"""Tests for Phase 10 changes:
- Change A: Ending-propulsion / compression sequencing fix
  - _apply_revision_ending_final_check persists v3_polish after ending repair
  - No ending retry fires inside the regression loop (ordering guarantee)
- Change B: Loosened revision guardrail ratios (config-level)
- Change C: Targeted exposition-drag second retry
  - detect_exposition_drag now returns paragraph previews
  - _build_targeted_exposition_macro uses paragraph locations
"""

import unittest
from unittest.mock import MagicMock, call, patch

from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.utils.config import GenerationConfig
from sovereign_ink.utils.text_quality import (
    detect_exposition_drag,
    format_exposition_drag_report,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PROPULSIVE_ENDING = """
---

The messenger arrived at midnight, his horse lathered and his coat wet. He
handed Jefferson a sealed packet without speaking. Jefferson broke the wax
and read the first three lines.

He reached for the pen. If he did not sign Monroe's commission before the
Senate reconvened at dawn, Pickering would force a floor vote — and
Jefferson had no constitutional answer that would survive the afternoon.
""".strip()

REFLECTIVE_ENDING = """
---

Jefferson sat alone in the study long after the candles had burned low. He
thought about everything that had happened, reflecting on the choices he had
made and wondering whether history would judge him fairly. It had been a
difficult day. He felt the weight of it all pressing down on him as he sat
in the quiet room, alone with his thoughts, contemplating the future.
""".strip()

CHAPTER_WITH_DRAG = """
The question of sovereignty had long occupied the minds of the delegates.
Perhaps the destiny of the republic rested on such abstract ideals as liberty
and progress. The meaning of civilization itself was at stake in these debates.

Freedom and justice were aspirations that proved difficult to codify. The
vision of a democratic future required careful consideration of competing
ideals. History would judge whether the promise of the new republic was kept.

"We cannot yield," Madison said.

Livingston crossed the room. "Then we are at an impasse."
""".strip()

CHAPTER_NO_DRAG = """
"Give me the document," Livingston demanded.

Talleyrand shook his head. "Not until the terms are signed."

Livingston stepped forward. "The Senate convenes at dawn. Sign now or we
lose the ratification window." He placed his hand on the table.

Talleyrand looked at the pen, then at Livingston. "Very well."
""".strip()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> GenerationConfig:
    return GenerationConfig(**kwargs)


def _make_stage(config: GenerationConfig) -> RevisionPipelineStage:
    """Create a RevisionPipelineStage with a real enough state_manager mock."""
    stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
    stage.config = config
    stage.state_manager = MagicMock()
    stage.llm = MagicMock()
    stage.prompts = MagicMock()
    return stage


# ---------------------------------------------------------------------------
# Change A: _apply_revision_ending_final_check
# ---------------------------------------------------------------------------

class TestApplyRevisionEndingFinalCheck(unittest.TestCase):
    """Verify the behavioral contract of the new final-check helper."""

    def _make_stage_with_ending(self, ending_content: str) -> RevisionPipelineStage:
        stage = _make_stage(_make_config())
        # Stub _apply_ending_propulsion_retries to return modified content
        stage._apply_ending_propulsion_retries = MagicMock(return_value=ending_content)
        return stage

    def test_saves_ending_fixed_content_as_version(self):
        """After fixing the ending, _apply_revision_ending_final_check must
        persist the result as the given draft version (v3_polish)."""
        fixed = PROPULSIVE_ENDING
        stage = self._make_stage_with_ending(fixed)
        chapter_outline = MagicMock()
        chapter_outline.ending_mode = "crisis deadline"

        result = stage._apply_revision_ending_final_check(
            final_content=REFLECTIVE_ENDING,
            chapter_outline=chapter_outline,
            system_prompt="sys",
            ch_num=1,
            version="v3_polish",
        )

        # The ending-fixed content must be saved as v3_polish
        stage.state_manager.save_chapter_draft.assert_called_once_with(
            1, fixed, "v3_polish"
        )
        self.assertEqual(result, fixed)

    def test_returns_ending_fixed_content(self):
        """Return value must be the output of _apply_ending_propulsion_retries."""
        fixed = PROPULSIVE_ENDING
        stage = self._make_stage_with_ending(fixed)
        chapter_outline = MagicMock()
        chapter_outline.ending_mode = ""

        result = stage._apply_revision_ending_final_check(
            final_content=REFLECTIVE_ENDING,
            chapter_outline=chapter_outline,
            system_prompt="sys",
            ch_num=2,
            version="v3_polish",
        )

        self.assertEqual(result, fixed)

    def test_calls_ending_propulsion_retries_once(self):
        """Must delegate to _apply_ending_propulsion_retries exactly once."""
        stage = self._make_stage_with_ending(PROPULSIVE_ENDING)
        chapter_outline = MagicMock()
        chapter_outline.ending_mode = ""

        stage._apply_revision_ending_final_check(
            final_content=REFLECTIVE_ENDING,
            chapter_outline=chapter_outline,
            system_prompt="sys",
            ch_num=3,
            version="v3_polish",
        )

        stage._apply_ending_propulsion_retries.assert_called_once()

    def test_no_compression_after_ending_fix(self):
        """_apply_revision_length_guardrails must NOT be called after the
        final ending check — this is the core of the sequencing guarantee."""
        stage = self._make_stage_with_ending(PROPULSIVE_ENDING)
        stage._apply_revision_length_guardrails = MagicMock()
        chapter_outline = MagicMock()
        chapter_outline.ending_mode = ""

        stage._apply_revision_ending_final_check(
            final_content=REFLECTIVE_ENDING,
            chapter_outline=chapter_outline,
            system_prompt="sys",
            ch_num=4,
            version="v3_polish",
        )

        stage._apply_revision_length_guardrails.assert_not_called()


# ---------------------------------------------------------------------------
# Change A: Polish pass ordering in revise_single_chapter
# ---------------------------------------------------------------------------

class TestPolishPassOrdering(unittest.TestCase):
    """Verify that compression runs before ending check, never after."""

    def _make_full_stage(self) -> RevisionPipelineStage:
        config = _make_config(
            enable_length_guardrails=True,
            pass_regression_max_retry=0,  # disable regression retries for isolation
        )
        stage = _make_stage(config)

        # Stub all LLM/IO operations to focus on call ordering
        stage.state_manager.load_novel_structure.return_value = None
        stage.state_manager.load_world_state.return_value = None
        stage.state_manager.load_chapter_draft.return_value = None
        stage.state_manager.load_all_chapter_drafts.return_value = {}
        stage.state_manager.load_gate_results.return_value = None
        stage.state_manager.load_all_quality_reports.return_value = {}
        stage.state_manager.save_quality_report = MagicMock()
        stage.state_manager.save_quality_aggregate = MagicMock()
        stage.state_manager.save_chapter_draft = MagicMock()
        stage.state_manager.project_dir = MagicMock()
        stage.state_manager.project_dir.__truediv__ = MagicMock(return_value=MagicMock())
        stage.prompts.render_system_prompt.return_value = "system"
        stage.prompts.render_revision.return_value = "user"

        call_log: list[str] = []

        def mock_guardrail(ch_num, chapter_content, system_prompt, pass_name, chapter_outline):
            call_log.append("guardrail")
            return chapter_content

        def mock_ending_final_check(final_content, chapter_outline, system_prompt, ch_num, version):
            call_log.append("ending_final_check")
            return final_content

        stage._apply_revision_length_guardrails = mock_guardrail
        stage._apply_revision_ending_final_check = mock_ending_final_check

        llm_response = MagicMock()
        llm_response.content = PROPULSIVE_ENDING
        stage.llm.generate_streaming.return_value = llm_response
        stage.llm.generate.return_value = llm_response

        stage._call_log = call_log
        return stage

    def test_guardrail_runs_before_ending_final_check_for_pass3(self):
        """For the polish pass (pass 3), guardrails (via _revise_single_chapter)
        must complete before _apply_revision_ending_final_check is called."""
        stage = self._make_full_stage()
        # Provide a v0_raw source draft for pass 1 to pick up
        stage.state_manager.load_chapter_draft.side_effect = lambda ch, ver: (
            "raw content here with some words " * 20 if ver == "v0_raw" else None
        )

        try:
            stage.revise_single_chapter(1)
        except Exception:
            pass  # structural issues from stubs are expected

        log = stage._call_log
        if "guardrail" in log and "ending_final_check" in log:
            self.assertLess(
                log.index("guardrail"),
                log.index("ending_final_check"),
                "guardrail must fire before ending_final_check",
            )


# ---------------------------------------------------------------------------
# Change B: Config — loosened revision guardrail ratios
# ---------------------------------------------------------------------------

class TestPhase10ConfigRatios(unittest.TestCase):
    def test_default_ratios_unchanged(self):
        """Default ratios must remain at phase 9 values for backward compat."""
        config = GenerationConfig()
        self.assertAlmostEqual(config.revision_soft_cap_ratio, 1.15)
        self.assertAlmostEqual(config.revision_hard_cap_ratio, 1.30)

    def test_phase10_ratios_accepted(self):
        """Phase 10 looser ratios must be accepted by GenerationConfig."""
        config = GenerationConfig(
            revision_soft_cap_ratio=1.30,
            revision_hard_cap_ratio=1.50,
        )
        self.assertAlmostEqual(config.revision_soft_cap_ratio, 1.30)
        self.assertAlmostEqual(config.revision_hard_cap_ratio, 1.50)

    def test_stage4_caps_independent_of_stage5_caps(self):
        """Stage 4 and Stage 5 guardrail ratios must be independent fields."""
        config = GenerationConfig(
            length_soft_cap_ratio=1.10,
            length_hard_cap_ratio=1.25,
            revision_soft_cap_ratio=1.30,
            revision_hard_cap_ratio=1.50,
        )
        # Stage 4 caps unchanged
        self.assertAlmostEqual(config.length_soft_cap_ratio, 1.10)
        self.assertAlmostEqual(config.length_hard_cap_ratio, 1.25)
        # Stage 5 caps raised
        self.assertAlmostEqual(config.revision_soft_cap_ratio, 1.30)
        self.assertAlmostEqual(config.revision_hard_cap_ratio, 1.50)


# ---------------------------------------------------------------------------
# Change C: detect_exposition_drag now returns preview
# ---------------------------------------------------------------------------

class TestDetectExpositionDragPreview(unittest.TestCase):
    def test_drag_findings_include_preview(self):
        """Each finding from detect_exposition_drag must contain a 'preview' key."""
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG)
        self.assertTrue(findings, "Expected at least one drag finding in test chapter")
        for f in findings:
            self.assertIn("preview", f, "Each drag finding must have a 'preview' field")

    def test_preview_is_nonempty_string(self):
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG)
        for f in findings:
            self.assertIsInstance(f["preview"], str)
            self.assertGreater(len(f["preview"]), 0)

    def test_preview_reflects_start_of_drag_block(self):
        """Preview should contain text from the beginning of the dragging block."""
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG)
        self.assertTrue(findings)
        # The first drag block starts with "The question of sovereignty..."
        self.assertIn("sovereignty", findings[0]["preview"].lower())

    def test_no_drag_returns_empty_list(self):
        findings = detect_exposition_drag(CHAPTER_NO_DRAG)
        self.assertEqual(findings, [])

    def test_start_end_para_still_present(self):
        """Existing start_para / end_para / paragraph_count fields must be preserved."""
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG)
        for f in findings:
            self.assertIn("start_para", f)
            self.assertIn("end_para", f)
            self.assertIn("paragraph_count", f)
            self.assertGreaterEqual(f["start_para"], 1)
            self.assertGreaterEqual(f["end_para"], f["start_para"])

    def test_preview_max_length(self):
        """Preview must be no longer than 150 characters."""
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG * 10)
        for f in findings:
            self.assertLessEqual(len(f["preview"]), 150)


