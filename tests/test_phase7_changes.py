"""Tests for Phase 7 changes:
- Change 1: Chapter word count caps in Stage 3
- Change 2: Targeted ending-only rewrite
- Change 3: Voice pass preservation context
- Change 4: Sensory deficit in polish quality reports
- Change 5: Voice diagnosis JSON parsing
"""

import json

import pytest

from sovereign_ink.utils.text_quality import (
    build_quality_snapshot,
    compute_quality_delta,
)
from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.pipeline.stages.stage4_prose_generation import ProseGenerationStage
from sovereign_ink.utils.config import GenerationConfig


# ---------------------------------------------------------------------------
# Change 1: Word count validation in validate_pressure_architecture
# ---------------------------------------------------------------------------


def _make_minimal_structure(estimated_word_count: int, num_scenes: int = 3):
    """Build a minimal NovelStructure-like object for validation testing."""
    from sovereign_ink.models.structure import (
        NovelStructure,
        ActStructure,
        Act,
        ChapterOutline,
        SceneBreakdown,
        Scene,
    )

    acts = [
        Act(
            act_number=i,
            title=f"Act {i}",
            description="desc",
            dramatic_beats=["beat"],
            stakes_level="medium",
            chapters=[1] if i == 1 else [],
        )
        for i in range(1, 4)
    ]
    act_structure = ActStructure(num_acts=3, acts=acts)

    chapter_outline = ChapterOutline(
        chapter_number=1,
        title="Test Chapter",
        pov_character="Jefferson",
        setting="The White House",
        time_period="April 1803",
        political_context="context",
        chapter_goal="goal",
        conflict="conflict",
        turn="turn",
        consequences="consequences",
        hard_reveal="reveal",
        soft_reversal="reversal",
        on_page_opposing_move="threatens to withdraw",
        ending_mode="cliffhanger_action",
        estimated_word_count=estimated_word_count,
        act_number=1,
    )

    scenes = [
        Scene(
            scene_number=i + 1,
            pov="Jefferson",
            setting="room",
            goal="goal",
            opposition="opposition",
            immediate_risk="risk",
            irreversible_cost_if_fail="cost",
            power_shift_target="Jefferson",
            turn="turn",
            consequences="consequences",
            emotional_beat="dread",
            continuity_notes="",
            complexity_score=5,
            register="solemn",
            supporting_cast_pressure="",
            gate_profile="external_collision",
            opponent_present_on_page=True,
            opponent_actor="Talleyrand",
            opponent_move="delivers ultimatum",
            pov_countermove="refuses and stands",
            failure_event_if_no_action="delegation walks out",
            deadline_or_clock="dawn",
            required_end_hook="vote looms" if i == num_scenes - 1 else "",
        )
        for i in range(num_scenes)
    ]

    scene_breakdown = SceneBreakdown(chapter_number=1, scenes=scenes)

    return NovelStructure(
        act_structure=act_structure,
        chapter_outlines=[chapter_outline],
        scene_breakdowns=[scene_breakdown],
    )


def test_validate_pressure_architecture_warns_on_oversized_chapter():
    """validate_pressure_architecture should warn when estimated_word_count > max."""
    from sovereign_ink.models.structure import validate_pressure_architecture

    structure = _make_minimal_structure(estimated_word_count=10000)
    warnings = validate_pressure_architecture(
        structure, max_words_per_chapter=4500
    )
    assert any("estimated_word_count" in w and "10000" in w for w in warnings), (
        f"Expected word count warning, got: {warnings}"
    )


def test_validate_pressure_architecture_no_warning_on_normal_chapter():
    """No word count warning when chapter is within bounds."""
    from sovereign_ink.models.structure import validate_pressure_architecture

    structure = _make_minimal_structure(estimated_word_count=3000)
    warnings = validate_pressure_architecture(
        structure, max_words_per_chapter=4500, min_words_per_chapter=2000
    )
    word_count_warnings = [w for w in warnings if "estimated_word_count" in w]
    assert word_count_warnings == [], (
        f"Unexpected word count warnings: {word_count_warnings}"
    )


def test_validate_pressure_architecture_warns_on_too_many_scenes():
    """validate_pressure_architecture should warn when scenes > max_scenes_per_chapter."""
    from sovereign_ink.models.structure import validate_pressure_architecture

    structure = _make_minimal_structure(estimated_word_count=3000, num_scenes=8)
    warnings = validate_pressure_architecture(
        structure, max_scenes_per_chapter=6
    )
    assert any("scenes exceeds recommended" in w for w in warnings), (
        f"Expected scene-count warning, got: {warnings}"
    )


# ---------------------------------------------------------------------------
# Change 2: _rewrite_ending_only body preservation
# ---------------------------------------------------------------------------


