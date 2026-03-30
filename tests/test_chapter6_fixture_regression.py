"""Regression fixture tests using phase11 chapter 6 assets."""

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sovereign_ink.models.contracts import (
    AdversarialValidationResult,
    SemanticValidationResult,
)
from sovereign_ink.pipeline.stages.stage4_prose_generation import ProseGenerationStage
from sovereign_ink.utils.config import GenerationConfig


ROOT = Path("/Users/dhrumilparekh/NovelGen")
PHASE11 = ROOT / "louisiana_purchase_phase11"


class TestChapter6FixtureRegression(unittest.TestCase):
    def test_phase11_chapter6_structural_contract_mismatch_detected(self):
        structure_path = PHASE11 / "structure" / "novel_structure.json"
        chapter_path = PHASE11 / "drafts" / "v3_polish" / "chapter_06.md"
        self.assertTrue(structure_path.exists())
        self.assertTrue(chapter_path.exists())

        structure_data = json.loads(structure_path.read_text(encoding="utf-8"))
        chapter_text = chapter_path.read_text(encoding="utf-8")

        chapter_outline = next(
            c for c in structure_data["chapter_outlines"] if c["chapter_number"] == 6
        )
        scene_breakdown = next(
            s for s in structure_data["scene_breakdowns"] if s["chapter_number"] == 6
        )

        stage = ProseGenerationStage.__new__(ProseGenerationStage)
        stage.config = GenerationConfig()

        # Convert dicts into simple attribute objects expected by helper.
        class Obj:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        outline_obj = Obj(**chapter_outline)
        scenes = [Obj(**scene) for scene in scene_breakdown["scenes"]]
        scene_obj = Obj(scenes=scenes)

        failures = stage._structural_failures(
            chapter_content=chapter_text,
            scene_breakdown=scene_obj,
            chapter_outline=outline_obj,
        )
        self.assertTrue(
            failures,
            "Expected known phase11 chapter_06 fixture to trigger structural failures.",
        )

        stage._run_semantic_contract_validator = MagicMock(
            return_value=SemanticValidationResult(
                passed=True,
                confidence=1.0,
                failures=[],
                requirement_results=[],
                raw_validator="mock",
            )
        )
        stage._run_adversarial_validator = MagicMock(
            return_value=AdversarialValidationResult(
                triggered=False,
                passed=True,
                reason="",
                requirement_results=[],
            )
        )
        report = stage._evaluate_compliance(
            ch_num=6,
            chapter_content=chapter_text,
            chapter_outline=outline_obj,
            scene_breakdown=scene_obj,
            scene_reports=[],
        )
        self.assertFalse(
            report.acceptance_passed,
            "Known chapter_06 fixture must fail acceptance before repair convergence.",
        )


if __name__ == "__main__":
    unittest.main()

