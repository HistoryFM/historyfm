"""Tests for Phase 9 changes:
- Change A: Deterministic chapter completion gate
- Change B: Ending propulsion retry hardening
- Change C: Exposition-drag non-regression contract
- Change D: Long-chapter dedup-first surgery
"""

import pytest

from sovereign_ink.utils.text_quality import (
    detect_incomplete_chapter_ending,
    gate_complete_chapter_ending,
    run_chapter_gates,
    compute_quality_delta,
)
from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.utils.config import GenerationConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

COMPLETE_ENDING = """
The chamber fell silent. Talleyrand folded the document, tucked it beneath
his coat, and walked to the door without looking back. Outside, the Seine
caught the last light of the afternoon.

"Monsieur," Livingston called.

Talleyrand paused at the threshold but did not turn. "Tomorrow," he said.
"Come alone." The door closed before Livingston could answer.
""".strip()

TRUNCATED_ENDING_BARE_DASH = """
Jefferson read the despatch twice, then set it on the desk. The implications
were clear enough. If Monroe had failed to secure even a preliminary—
""".strip()

TRUNCATED_ENDING_DANGLING_FUNCTION_WORD = """
The vote was called. Every senator turned to face the
""".strip()

TRUNCATED_ENDING_MISSING_PUNCTUATION = """
Livingston crossed the room to where the candle guttered on the mantle
He read the final clause again
""".strip()

TRUNCATED_ENDING_UNMATCHED_QUOTE = """
"I have told you everything," Talleyrand said. "Every condition, every term.
What more could you want?"

Livingston looked at the document. "You forgot one
""".strip()

REFLECTIVE_WEAK_ENDING = """
---

Jefferson sat alone in the study long after the candles had burned low. He
thought about everything that had happened, reflecting on the choices he had
made and wondering whether history would judge him fairly. It had been a
difficult day. He felt the weight of it all pressing down on him as he sat
in the quiet room, alone with his thoughts, contemplating the future.
""".strip()

PROPULSIVE_ENDING = """
---

The messenger arrived at midnight, his horse lathered and his coat wet. He
handed Jefferson a sealed packet without speaking. Jefferson broke the wax
and read the first three lines.

He reached for the pen. If he did not sign Monroe's commission before the
Senate reconvened at dawn, Pickering would force a floor vote — and
Jefferson had no constitutional answer that would survive the afternoon.
""".strip()


# ---------------------------------------------------------------------------
# Change A: Chapter completion detector
# ---------------------------------------------------------------------------

class TestDetectIncompleteChapterEnding:
    def test_complete_ending_returns_empty(self):
        result = detect_incomplete_chapter_ending(COMPLETE_ENDING)
        assert result == {}, f"Expected no findings, got: {result}"

    def test_bare_dash_detected(self):
        result = detect_incomplete_chapter_ending(TRUNCATED_ENDING_BARE_DASH)
        assert result, "Expected findings for bare-dash ending"
        reasons = result.get("reasons", [])
        assert any("dash" in r.lower() for r in reasons), \
            f"Expected a dash-related reason, got: {reasons}"

    def test_dangling_function_word_detected(self):
        result = detect_incomplete_chapter_ending(TRUNCATED_ENDING_DANGLING_FUNCTION_WORD)
        assert result, "Expected findings for dangling-function-word ending"
        reasons = result.get("reasons", [])
        assert any("dangling" in r.lower() or "function word" in r.lower() or "cut" in r.lower()
                   for r in reasons), f"Expected abrupt-ending reason, got: {reasons}"

    def test_unmatched_quote_detected(self):
        result = detect_incomplete_chapter_ending(TRUNCATED_ENDING_UNMATCHED_QUOTE)
        assert result, "Expected findings for unmatched-quote ending"
        reasons = result.get("reasons", [])
        assert any("quote" in r.lower() or "dialogue" in r.lower() for r in reasons), \
            f"Expected quote-related reason, got: {reasons}"

    def test_empty_text_returns_empty(self):
        assert detect_incomplete_chapter_ending("") == {}
        assert detect_incomplete_chapter_ending("   ") == {}


class TestGateCompleteChapterEnding:
    def test_complete_ending_passes(self):
        result = gate_complete_chapter_ending(COMPLETE_ENDING)
        assert result.passed
        assert result.gate_name == "complete_chapter_ending"

    def test_truncated_ending_fails(self):
        result = gate_complete_chapter_ending(TRUNCATED_ENDING_BARE_DASH)
        assert not result.passed
        assert "CHAPTER COMPLETION FAILURE" in result.report

    def test_gate_in_run_chapter_gates(self):
        gates = run_chapter_gates(COMPLETE_ENDING)
        assert "complete_chapter_ending" in gates
        assert gates["complete_chapter_ending"].gate_name == "complete_chapter_ending"

    def test_gate_in_run_chapter_gates_truncated(self):
        gates = run_chapter_gates(TRUNCATED_ENDING_BARE_DASH)
        assert not gates["complete_chapter_ending"].passed


# ---------------------------------------------------------------------------
# Change B: Ending propulsion retry hardening
# ---------------------------------------------------------------------------