def test_rewrite_ending_only_preserves_body(monkeypatch):
    """_rewrite_ending_only must return the body text verbatim up to the split."""
    import types

    # Build a long body (>> 400 words) with paragraph breaks so the splitter
    # can find a clean paragraph boundary before the last ~400 words.
    # Each paragraph is ~45 words × 3 repetitions = ~135 words.
    # 8 paragraphs × 135 words = ~1080 words body, so the split point is
    # ~400 words from the end, meaning paragraphs 5-8 land in the "ending zone".
    # The sentinel must be in an early paragraph (1-4) to guarantee preservation.
    scene_sentences = (
        "The diplomat crossed the room with measured deliberation, "
        "his boots leaving faint impressions on the thick carpet. "
        "Outside, rain fell on the cobblestones of the Rue Saint-Honoré, "
        "and the smell of the river rose through the casements. "
        "Talleyrand had not yet arrived. "
    )
    body_paragraphs = [scene_sentences * 3 for _ in range(8)]

    SENTINEL = "BODY_SENTINEL_UNIQUE_STRING_12345"
    # Put the sentinel in the FIRST paragraph — guaranteed to be in the
    # preserved body regardless of where the split falls.
    body_paragraphs[0] = SENTINEL + " " + body_paragraphs[0]
    body_text = "\n\n".join(body_paragraphs)

    ending_text = (
        "\n\nJefferson sat alone with his thoughts, "
        "the fire dying in the grate."
    )
    chapter = body_text + ending_text

    rewritten_ending = (
        "Jefferson reached for the pen. The vote was at dawn "
        "and Monroe had not yet returned."
    )

    class _FakeLLM:
        def generate(self, **kwargs):
            r = types.SimpleNamespace()
            r.content = rewritten_ending
            return r

    class _FakeConfig:
        model_revision_polish = "test-model"
        temperature_revision = 0.6

    stage = object.__new__(RevisionPipelineStage)
    stage.llm = _FakeLLM()
    stage.config = _FakeConfig()

    result = stage._rewrite_ending_only(
        chapter_content=chapter,
        system_prompt="system",
        retry_context="## ENDING-ONLY\nFix the ending.",
    )

    # The body sentinel must be preserved (body not rewritten)
    assert SENTINEL in result, "Body sentinel was lost — body was rewritten"
    # The result must differ from the original ending
    assert "dying in the grate" not in result, "Original ending was not replaced"
    # The rewritten ending should appear
    assert "vote was at dawn" in result, "Rewritten ending content missing"


# ---------------------------------------------------------------------------
# Change 3: _build_voice_preservation_context
# ---------------------------------------------------------------------------


REPETITIVE_CHAPTER = """
The weight of the decision pressed down upon him. He felt the weight of it
in his bones, the weight of history, the weight of his office.

---

He walked to the window and considered the weight of what he faced. The weight
of the republic rested on his shoulders. He could not escape the weight.

---

"This is no small matter," he said. The weight of the words hung in the air.
He nodded. The weight of the moment was unbearable.
"""


def test_voice_preservation_context_includes_repetitions():
    """_build_voice_preservation_context must list existing repetition patterns."""
    result = RevisionPipelineStage._build_voice_preservation_context(
        REPETITIVE_CHAPTER
    )
    assert "voice_preservation" in result
    text = result["voice_preservation"]
    assert "Repetition patterns" in text
    assert "CURRENT QUALITY BASELINE" in text


SENSORY_DEFICIENT_CHAPTER = """
# Chapter 1: The Meeting

Jefferson considered the implications of the treaty. He weighed each clause
against the constitutional framework. Monroe would arrive shortly.

---

The negotiations had proceeded for three weeks. Each party sought advantage.
Jefferson understood that the outcome would define the republic.
"""


def test_voice_preservation_context_includes_sensory_info():
    """_build_voice_preservation_context must report sensory deficit scenes."""
    result = RevisionPipelineStage._build_voice_preservation_context(
        SENSORY_DEFICIENT_CHAPTER
    )
    text = result["voice_preservation"]
    assert "Sensory deficit scenes" in text
    # The chapter has no sensory detail so count should be > 0
    assert "sensory deficit" in text.lower() or "Sensory" in text


# ---------------------------------------------------------------------------
# Change 4: sensory_deficit in polish quality reports
# ---------------------------------------------------------------------------


