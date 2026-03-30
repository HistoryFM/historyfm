from pathlib import Path
from types import SimpleNamespace

from sovereign_ink.experiments import chapter_edit_lab as lab


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    _write(
        project / "drafts" / "v3_polish" / "chapter_01.md",
        "The chamber grew quiet, and the chamber grew quiet again.\n\nHe looked up.",
    )
    return project


def test_edit_lab_reverts_when_repetition_worsens(tmp_path, monkeypatch):
    project = _make_project(tmp_path)

    class FakeStage:
        def __init__(self):
            self.config = SimpleNamespace()

        def run_smart_repetition_on_text(self, **kwargs):
            return (
                "The chamber grew quiet, and the chamber grew quiet again. "
                "The chamber grew quiet once more.\n\nHe looked up.",
                {"status": "completed"},
            )

    monkeypatch.setattr(lab, "_build_revision_stage_for_lab", lambda _: FakeStage())

    result = lab.run_chapter_edit_lab(
        lab.ChapterEditLabOptions(project_dir=project, source_version="v3_polish")
    )
    summary = result["summary"]
    row = summary["results"][0]
    assert row["disposition"] == "rejected_reverted"
    assert "repetition_patterns worsened" in " | ".join(row["reasons"])


def test_edit_lab_accepts_when_repetition_improves(tmp_path, monkeypatch):
    project = _make_project(tmp_path)

    class FakeStage:
        def __init__(self):
            self.config = SimpleNamespace()

        def run_smart_repetition_on_text(self, **kwargs):
            return ("The chamber stilled before the vote.\n\nHe looked up.", {"status": "completed"})

    monkeypatch.setattr(lab, "_build_revision_stage_for_lab", lambda _: FakeStage())

    result = lab.run_chapter_edit_lab(
        lab.ChapterEditLabOptions(project_dir=project, source_version="v3_polish")
    )
    summary = result["summary"]
    row = summary["results"][0]
    assert row["disposition"] == "accepted"
    assert row["final"]["counts"].get("repetition_patterns", 0) <= row["baseline"]["counts"].get("repetition_patterns", 0)


def test_edit_lab_reports_always_emitted(tmp_path, monkeypatch):
    project = _make_project(tmp_path)

    class FakeStage:
        def __init__(self):
            self.config = SimpleNamespace()

        def run_smart_repetition_on_text(self, **kwargs):
            # Mimic malformed-output fallback path that keeps source text.
            return (kwargs["chapter_content"], {"status": "no_findings_or_parse_failure"})

    monkeypatch.setattr(lab, "_build_revision_stage_for_lab", lambda _: FakeStage())

    result = lab.run_chapter_edit_lab(
        lab.ChapterEditLabOptions(project_dir=project, source_version="v3_polish")
    )
    reports = Path(result["reports_dir"])
    assert (reports / "summary.json").exists()
    assert (reports / "summary.md").exists()
    assert (reports / "edit_decisions.json").exists()
    assert (reports / "baseline_metrics.json").exists()
    assert (reports / "edited_metrics.json").exists()
    assert (reports / "final_metrics.json").exists()


def test_edit_lab_strict_effectiveness_gate_reverts_without_improvement(tmp_path, monkeypatch):
    project = _make_project(tmp_path)

    class FakeStage:
        def __init__(self):
            self.config = SimpleNamespace()

        def run_smart_repetition_on_text(self, **kwargs):
            # No change in repetition signal.
            return (kwargs["chapter_content"], {"status": "completed", "accepted_edits_count": 1})

    monkeypatch.setattr(lab, "_build_revision_stage_for_lab", lambda _: FakeStage())

    result = lab.run_chapter_edit_lab(
        lab.ChapterEditLabOptions(
            project_dir=project,
            source_version="v3_polish",
            effectiveness_gate_mode="strict",
        )
    )
    row = result["summary"]["results"][0]
    assert row["disposition"] == "rejected_reverted"
    assert any("strict effectiveness gate requires reduction" in r for r in row["reasons"])


def test_edit_lab_batch_effectiveness_gate_marks_summary_failure(tmp_path, monkeypatch):
    project = _make_project(tmp_path)

    class FakeStage:
        def __init__(self):
            self.config = SimpleNamespace()

        def run_smart_repetition_on_text(self, **kwargs):
            # Keep chapter unchanged to force zero improvement.
            return (kwargs["chapter_content"], {"status": "completed", "accepted_edits_count": 0})

    monkeypatch.setattr(lab, "_build_revision_stage_for_lab", lambda _: FakeStage())

    result = lab.run_chapter_edit_lab(
        lab.ChapterEditLabOptions(
            project_dir=project,
            source_version="v3_polish",
            effectiveness_gate_mode="batch",
            batch_min_improved_chapters=1,
            batch_require_aggregate_decrease=True,
        )
    )
    summary = result["summary"]
    assert summary["effectiveness_gate"]["mode"] == "batch"
    assert summary["effectiveness_gate"]["passed"] is False