class TestBuildEndingRetryContext:
    def test_non_strict_returns_directive(self):
        ctx = RevisionPipelineStage._build_ending_retry_context(
            ending_deficit={},
            ending_mode="crisis deadline",
            strict_template=False,
        )
        assert "ENDING-ONLY RETRY DIRECTIVE" in ctx
        assert "STRICT ENDING CONTRACT" not in ctx

    def test_strict_template_adds_contract(self):
        ctx = RevisionPipelineStage._build_ending_retry_context(
            ending_deficit={},
            ending_mode="",
            strict_template=True,
        )
        assert "STRICT ENDING CONTRACT" in ctx
        assert "FORBIDDEN" in ctx
        assert "REQUIRED" in ctx

    def test_strict_template_denies_reflective_deceleration(self):
        ctx = RevisionPipelineStage._build_ending_retry_context(
            ending_deficit={},
            ending_mode="",
            strict_template=True,
        )
        assert "Pure reflection" in ctx or "pure reflection" in ctx.lower()


class TestEndingHasUnresolvedAction:
    def test_propulsive_ending_passes(self):
        assert RevisionPipelineStage._ending_has_unresolved_action(PROPULSIVE_ENDING)

    def test_reflective_ending_fails(self):
        assert not RevisionPipelineStage._ending_has_unresolved_action(REFLECTIVE_WEAK_ENDING)

    def test_deadline_marker_passes(self):
        text = "He had until midnight to sign the order. " * 5 + "The clock was running."
        assert RevisionPipelineStage._ending_has_unresolved_action(text)

    def test_pure_reflection_fails(self):
        text = (
            "He thought about it. He wondered what it meant. He reflected on the "
            "long journey. He contemplated the future alone in the quiet room. "
            "He considered all that had passed."
        )
        assert not RevisionPipelineStage._ending_has_unresolved_action(text)


# ---------------------------------------------------------------------------
# Change C: Exposition-drag non-regression contract
# ---------------------------------------------------------------------------

class TestCriticalRegressionsExpositionDrag:
    def _make_config(self, include_drag: bool) -> GenerationConfig:
        return GenerationConfig(
            critical_retry_include_exposition_drag=include_drag,
        )

    def _make_stage(self, config: GenerationConfig):
        """Create a RevisionPipelineStage without a real project dir."""
        class FakeStateManager:
            project_dir = None
        stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
        stage.config = config
        return stage

    def test_exposition_drag_excluded_by_default(self):
        config = self._make_config(include_drag=False)
        stage = self._make_stage(config)
        delta = {
            "regressions": [
                {"metric": "exposition_drag_runs", "delta": 2, "before": 1, "after": 3},
            ]
        }
        result = stage._critical_regressions(delta)
        assert result == [], "exposition_drag_runs should not be critical when flag is False"

    def test_exposition_drag_included_when_flag_set(self):
        config = self._make_config(include_drag=True)
        stage = self._make_stage(config)
        delta = {
            "regressions": [
                {"metric": "exposition_drag_runs", "delta": 2, "before": 1, "after": 3},
            ]
        }
        result = stage._critical_regressions(delta)
        assert len(result) == 1
        assert result[0]["metric"] == "exposition_drag_runs"

    def test_existing_critical_metrics_still_apply(self):
        config = self._make_config(include_drag=False)
        stage = self._make_stage(config)
        delta = {
            "regressions": [
                {"metric": "repetition_patterns", "delta": 5, "before": 10, "after": 15},
                {"metric": "sensory_deficit_scenes", "delta": 1, "before": 2, "after": 3},
            ]
        }
        result = stage._critical_regressions(delta)
        assert len(result) == 2


class TestBuildExpositionMomentumMacro:
    def test_returns_macro_with_pattern(self):
        delta = {
            "regressions": [
                {"metric": "exposition_drag_runs", "delta": 2, "before": 1, "after": 3},
            ]
        }
        macro = RevisionPipelineStage._build_exposition_momentum_macro(delta)
        assert "EXPOSITION MOMENTUM RECOVERY" in macro
        assert "Ask → Deny → Pressure → Countermove" in macro
        assert "1" in macro and "3" in macro  # before/after counts

    def test_macro_prohibits_summary_replacement(self):
        macro = RevisionPipelineStage._build_exposition_momentum_macro({"regressions": []})
        assert "summary prose" in macro.lower() or "Prohibit" in macro


# ---------------------------------------------------------------------------
# Change D: Long-chapter dedup config flags
# ---------------------------------------------------------------------------

class TestDeduplicateConfig:
    def test_dedup_config_defaults(self):
        config = GenerationConfig()
        assert config.enable_long_chapter_dedup_first is False
        assert config.dedup_first_soft_cap_words == 5000

    def test_dedup_config_override(self):
        config = GenerationConfig(
            enable_long_chapter_dedup_first=True,
            dedup_first_soft_cap_words=4000,
        )
        assert config.enable_long_chapter_dedup_first is True
        assert config.dedup_first_soft_cap_words == 4000


# ---------------------------------------------------------------------------
# Config flags all present with correct defaults
# ---------------------------------------------------------------------------

class TestPhase9ConfigDefaults:
    def test_completion_gate_defaults(self):
        config = GenerationConfig()
        assert config.enable_chapter_completion_gate is False
        assert config.gate_max_completion_retries == 2

    def test_exposition_drag_retry_default(self):
        config = GenerationConfig()
        assert config.critical_retry_include_exposition_drag is False

    def test_dedup_first_defaults(self):
        config = GenerationConfig()
        assert config.enable_long_chapter_dedup_first is False
        assert config.dedup_first_soft_cap_words == 5000