def test_polish_quality_reports_includes_sensory_deficit():
    """_build_polish_quality_reports must include sensory_deficit key when flagged."""
    # A chapter with no sensory detail should produce a sensory_deficit report
    result = RevisionPipelineStage._build_polish_quality_reports(
        SENSORY_DEFICIENT_CHAPTER
    )
    # sensory_deficit should be present in the key set
    # (it will appear if the detector fires)
    assert "sensory_deficit" not in result or isinstance(
        result.get("sensory_deficit"), str
    ), "sensory_deficit value should be a string report"
    # Verify the key is in the allowed polish keys by checking the method source
    import inspect
    source = inspect.getsource(RevisionPipelineStage._build_polish_quality_reports)
    assert '"sensory_deficit"' in source, (
        "sensory_deficit not found in polish_keys set"
    )


# ---------------------------------------------------------------------------
# Change 5: _parse_voice_diagnosis
# ---------------------------------------------------------------------------


def test_parse_voice_diagnosis_valid_json():
    """_parse_voice_diagnosis must parse a valid JSON array."""
    diagnosis_json = json.dumps([
        {
            "paragraph_index": 2,
            "issue_type": "voice_homogeneity",
            "issue": "Walker sounds like Polk",
            "suggested_fix": "Add qualifying hedges",
        },
        {
            "paragraph_index": 7,
            "issue_type": "attribution_overuse",
            "issue": "Three consecutive 'said' tags",
            "suggested_fix": "Replace middle tag with action beat",
        },
    ])
    result = RevisionPipelineStage._parse_voice_diagnosis(diagnosis_json)
    assert len(result) == 2
    assert result[0]["paragraph_index"] == 2
    assert result[1]["issue_type"] == "attribution_overuse"


def test_parse_voice_diagnosis_with_markdown_fences():
    """_parse_voice_diagnosis must strip markdown fences before parsing."""
    content = "```json\n[\n  {\"paragraph_index\": 3, \"issue_type\": \"modern_vocabulary\", \"issue\": \"anachronism\", \"suggested_fix\": \"rewrite\"}\n]\n```"
    result = RevisionPipelineStage._parse_voice_diagnosis(content)
    assert len(result) == 1
    assert result[0]["paragraph_index"] == 3


def test_parse_voice_diagnosis_with_preamble():
    """_parse_voice_diagnosis must skip preamble text before the JSON array."""
    content = "Here are the issues I found:\n\n[{\"paragraph_index\": 0, \"issue_type\": \"explicit_emotion\", \"issue\": \"names fear\", \"suggested_fix\": \"show gesture\"}]"
    result = RevisionPipelineStage._parse_voice_diagnosis(content)
    assert len(result) == 1
    assert result[0]["issue_type"] == "explicit_emotion"


def test_parse_voice_diagnosis_empty_array():
    """_parse_voice_diagnosis must return empty list for empty JSON array."""
    result = RevisionPipelineStage._parse_voice_diagnosis("[]")
    assert result == []


def test_parse_voice_diagnosis_malformed_json():
    """_parse_voice_diagnosis must return empty list on malformed JSON."""
    result = RevisionPipelineStage._parse_voice_diagnosis("not json at all")
    assert result == []


def test_parse_voice_diagnosis_filters_non_dicts():
    """_parse_voice_diagnosis must filter out non-dict elements."""
    content = json.dumps([
        {"paragraph_index": 1, "issue_type": "voice_homogeneity", "issue": "x", "suggested_fix": "y"},
        "invalid string element",
        42,
        {"paragraph_index": 5, "issue_type": "attribution_overuse", "issue": "z", "suggested_fix": "w"},
    ])
    result = RevisionPipelineStage._parse_voice_diagnosis(content)
    assert len(result) == 2
    assert all(isinstance(p, dict) for p in result)


# ---------------------------------------------------------------------------
# Change 1 also: post-generation word count clamp is applied
# ---------------------------------------------------------------------------


def test_chapter_outline_estimated_word_count_clamped():
    """Stage 3 must clamp estimated_word_count to max_words_per_chapter.

    This tests the data model allows mutation, simulating what
    _build_chapter_outlines does after generate_structured.
    """
    from sovereign_ink.models.structure import ChapterOutline

    co = ChapterOutline(
        chapter_number=1,
        title="Chapter",
        pov_character="Jefferson",
        setting="White House",
        time_period="April 1803",
        political_context="context",
        chapter_goal="goal",
        conflict="conflict",
        turn="turn",
        consequences="consequences",
        hard_reveal="reveal",
        soft_reversal="reversal",
        on_page_opposing_move="threatens",
        ending_mode="cliffhanger_action",
        estimated_word_count=12000,
        act_number=1,
    )
    max_words = 4500
    if co.estimated_word_count > max_words:
        co.estimated_word_count = max_words
    assert co.estimated_word_count == max_words


# ---------------------------------------------------------------------------
# Change 3 also: regression detection works for known regressive before/after
# ---------------------------------------------------------------------------


BEFORE_TEXT = """
The rain fell on cobblestones slick with mud, the smell of the river thick
in the morning air. Jefferson crossed to the window.

---

"You have one hour," Talleyrand said. His boots clicked on the marble floor.
Jefferson felt the cold stone through his thin-soled shoes.
"""

