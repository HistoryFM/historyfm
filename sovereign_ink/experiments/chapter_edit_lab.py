"""Chapter-copy editing lab for fast smart-edit iteration.

Runs smart repetition editing on copied chapter files without invoking the full
pipeline convergence loop. Produces before/after metrics and a hard
non-regression acceptance gate for repetition.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sovereign_ink.llm import LLMClient
from sovereign_ink.models.structure import NovelStructure
from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage
from sovereign_ink.prompts import PromptRenderer
from sovereign_ink.utils.config import load_config
from sovereign_ink.utils.text_quality import (
    build_quality_snapshot,
    detect_duplicate_passages,
)


CHAPTER_NAME_RE = re.compile(r"chapter_(\d+)\.md$")


@dataclass
class ChapterEditLabOptions:
    project_dir: Path
    chapter_selector: str | None = None
    source_version: str = "v3_polish"
    dry_run: bool = False
    max_paragraphs: int | None = None
    max_findings: int | None = None
    retry_limit: int | None = None
    judge_min_confidence: float | None = None
    tiebreak_mode: str | None = None
    repetition_non_regression_required: bool = True
    effectiveness_gate_mode: str = "none"  # none|strict|batch
    batch_min_improved_chapters: int = 2
    batch_require_aggregate_decrease: bool = True
    critical_max_increase: dict[str, int] | None = None


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _parse_chapter_selector(selector: str | None, available: list[int]) -> list[int]:
    if not selector:
        return sorted(available)
    selected: set[int] = set()
    for raw in selector.split(","):
        part = raw.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a)
            end = int(b)
            lo = min(start, end)
            hi = max(start, end)
            selected.update(range(lo, hi + 1))
        else:
            selected.add(int(part))
    return [n for n in sorted(selected) if n in set(available)]


def _chapter_number_from_path(path: Path) -> int:
    m = CHAPTER_NAME_RE.search(path.name)
    if not m:
        raise ValueError(f"Invalid chapter filename: {path.name}")
    return int(m.group(1))


def _chapter_metrics(chapter_text: str) -> dict:
    snapshot = build_quality_snapshot(chapter_text)
    counts = snapshot.get("counts", {})
    duplicates = detect_duplicate_passages(chapter_text)
    repetition_raw = snapshot.get("raw", {}).get("repetition", []) or []
    repetition_burden = sum(max(int(item.get("count", 0) or 0) - 2, 0) for item in repetition_raw)
    return {
        "word_count": int(snapshot.get("word_count", 0)),
        "counts": counts,
        "duplicate_passage_pairs": len(duplicates),
        "repetition_burden": repetition_burden,
        "repetition_raw": repetition_raw[:25],
    }


def _pattern_key(pattern: str) -> str:
    value = str(pattern or "").strip().lower()
    if " — e.g. " in value:
        return value.split(" — e.g. ", 1)[0].strip()
    return value


def _pattern_delta(before: list[dict], after: list[dict]) -> list[dict]:
    before_map: dict[str, int] = {}
    after_map: dict[str, int] = {}
    for item in before:
        key = _pattern_key(item.get("pattern", ""))
        if key:
            before_map[key] = int(item.get("count", 0) or 0)
    for item in after:
        key = _pattern_key(item.get("pattern", ""))
        if key:
            after_map[key] = int(item.get("count", 0) or 0)
    keys = sorted(set(before_map) | set(after_map))
    deltas: list[dict] = []
    for key in keys:
        b = before_map.get(key, 0)
        a = after_map.get(key, 0)
        if a == b:
            continue
        deltas.append(
            {
                "pattern_key": key,
                "baseline_count": b,
                "final_count": a,
                "delta": a - b,
            }
        )
    deltas.sort(key=lambda x: abs(int(x["delta"])), reverse=True)
    return deltas[:20]


def _load_structure(project_dir: Path) -> NovelStructure | None:
    structure_path = project_dir / "structure" / "novel_structure.json"
    if not structure_path.exists():
        return None
    data = json.loads(structure_path.read_text(encoding="utf-8"))
    return NovelStructure(**data)


def _find_outline(structure: NovelStructure | None, ch_num: int):
    if not structure:
        return None
    for co in structure.chapter_outlines:
        if co.chapter_number == ch_num:
            return co
    return None


def _clone_and_select_inputs(
    source_dir: Path,
    input_dir: Path,
    baseline_dir: Path,
    edited_dir: Path,
    selected_chapters: list[int],
) -> list[Path]:
    copied: list[Path] = []
    for ch_num in selected_chapters:
        name = f"chapter_{ch_num:02d}.md"
        src = source_dir / name
        if not src.exists():
            continue
        input_target = input_dir / name
        base_target = baseline_dir / name
        edit_target = edited_dir / name
        input_target.parent.mkdir(parents=True, exist_ok=True)
        baseline_dir.mkdir(parents=True, exist_ok=True)
        edited_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, input_target)
        shutil.copy2(src, base_target)
        shutil.copy2(src, edit_target)
        copied.append(edit_target)
    return copied


def _build_revision_stage_for_lab(project_dir: Path):
    config = load_config(project_dir)
    llm = LLMClient(config)
    prompts = PromptRenderer()
    state_manager = SimpleNamespace(
        project_dir=project_dir,
        _write_json=lambda path, payload: _write_json(Path(path), payload),
    )
    stage = RevisionPipelineStage.__new__(RevisionPipelineStage)
    stage.config = config
    stage.llm = llm
    stage.prompts = prompts
    stage.state_manager = state_manager
    return stage


def run_chapter_edit_lab(options: ChapterEditLabOptions) -> dict:
    project_dir = options.project_dir.resolve()
    source_dir = project_dir / "drafts" / options.source_version
    if not source_dir.exists():
        raise FileNotFoundError(f"Source version directory not found: {source_dir}")

    chapter_paths = sorted(source_dir.glob("chapter_*.md"))
    available = [_chapter_number_from_path(p) for p in chapter_paths]
    selected = _parse_chapter_selector(options.chapter_selector, available)
    if not selected:
        raise ValueError("No chapters matched selector.")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = project_dir / "state" / "edit_lab" / run_id
    input_dir = run_root / "input"
    baseline_dir = run_root / "baseline"
    edited_dir = run_root / "edited"
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    copied_paths = _clone_and_select_inputs(
        source_dir=source_dir,
        input_dir=input_dir,
        baseline_dir=baseline_dir,
        edited_dir=edited_dir,
        selected_chapters=selected,
    )

    metadata = {
        "run_id": run_id,
        "project_dir": str(project_dir),
        "source_version": options.source_version,
        "selected_chapters": selected,
        "created_at": datetime.now().isoformat(),
        "dry_run": bool(options.dry_run),
        "effectiveness_gate_mode": options.effectiveness_gate_mode,
        "batch_min_improved_chapters": int(options.batch_min_improved_chapters),
        "batch_require_aggregate_decrease": bool(options.batch_require_aggregate_decrease),
    }
    _write_json(reports_dir / "metadata.json", metadata)

    structure = _load_structure(project_dir)
    stage = None if options.dry_run else _build_revision_stage_for_lab(project_dir)
    prompt_renderer = PromptRenderer()
    if stage:
        stage.config.enable_smart_repetition_pass = True
        if options.max_paragraphs is not None:
            stage.config.smart_repetition_max_paragraphs = options.max_paragraphs
        if options.max_findings is not None:
            stage.config.smart_repetition_max_critic_findings = options.max_findings
        if options.retry_limit is not None:
            stage.config.smart_repetition_retry_limit = options.retry_limit
        if options.judge_min_confidence is not None:
            stage.config.smart_repetition_judge_min_confidence = options.judge_min_confidence
        if options.tiebreak_mode is not None:
            stage.config.smart_repetition_tiebreak_mode = options.tiebreak_mode

    critical_limits = options.critical_max_increase or {
        "sensory_deficit_scenes": 0,
        "immediate_jeopardy_deficit_scenes": 0,
        "ending_propulsion_deficit_flag": 0,
    }

    chapter_results: list[dict] = []
    baseline_metrics: dict[str, dict] = {}
    edited_metrics: dict[str, dict] = {}
    final_metrics: dict[str, dict] = {}

    for edited_path in copied_paths:
        ch_num = _chapter_number_from_path(edited_path)
        baseline_path = baseline_dir / edited_path.name
        baseline_text = baseline_path.read_text(encoding="utf-8")
        before = _chapter_metrics(baseline_text)
        baseline_metrics[str(ch_num)] = before

        diagnostics = {}
        candidate_text = baseline_text
        if stage:
            renderer = getattr(stage, "prompts", prompt_renderer)
            system_prompt = renderer.render_system_prompt(era_tone_guide=None)
            candidate_text, diagnostics = stage.run_smart_repetition_on_text(
                ch_num=ch_num,
                chapter_content=baseline_text,
                system_prompt=system_prompt,
                chapter_outline=_find_outline(structure, ch_num),
                structure=structure,
                persist_artifact=False,
            )
            edited_path.write_text(candidate_text, encoding="utf-8")

        after_candidate = _chapter_metrics(candidate_text)
        edited_metrics[str(ch_num)] = after_candidate

        reasons: list[str] = []
        rep_before = int(before["counts"].get("repetition_patterns", 0))
        rep_after = int(after_candidate["counts"].get("repetition_patterns", 0))
        if options.repetition_non_regression_required and rep_after > rep_before:
            reasons.append(
                f"repetition_patterns worsened ({rep_before} -> {rep_after})"
            )
        if str(options.effectiveness_gate_mode).strip().lower() == "strict" and rep_after >= rep_before:
            reasons.append(
                f"strict effectiveness gate requires reduction ({rep_before} -> {rep_after})"
            )

        for metric, max_inc in critical_limits.items():
            b = int(before["counts"].get(metric, 0))
            a = int(after_candidate["counts"].get(metric, 0))
            if a - b > int(max_inc):
                reasons.append(
                    f"{metric} exceeded threshold ({b} -> {a}, max_increase={max_inc})"
                )

        if reasons:
            disposition = "rejected_reverted"
            final_text = baseline_text
            edited_path.write_text(final_text, encoding="utf-8")
        else:
            disposition = "accepted"
            final_text = candidate_text

        final = _chapter_metrics(final_text)
        final_metrics[str(ch_num)] = final

        chapter_results.append(
            {
                "chapter_number": ch_num,
                "file": edited_path.name,
                "disposition": disposition,
                "reasons": reasons,
                "baseline": before,
                "edited_candidate": after_candidate,
                "final": final,
                "smart_pass": diagnostics,
                "repetition_analysis": {
                    "baseline_burden": int(before.get("repetition_burden", 0)),
                    "candidate_burden": int(after_candidate.get("repetition_burden", 0)),
                    "final_burden": int(final.get("repetition_burden", 0)),
                    "pattern_deltas": _pattern_delta(
                        before.get("repetition_raw", []),
                        final.get("repetition_raw", []),
                    ),
                },
            }
        )

    _write_json(reports_dir / "baseline_metrics.json", baseline_metrics)
    _write_json(reports_dir / "edited_metrics.json", edited_metrics)
    _write_json(reports_dir / "final_metrics.json", final_metrics)
    _write_json(reports_dir / "edit_decisions.json", chapter_results)

    repetition_deltas = [
        int(r["final"]["counts"].get("repetition_patterns", 0))
        - int(r["baseline"]["counts"].get("repetition_patterns", 0))
        for r in chapter_results
    ]
    aggregate_repetition_delta = int(sum(repetition_deltas))
    improved_chapters = int(sum(1 for d in repetition_deltas if d < 0))
    worsened_chapters = int(sum(1 for d in repetition_deltas if d > 0))
    any_regressed = any(d > 0 for d in repetition_deltas)
    any_improved = any(d < 0 for d in repetition_deltas)
    gate_mode = str(options.effectiveness_gate_mode).strip().lower()
    effectiveness_gate_passed = True
    if gate_mode == "batch":
        effectiveness_gate_passed = improved_chapters >= int(options.batch_min_improved_chapters)
        if options.batch_require_aggregate_decrease:
            effectiveness_gate_passed = effectiveness_gate_passed and aggregate_repetition_delta < 0
    if any_regressed:
        recommendation = "regressed"
    elif not effectiveness_gate_passed:
        recommendation = "mixed"
    elif any_improved:
        recommendation = "improved"
    else:
        recommendation = "mixed"

    summary = {
        "run_id": run_id,
        "selected_chapters": selected,
        "chapter_count": len(chapter_results),
        "recommendation": recommendation,
        "repetition_non_regression_enforced": bool(options.repetition_non_regression_required),
        "aggregate_repetition_delta": aggregate_repetition_delta,
        "improved_chapters": improved_chapters,
        "worsened_chapters": worsened_chapters,
        "effectiveness_gate": {
            "mode": gate_mode,
            "passed": bool(effectiveness_gate_passed),
            "batch_min_improved_chapters": int(options.batch_min_improved_chapters),
            "batch_require_aggregate_decrease": bool(options.batch_require_aggregate_decrease),
        },
        "results": chapter_results,
    }
    _write_json(reports_dir / "summary.json", summary)

    md_lines = [
        f"# Chapter Edit Lab Summary ({run_id})",
        "",
        f"- Source version: `{options.source_version}`",
        f"- Selected chapters: `{', '.join(str(c) for c in selected)}`",
        f"- Recommendation: `{recommendation}`",
        f"- Aggregate repetition delta: `{aggregate_repetition_delta}`",
        f"- Improved chapters: `{improved_chapters}`",
        f"- Worsened chapters: `{worsened_chapters}`",
        f"- Effectiveness gate: `{gate_mode}` (passed=`{effectiveness_gate_passed}`)",
        "",
        "## Chapter Results",
        "",
    ]
    for row in chapter_results:
        ch = row["chapter_number"]
        base_rep = row["baseline"]["counts"].get("repetition_patterns", 0)
        final_rep = row["final"]["counts"].get("repetition_patterns", 0)
        md_lines.append(
            f"- Chapter {ch:02d}: `{row['disposition']}` "
            f"(repetition_patterns {base_rep} -> {final_rep})"
        )
        if row["reasons"]:
            md_lines.append(f"  - Reasons: {', '.join(row['reasons'])}")
    (reports_dir / "summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    return {
        "run_root": str(run_root),
        "reports_dir": str(reports_dir),
        "summary": summary,
    }

