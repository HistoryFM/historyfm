import types
from typing import Optional
from unittest.mock import MagicMock

from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.utils.config import GenerationConfig


def _resp(content: str, model: str = "claude-sonnet-4-6"):
    return types.SimpleNamespace(
        content=content,
        model=model,
        input_tokens=10,
        output_tokens=20,
        latency_ms=10.0,
        cost_estimate=0.001,
        stop_reason="stop",
    )


def _make_stage(config: Optional[GenerationConfig] = None) -> RevisionPipelineStage:
    stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
    stage.config = config or GenerationConfig()
    stage.state_manager = MagicMock()
    stage.prompts = MagicMock()
    stage.llm = MagicMock()
    return stage


def test_parse_repetition_critic_json_malformed_returns_none():
    stage = _make_stage()
    assert stage._parse_repetition_critic_json("not json") is None


def test_extract_protected_anchors_includes_outline_and_scene_fields():
    stage = _make_stage()
    chapter_outline = types.SimpleNamespace(
        hard_reveal="The treaty clause is forged",
        on_page_opposing_move="The minister blocks the signature",
        required_end_hook="A courier arrives at midnight",
        chapter_goal="Secure ratification",
        turn="They realize the map is wrong",
        consequences="Delay risks war",
    )
    scene = types.SimpleNamespace(
        required_end_hook="A courier arrives at midnight",
        opponent_move="The minister blocks the signature",
        failure_event_if_no_action="The vote is lost",
        pov_countermove="He signs anyway",
        turn="They realize the map is wrong",
        consequences="Delay risks war",
    )
    structure = types.SimpleNamespace(
        scene_breakdowns=[types.SimpleNamespace(chapter_number=1, scenes=[scene])]
    )
    anchors = stage._extract_protected_anchors(
        ch_num=1,
        chapter_outline=chapter_outline,
        structure=structure,
    )
    assert any("forged" in a for a in anchors)
    assert any("blocks the signature" in a for a in anchors)
    assert any("vote is lost" in a for a in anchors)


def test_run_smart_repetition_pass_rejects_on_judge_uncertain():
    cfg = GenerationConfig(
        smart_repetition_retry_limit=0,
        smart_repetition_max_critic_findings=3,
        smart_repetition_max_paragraphs=3,
        smart_repetition_judge_min_confidence=0.75,
    )
    stage = _make_stage(cfg)
    stage.state_manager.project_dir = MagicMock()
    stage.state_manager.project_dir.__truediv__ = MagicMock(return_value=MagicMock())
    stage.prompts.render_revision.side_effect = ["critic", "editor", "judge"]
    stage.llm.generate.side_effect = [
        _resp(
            '[{"start_paragraph":0,"end_paragraph":0,"redundancy_type":"lexical","rationale":"repeat","confidence":0.9,"anchor_risk":"low"}]'
        ),
        _resp('{"rewritten_span":"The chamber stilled.","edit_rationale":"removed repetition"}'),
        _resp('{"decision":"uncertain","confidence":0.8,"fidelity_ok":true,"quality_delta":"same","rejection_reason":"uncertain"}'),
    ]

    chapter = (
        "The chamber grew quiet, and the chamber grew quiet again.\n\n"
        "He turned to the door.\n\n"
        "The clerk unfolded the paper."
    )
    result = stage._run_smart_repetition_pass(
        ch_num=1,
        chapter_content=chapter,
        system_prompt="system",
        chapter_outline=None,
        structure=None,
    )
    assert result == chapter


def test_run_smart_repetition_pass_accepts_and_reduces_repetition_golden_style():
    cfg = GenerationConfig(
        smart_repetition_retry_limit=0,
        smart_repetition_max_critic_findings=3,
        smart_repetition_max_paragraphs=3,
        smart_repetition_judge_min_confidence=0.75,
    )
    stage = _make_stage(cfg)
    stage.state_manager.project_dir = MagicMock()
    stage.state_manager.project_dir.__truediv__ = MagicMock(return_value=MagicMock())
    stage.prompts.render_revision.side_effect = ["critic", "editor", "judge"]
    stage.llm.generate.side_effect = [
        _resp(
            '[{"start_paragraph":0,"end_paragraph":0,"redundancy_type":"lexical","rationale":"repeated phrase","confidence":0.95,"anchor_risk":"low"}]'
        ),
        _resp('{"rewritten_span":"The chamber stilled as the vote was called.","edit_rationale":"condensed repeated wording"}'),
        _resp('{"decision":"accept","confidence":0.92,"fidelity_ok":true,"quality_delta":"better","rejection_reason":""}'),
    ]

    chapter = (
        "The chamber grew quiet, and the chamber grew quiet again before the vote.\n\n"
        "He turned to the door.\n\n"
        "The clerk unfolded the paper."
    )
    result = stage._run_smart_repetition_pass(
        ch_num=1,
        chapter_content=chapter,
        system_prompt="system",
        chapter_outline=None,
        structure=None,
    )
    assert result != chapter
    assert result.count("chamber grew quiet") < chapter.count("chamber grew quiet")


def test_run_smart_repetition_pass_rejects_non_effective_accept():
    cfg = GenerationConfig(
        smart_repetition_retry_limit=0,
        smart_repetition_max_critic_findings=3,
        smart_repetition_max_paragraphs=3,
        smart_repetition_judge_min_confidence=0.75,
        smart_repetition_require_effective_reduction=True,
    )
    stage = _make_stage(cfg)
    stage.state_manager.project_dir = MagicMock()
    stage.state_manager.project_dir.__truediv__ = MagicMock(return_value=MagicMock())
    stage.prompts.render_revision.side_effect = ["critic", "editor", "judge"]
    stage.llm.generate.side_effect = [
        _resp(
            '[{"start_paragraph":0,"end_paragraph":0,"redundancy_type":"lexical","rationale":"repeated phrase","confidence":0.95,"anchor_risk":"low"}]'
        ),
        _resp('{"rewritten_span":"The chamber grew quiet, the chamber grew quiet, and the chamber grew quiet before the vote.","edit_rationale":"minor punctuation tweak"}'),
        _resp('{"decision":"accept","confidence":0.92,"fidelity_ok":true,"quality_delta":"same","rejection_reason":""}'),
    ]

    chapter = (
        "The chamber grew quiet, the chamber grew quiet, and the chamber grew quiet before the vote.\n\n"
        "He turned to the door.\n\n"
        "The clerk unfolded the paper."
    )
    result = stage._run_smart_repetition_pass(
        ch_num=1,
        chapter_content=chapter,
        system_prompt="system",
        chapter_outline=None,
        structure=None,
    )
    artifact = getattr(stage, "_last_smart_repetition_artifact", {})
    assert result == chapter
    assert artifact.get("accepted_edits_count", 0) == 0
    assert artifact.get("rejected_edits_count", 0) >= 1