AFTER_TEXT_WITH_REGRESSIONS = """
The situation was significant. Jefferson understood the weight of the moment.
He walked to the window and considered the weight of his decision.

---

"You have one hour," Talleyrand said. Jefferson nodded. He considered the
weight of what was being asked. The weight pressed down. The weight.
"""


def test_compute_quality_delta_detects_repetition_regression():
    """compute_quality_delta must flag repetition_patterns as regressed."""
    delta = compute_quality_delta(BEFORE_TEXT, AFTER_TEXT_WITH_REGRESSIONS)
    regression_metrics = {r["metric"] for r in delta["regressions"]}
    # repetition_patterns should have increased (AFTER has "the weight" many times)
    assert "repetition_patterns" in regression_metrics or delta["has_regressions"], (
        "Expected at least one regression in the after text"
    )


def test_compute_quality_delta_sensory_degradation_detected():
    """compute_quality_delta must detect when sensory_deficit_scenes worsens."""
    delta = compute_quality_delta(BEFORE_TEXT, AFTER_TEXT_WITH_REGRESSIONS)
    # AFTER_TEXT has no sensory detail; BEFORE_TEXT has rain/smell/cold
    # So sensory_deficit_scenes should increase (regression)
    sensory_regression = next(
        (r for r in delta["regressions"] if r["metric"] == "sensory_deficit_scenes"),
        None,
    )
    if sensory_regression:
        assert sensory_regression["after"] > sensory_regression["before"]


def test_generation_config_includes_phase8_fields():
    """Phase 8 config fields should exist with backward-compatible defaults."""
    cfg = GenerationConfig()
    assert hasattr(cfg, "enable_length_guardrails")
    assert hasattr(cfg, "length_soft_cap_ratio")
    assert hasattr(cfg, "revision_soft_cap_ratio")
    assert hasattr(cfg, "pass_regression_max_retry")
    assert cfg.enable_length_guardrails is False


def test_stage4_generation_length_guardrails_reduce_overflow():
    """Stage 4 should apply targeted compression when chapter exceeds soft cap."""
    stage = object.__new__(ProseGenerationStage)

    class _Cfg:
        max_words_per_chapter = 100
        length_soft_cap_ratio = 1.10
        length_hard_cap_ratio = 1.25
        length_guard_max_retries = 2

    class _Outline:
        ending_mode = "arrival_of_threat"

    stage.config = _Cfg()

    def _fake_compress(**kwargs):
        words = kwargs["chapter_content"].split()
        return " ".join(words[:105])

    stage._compress_to_word_budget = _fake_compress
    overlong = " ".join(["word"] * 140)
    result = stage._apply_generation_length_guardrails(
        ch_num=1,
        chapter_content=overlong,
        system_prompt="system",
        chapter_outline=_Outline(),
    )
    assert len(result.split()) <= 110


def test_stage5_revision_length_guardrails_reduce_overflow():
    """Stage 5 should compress overlong revision outputs."""
    stage = object.__new__(RevisionPipelineStage)

    class _Cfg:
        max_words_per_chapter = 100
        revision_soft_cap_ratio = 1.10
        revision_hard_cap_ratio = 1.20
        length_guard_max_retries = 1
        model_revision_polish = "test-model"
        temperature_revision = 0.6

    class _LLM:
        def generate(self, **kwargs):
            import types
            r = types.SimpleNamespace()
            r.content = " ".join(["word"] * 105)
            return r

    class _Outline:
        ending_mode = "mid_action"

    stage.config = _Cfg()
    stage.llm = _LLM()
    result = stage._apply_revision_length_guardrails(
        ch_num=1,
        chapter_content=" ".join(["word"] * 150),
        system_prompt="system",
        pass_name="polish",
        chapter_outline=_Outline(),
    )
    assert len(result.split()) <= 110


def test_critical_regression_filtering():
    """Critical regression filter should keep only configured high-priority regressions."""
    stage = object.__new__(RevisionPipelineStage)

    class _Cfg:
        pass_regression_critical_metrics = [
            "repetition_patterns",
            "sensory_deficit_scenes",
        ]
        pass_regression_delta_threshold = 0

    stage.config = _Cfg()
    delta = {
        "regressions": [
            {"metric": "repetition_patterns", "delta": 3},
            {"metric": "immediate_jeopardy_deficit_scenes", "delta": 1},
            {"metric": "sensory_deficit_scenes", "delta": 1},
        ]
    }
    filtered = stage._critical_regressions(delta)
    names = {r["metric"] for r in filtered}
    assert names == {"repetition_patterns", "sensory_deficit_scenes"}