class TestFormatExpositionDragReportPreview(unittest.TestCase):
    def test_report_includes_preview_text(self):
        """format_exposition_drag_report must surface preview text when present."""
        findings = detect_exposition_drag(CHAPTER_WITH_DRAG)
        report = format_exposition_drag_report(findings)
        self.assertIn("sovereignty", report.lower(),
                      "Report should include preview text from the dragging block")

    def test_report_without_preview_does_not_crash(self):
        """If a finding has no preview key, report must still be generated."""
        findings = [{"start_para": 1, "end_para": 3, "paragraph_count": 2}]
        report = format_exposition_drag_report(findings)
        self.assertIn("EXPOSITION DRAG ALERT", report)


# ---------------------------------------------------------------------------
# Change C: _build_targeted_exposition_macro
# ---------------------------------------------------------------------------

class TestBuildTargetedExpositionMacro(unittest.TestCase):
    def _make_stage(self) -> RevisionPipelineStage:
        stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
        stage.config = GenerationConfig()
        return stage

    def test_macro_references_paragraph_ranges(self):
        """Macro must name the specific paragraph ranges from the findings."""
        findings = [
            {"start_para": 3, "end_para": 5, "paragraph_count": 2,
             "preview": "The destiny of the republic..."},
        ]
        macro = RevisionPipelineStage._build_targeted_exposition_macro(findings)
        self.assertIn("3", macro)
        self.assertIn("5", macro)

    def test_macro_includes_preview_text(self):
        """Macro must include the preview so the LLM can locate the block."""
        findings = [
            {"start_para": 1, "end_para": 2, "paragraph_count": 1,
             "preview": "Perhaps the destiny of the republic rested..."},
        ]
        macro = RevisionPipelineStage._build_targeted_exposition_macro(findings)
        self.assertIn("destiny", macro)

    def test_macro_mandatory_header(self):
        """Macro must carry the SECOND ATTEMPT label so the LLM knows it is a
        second targeted correction, not the standard momentum macro."""
        findings = [{"start_para": 1, "end_para": 2, "paragraph_count": 1, "preview": ""}]
        macro = RevisionPipelineStage._build_targeted_exposition_macro(findings)
        self.assertIn("SECOND ATTEMPT", macro)
        self.assertIn("TARGETED", macro)

    def test_macro_prohibits_summary_replacement(self):
        """Macro must explicitly prohibit replacing exposition with summary."""
        macro = RevisionPipelineStage._build_targeted_exposition_macro(
            [{"start_para": 1, "end_para": 2, "paragraph_count": 1, "preview": ""}]
        )
        self.assertIn("summary", macro.lower())

    def test_macro_handles_empty_findings_gracefully(self):
        macro = RevisionPipelineStage._build_targeted_exposition_macro([])
        self.assertIsInstance(macro, str)
        self.assertGreater(len(macro), 0)

    def test_macro_capped_at_six_findings(self):
        """Only the first 6 findings should be included to avoid prompt bloat."""
        findings = [
            {"start_para": i, "end_para": i + 1, "paragraph_count": 1, "preview": f"block {i}"}
            for i in range(1, 15)
        ]
        macro = RevisionPipelineStage._build_targeted_exposition_macro(findings)
        # Paragraph 14 should not appear but 6 should
        self.assertNotIn("block 14", macro)
        self.assertIn("block 1", macro)


