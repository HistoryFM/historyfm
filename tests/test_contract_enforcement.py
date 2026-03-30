"""Tests for contract-first enforcement plumbing."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sovereign_ink.pipeline.errors import ContractEnforcementError
from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.pipeline.stages.stage4_prose_generation import ProseGenerationStage
from sovereign_ink.utils.config import GenerationConfig
from sovereign_ink.utils.text_quality import GateResult
from sovereign_ink.models.contracts import (
    AdversarialValidationResult,
    ComplianceReport,
    DeterministicValidationResult,
    SemanticValidationResult,
)


def _make_stage(config: GenerationConfig) -> ProseGenerationStage:
    stage = ProseGenerationStage.__new__(ProseGenerationStage)
    stage.config = config
    stage.state_manager = MagicMock()
    stage.llm = MagicMock()
    stage.prompts = MagicMock()
    return stage


class TestStage4StrictFailures(unittest.TestCase):
    def test_chapter_gates_raise_in_strict_mode(self):
        stage = _make_stage(
            GenerationConfig(
                contract_enforcement_mode="strict",
                gate_max_chapter_retries=1,
            )
        )
        stage._gate_correction_pass = MagicMock(return_value="chapter text")
        stage._save_gate_results = MagicMock()

        failing = GateResult(
            gate_name="immediate_jeopardy",
            passed=False,
            details={},
            report="failed",
        )
        with patch(
            "sovereign_ink.pipeline.stages.stage4_prose_generation.run_chapter_gates",
            return_value={"immediate_jeopardy": failing},
        ):
            with self.assertRaises(ContractEnforcementError):
                stage._apply_chapter_gates(
                    ch_num=1,
                    chapter_content="text",
                    system_prompt="sys",
                )

    def test_structural_failures_detect_scene_count_mismatch(self):
        stage = _make_stage(GenerationConfig())
        chapter_outline = SimpleNamespace(
            hard_reveal="reveal",
            soft_reversal="reversal",
            on_page_opposing_move="move",
            petty_moment="petty",
            ending_mode="cliffhanger_action",
        )
        scene_breakdown = SimpleNamespace(
            scenes=[
                SimpleNamespace(
                    scene_number=1,
                    opponent_move="blocks him",
                    pov_countermove="counters",
                    required_end_hook="",
                ),
                SimpleNamespace(
                    scene_number=2,
                    opponent_move="threatens",
                    pov_countermove="refuses",
                    required_end_hook="deadline remains",
                ),
            ]
        )
        failures = stage._structural_failures(
            chapter_content="Only one scene with no markdown split",
            scene_breakdown=scene_breakdown,
            chapter_outline=chapter_outline,
        )
        self.assertTrue(any("Scene count mismatch" in f for f in failures))

    def test_semantic_validator_disabled_is_non_blocking(self):
        stage = _make_stage(
            GenerationConfig(semantic_validator_enabled=False)
        )
        chapter_outline = SimpleNamespace(
            hard_reveal="hr",
            soft_reversal="sr",
            on_page_opposing_move="move",
            petty_moment="petty",
            ending_mode="cliffhanger_action",
        )
        scene_breakdown = SimpleNamespace(scenes=[])
        result = stage._run_semantic_contract_validator(
            ch_num=1,
            chapter_content="chapter",
            chapter_outline=chapter_outline,
            scene_breakdown=scene_breakdown,
        )
        self.assertTrue(result.passed)
        self.assertEqual([], result.failures)
        self.assertEqual("semantic_validator_disabled", result.raw_validator)

    def test_outline_critical_failure_raises_even_in_safe_mode(self):
        stage = _make_stage(GenerationConfig(contract_enforcement_mode="safe"))
        with self.assertRaises(ContractEnforcementError):
            stage._maybe_fail_contract(
                ch_num=1,
                message="critical acceptance failure",
                error_code="chapter_acceptance_failed",
            )

    def test_adversarial_trigger_never_disables_verifier(self):
        stage = _make_stage(
            GenerationConfig(
                adversarial_verifier_enabled=True,
                adversarial_trigger="never",
            )
        )
        deterministic = SimpleNamespace(passed=True)
        semantic = SimpleNamespace(passed=True, confidence=1.0)
        self.assertFalse(stage._should_trigger_adversarial(deterministic, semantic))

    def test_semantic_validator_malformed_output_returns_typed_failure(self):
        stage = _make_stage(
            GenerationConfig(
                semantic_validator_enabled=True,
                semantic_confidence_threshold=0.7,
            )
        )
        stage.prompts.render_validation = MagicMock(return_value="validation")
        stage.prompts.render_system_prompt = MagicMock(return_value="sys")
        stage.llm.generate_structured = MagicMock(side_effect=ValueError("bad json"))
        chapter_outline = SimpleNamespace(
            hard_reveal="hr",
            soft_reversal="sr",
            on_page_opposing_move="move",
            petty_moment="petty",
            ending_mode="cliffhanger_action",
        )
        scene_breakdown = SimpleNamespace(scenes=[])
        result = stage._run_semantic_contract_validator(
            ch_num=1,
            chapter_content="chapter",
            chapter_outline=chapter_outline,
            scene_breakdown=scene_breakdown,
        )
        self.assertFalse(result.passed)
        self.assertIn("semantic_validator_malformed_output", result.raw_validator)
        self.assertTrue(result.failures)

    def test_contract_preflight_flags_unmapped_beats(self):
        stage = _make_stage(GenerationConfig())
        chapter_outline = SimpleNamespace(
            chapter_number=1,
            hard_reveal="French garrison plans for New Orleans are revealed",
            soft_reversal="charm becomes obstruction after twenty minutes",
            on_page_opposing_move="note from Spanish minister appears on page",
            petty_moment="Livingston replays his correction in carriage",
        )
        scene_breakdown = SimpleNamespace(
            scenes=[
                SimpleNamespace(
                    scene_number=1,
                    setting="A quiet office",
                    turn="He writes a memo",
                    consequences="No new information arrives",
                    continuity_notes="",
                    opponent_move="silence",
                    pov_countermove="writes again",
                    required_end_hook="",
                )
            ]
        )
        preflight = stage._build_chapter_contract_preflight(
            chapter_outline, scene_breakdown
        )
        self.assertFalse(preflight["all_beats_mapped"])
        self.assertIn("hard_reveal", preflight["missing_beats"])


class TestStage5StrictFailures(unittest.TestCase):
    def test_outline_critical_failure_raises_even_in_safe_mode(self):
        stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
        stage.config = GenerationConfig(contract_enforcement_mode="safe")
        with self.assertRaises(ContractEnforcementError):
            stage._maybe_fail_contract(
                ch_num=1,
                message="revision pass contract failure",
                error_code="revision_pass_contract_failed",
            )

    def test_structural_non_regression_falls_back_when_scene_count_collapses(self):
        stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
        source = "S1\n\n---\n\nS2\n\n---\n\nS3\n\n---\n\nS4"
        revised = "S1\n\n---\n\nS2"
        result = stage._enforce_structural_non_regression(
            ch_num=2,
            pass_name="structural",
            source_content=source,
            revised_content=revised,
        )
        self.assertEqual(result, source)

    def test_revision_validation_syncs_report_acceptance_fields(self):
        stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
        stage.config = GenerationConfig()

        fake_report = ComplianceReport(
            chapter_number=1,
            status="failed",
            acceptance_passed=False,
            bypass_flags_used=[],
            deterministic=DeterministicValidationResult(
                passed=False,
                structural_passed=True,
                scene_contracts_passed=False,
                chapter_contracts_passed=True,
                failures=[],
                scene_results=[],
                chapter_requirements=[],
            ),
            semantic=SemanticValidationResult(
                passed=True,
                confidence=0.9,
                failures=[],
                requirement_results=[],
                raw_validator="mock",
            ),
            adversarial=AdversarialValidationResult(
                triggered=False,
                passed=True,
                reason="",
                requirement_results=[],
            ),
            retries={"chapter_gate_retries": 0, "scene_contract_retries": 0},
            model_routing={},
        )

        class FakeValidator:
            def _split_chapter_into_scenes(self, _):
                return []

            def _evaluate_compliance(self, **_kwargs):
                return fake_report

        stage._stage4_validator = MagicMock(return_value=FakeValidator())
        report, accepted = stage._validate_revision_contracts(
            ch_num=1,
            chapter_content="chapter",
            structure=None,
            final_acceptance=True,
        )
        self.assertTrue(accepted)
        self.assertTrue(report.acceptance_passed)
        self.assertEqual(report.status, "passed")


if __name__ == "__main__":
    unittest.main()