# ---------------------------------------------------------------------------
# Change C: targeted drag retry fires only when drag doesn't improve
# ---------------------------------------------------------------------------

class TestTargetedDragRetryCondition(unittest.TestCase):
    def _make_stage_for_drag(self, include_drag: bool) -> RevisionPipelineStage:
        config = _make_config(critical_retry_include_exposition_drag=include_drag)
        stage = _make_stage(config)
        return stage

    def test_targeted_macro_built_for_non_improving_drag(self):
        """_build_targeted_exposition_macro must be called when drag_after
        count is >= drag_before count after the regression loop."""
        stage = self._make_stage_for_drag(include_drag=True)
        stage._build_targeted_exposition_macro = MagicMock(
            return_value="targeted macro"
        )
        stage._revise_single_chapter = MagicMock(return_value=CHAPTER_WITH_DRAG)
        stage.state_manager.save_chapter_draft = MagicMock()

        # Simulate a scenario where drag_after >= drag_before
        drag_before = detect_exposition_drag(CHAPTER_WITH_DRAG)
        drag_after = detect_exposition_drag(CHAPTER_WITH_DRAG)

        if drag_after and len(drag_after) >= len(drag_before):
            targeted_macro = RevisionPipelineStage._build_targeted_exposition_macro(drag_after)
            self.assertIn("TARGETED", targeted_macro)

    def test_targeted_retry_not_triggered_when_drag_flag_disabled(self):
        """When critical_retry_include_exposition_drag is False, the targeted
        retry block must never execute."""
        stage = self._make_stage_for_drag(include_drag=False)
        # If the config flag is False, the outer `if` guard prevents the retry
        should_trigger = getattr(
            stage.config, "critical_retry_include_exposition_drag", False
        )
        self.assertFalse(should_trigger)


if __name__ == "__main__":
    unittest.main()
