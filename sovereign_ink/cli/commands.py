"""Sovereign Ink CLI — command-line interface for novel generation."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import click
import sentry_sdk
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ---------------------------------------------------------------------------
# Self-healing escalation levels for chapter convergence.
# Each level is cumulative — higher levels include all prior overrides.
# The convergence loop tries level 0 first, escalates on repeated failure.
# ---------------------------------------------------------------------------
_ESCALATION_LEVELS = [
    # Level 0: no changes — use project config as-is
    {},
    # Level 1: loosen scene tolerance, disable pressure contracts
    {
        "enable_pressure_contracts": False,
        "stage4_scene_count_tolerance": 1,
    },
    # Level 2: disable semantic/adversarial validators, increase repair budget
    {
        "enable_pressure_contracts": False,
        "stage4_scene_count_tolerance": 1,
        "semantic_validator_enabled": False,
        "adversarial_verifier_enabled": False,
        "stage4_max_total_repair_attempts": 20,
    },
    # Level 3: disable quality gates entirely, max retry budget
    {
        "enable_pressure_contracts": False,
        "stage4_scene_count_tolerance": 1,
        "semantic_validator_enabled": False,
        "adversarial_verifier_enabled": False,
        "stage4_max_total_repair_attempts": 20,
        "enable_quality_gates": False,
        "next_max_convergence_attempts": 20,
        "next_max_identical_failure_streak": 6,
    },
]

_ESCALATION_CONFIG_FIELDS = {
    "enable_pressure_contracts", "stage4_scene_count_tolerance",
    "semantic_validator_enabled", "adversarial_verifier_enabled",
    "stage4_max_total_repair_attempts", "enable_quality_gates",
    "next_max_convergence_attempts", "next_max_identical_failure_streak",
}


@click.group()
@click.version_option(version="0.1.0", prog_name="sovereign-ink")
def cli():
    """Sovereign Ink — Autonomous Historical Novel Generation System"""
    pass


@cli.command()
@click.option("--project-dir", "-p", type=click.Path(), default=None,
              help="Project directory name (created inside current working directory)")
@click.option("--title", "-t", type=str, default=None, help="Working title")
@click.option("--era-start", type=int, default=None, help="Era start year (1700-1900)")
@click.option("--era-end", type=int, default=None, help="Era end year (1700-1900)")
@click.option("--region", type=str, default=None, help="Region/country")
@click.option("--event", type=str, default=None, help="Central historical event")
@click.option("--tone", type=click.Choice(["dramatic", "highly_dramatic", "restrained_dramatic"]), default=None)
@click.option("--pov-count", type=int, default=None, help="Number of POV characters (1-4)")
@click.option("--protagonist", type=click.Choice(["historical_figure", "fictional_character", "both"]), default=None)
@click.option("--length", type=click.Choice(["novella_50k", "novel_120k"]), default=None)
@click.option("--interactive/--no-interactive", default=True, help="Use interactive setup wizard")
def new(project_dir, title, era_start, era_end, region, event, tone, pov_count, protagonist, length, interactive):
    """Create a new novel project with interactive setup."""
    from sovereign_ink.utils.config import load_config
    from sovereign_ink.utils.logging import setup_logging

    console.print(Panel(
        "[bold cyan]Sovereign Ink[/bold cyan] — Novel Generation System\n"
        "Creating a new project...",
        expand=False
    ))

    # Determine project directory
    if project_dir is None:
        project_name = title.replace(" ", "_").lower() if title else "novel_project"
        project_dir = Path.cwd() / project_name
    else:
        project_dir = Path(project_dir)

    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    setup_logging(project_dir / "logs")

    # If all required fields are provided via CLI, skip interactive mode
    if not interactive or all([era_start, era_end, region, event, tone, protagonist, length]):
        from sovereign_ink.models import NovelSpec

        spec = NovelSpec(
            title=title,
            era_start=era_start or 1789,
            era_end=era_end or 1799,
            region=region or "France",
            central_event=event or "The French Revolution",
            tone_intensity=tone or "highly_dramatic",
            pov_count=pov_count or 2,
            protagonist_type=protagonist or "both",
            thematic_focus=["loyalty vs ambition", "idealism vs pragmatism"],
            desired_length=length or "novella_50k",
            additional_notes=None,
        )
    else:
        spec = None  # Will be gathered interactively

    # Create the project and run only the setup stage
    from sovereign_ink.pipeline.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator(project_dir, novel_spec=spec)
        # Only run the interactive_setup stage (not the full pipeline)
        orchestrator.run(start_from="interactive_setup", stop_after="interactive_setup")

        # Show what was created
        saved_spec = orchestrator.state_manager.load_novel_spec()
        if saved_spec:
            _display_spec(saved_spec)

        console.print(f"\n[green]Project created at: {project_dir}[/green]")
        console.print(f"Run [bold]sovereign-ink run -p {project_dir}[/bold] to generate your novel.")

        orchestrator.cleanup()
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option("--project-dir", "-p", type=click.Path(exists=True), required=True,
              help="Path to the project directory")
@click.option("--from-stage", type=click.Choice([
    "interactive_setup", "world_building", "structural_planning",
    "prose_generation", "revision_pipeline", "assembly_export"
]), default=None, help="Start from a specific stage (for re-running)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def run(project_dir, from_stage, verbose):
    """Run or resume the novel generation pipeline."""
    from sovereign_ink.utils.logging import setup_logging

    project_dir = Path(project_dir).resolve()
    setup_logging(project_dir / "logs", verbose=verbose)

    console.print(Panel(
        "[bold cyan]Sovereign Ink[/bold cyan] — Running Pipeline",
        expand=False
    ))

    from sovereign_ink.pipeline.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator(project_dir)

        # Display current status
        status = orchestrator.get_status()
        console.print(f"Project: [bold]{status['project_name']}[/bold]")
        console.print(f"Current stage: [cyan]{status['current_stage']}[/cyan]")
        console.print()

        orchestrator.run(start_from=from_stage)

        # Show final stats
        console.print("\n[bold green]Pipeline complete![/bold green]")
        final_status = orchestrator.get_status()
        console.print(f"Total tokens: {final_status['total_tokens']:,}")
        console.print(f"Total cost: {final_status['total_cost']}")

        orchestrator.cleanup()
    except KeyboardInterrupt:
        console.print("\n[yellow]Pipeline paused. Resume with the same command.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        logging.getLogger(__name__).exception("Pipeline failed")
        sys.exit(1)


@cli.command()
@click.option("--project-dir", "-p", type=click.Path(exists=True), required=True,
              help="Path to the project directory")
@click.option("--quality", is_flag=True, help="Show aggregate quality metrics if available")
def status(project_dir, quality):
    """Show the current pipeline status."""
    project_dir = Path(project_dir).resolve()

    try:
        # Read state files directly without acquiring a lock
        state_path = project_dir / "state" / "pipeline_state.json"
        if not state_path.exists():
            console.print("[yellow]No pipeline state found. Run 'sovereign-ink new' first.[/yellow]")
            return

        import json
        state_data = json.loads(state_path.read_text())

        console.print(Panel(
            f"[bold cyan]Project: {state_data.get('project_name', 'Unknown')}[/bold cyan]",
            expand=False
        ))

        table = Table(title="Pipeline Status")
        table.add_column("Stage", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Sub-step")
        table.add_column("Started")
        table.add_column("Completed")

        for stage_name, progress in state_data.get("stages", {}).items():
            status_val = progress.get("status", "pending")
            style = {
                "pending": "dim",
                "in_progress": "yellow",
                "completed": "green",
                "failed": "red",
            }.get(status_val, "white")

            table.add_row(
                stage_name.replace("_", " ").title(),
                f"[{style}]{status_val}[/{style}]",
                progress.get("sub_step", "—") or "—",
                str(progress.get("started_at", "—") or "—")[:19],
                str(progress.get("completed_at", "—") or "—")[:19],
            )

        console.print(table)
        console.print(f"\nTokens used: {state_data.get('total_tokens_used', 0):,}")
        console.print(f"Estimated cost: ${state_data.get('total_cost_estimate', 0):.4f}")

        # Check for manuscript
        manuscript_path = project_dir / "output" / "manuscript.md"
        if manuscript_path.exists():
            word_count = len(manuscript_path.read_text().split())
            console.print(f"\n[green]Manuscript available: {manuscript_path}[/green]")
            console.print(f"Word count: {word_count:,}")

        if quality:
            quality_path = project_dir / "state" / "quality_reports" / "aggregate.json"
            if quality_path.exists():
                quality_data = json.loads(quality_path.read_text())
                console.print("\n[bold cyan]Quality Metrics (Aggregate)[/bold cyan]")

                chapters = quality_data.get("chapters_included", [])
                console.print(f"Chapters included: {', '.join(str(c) for c in chapters) if chapters else '—'}")

                norm = quality_data.get("normalized_per_10k_words", {})
                before = norm.get("v0_raw", {})
                after = norm.get("v3_polish", {})

                q_table = Table(title="Normalized Metrics (per 10k words)")
                q_table.add_column("Metric", style="cyan")
                q_table.add_column("v0_raw", justify="right")
                q_table.add_column("v3_polish", justify="right")

                for key in [
                    "immediate_jeopardy_deficit_scenes_per_10k_words",
                    "exposition_drag_runs_per_10k_words",
                    "repetition_patterns_per_10k_words",
                ]:
                    q_table.add_row(
                        key,
                        str(before.get(key, "—")),
                        str(after.get(key, "—")),
                    )
                console.print(q_table)
            else:
                console.print(
                    "\n[yellow]No quality aggregate found yet. "
                    "Generate/polish chapters first.[/yellow]"
                )

    except Exception as e:
        console.print(f"[red]Error reading status: {e}[/red]")


@cli.command("edit-lab")
@click.option("--project-dir", "-p", type=click.Path(exists=True), required=True,
              help="Path to the project directory")
@click.option("--chapters", type=str, default=None,
              help="Chapter selection, e.g. '6-12' or '1,2,7'")
@click.option("--source-version", type=str, default="v3_polish",
              help="Draft source version (default: v3_polish)")
@click.option("--dry-run", is_flag=True,
              help="Only copy chapters and compute metrics; skip editing calls")
@click.option("--max-paragraphs", type=int, default=None,
              help="Override smart repetition max edited paragraphs")
@click.option("--max-findings", type=int, default=None,
              help="Override smart repetition max critic findings")
@click.option("--retry-limit", type=int, default=None,
              help="Override smart repetition parse/retry limit")
@click.option("--judge-min-confidence", type=float, default=None,
              help="Override smart repetition judge confidence threshold")
@click.option("--effectiveness-gate-mode", type=click.Choice(["none", "strict", "batch"]), default="none",
              help="Extra effectiveness gating mode for repetition outcomes")
@click.option("--batch-min-improved-chapters", type=int, default=2,
              help="Batch gate minimum improved chapters (batch mode only)")
@click.option("--batch-require-aggregate-decrease/--no-batch-require-aggregate-decrease", default=True,
              help="Require aggregate repetition decrease in batch mode")
def edit_lab(
    project_dir,
    chapters,
    source_version,
    dry_run,
    max_paragraphs,
    max_findings,
    retry_limit,
    judge_min_confidence,
    effectiveness_gate_mode,
    batch_min_improved_chapters,
    batch_require_aggregate_decrease,
):
    """Run chapter-copy smart-edit experiment without full pipeline loops."""
    from sovereign_ink.experiments.chapter_edit_lab import (
        ChapterEditLabOptions,
        run_chapter_edit_lab,
    )
    from sovereign_ink.utils.logging import setup_logging

    project_path = Path(project_dir).resolve()
    setup_logging(project_path / "logs")

    options = ChapterEditLabOptions(
        project_dir=project_path,
        chapter_selector=chapters,
        source_version=source_version,
        dry_run=dry_run,
        max_paragraphs=max_paragraphs,
        max_findings=max_findings,
        retry_limit=retry_limit,
        judge_min_confidence=judge_min_confidence,
        effectiveness_gate_mode=effectiveness_gate_mode,
        batch_min_improved_chapters=batch_min_improved_chapters,
        batch_require_aggregate_decrease=batch_require_aggregate_decrease,
    )

    result = run_chapter_edit_lab(options)
    summary = result["summary"]
    console.print(Panel("[bold cyan]Sovereign Ink[/bold cyan] — Chapter Edit Lab", expand=False))
    console.print(f"Run ID: [bold]{summary['run_id']}[/bold]")
    console.print(f"Recommendation: [bold]{summary['recommendation']}[/bold]")
    console.print(f"Reports: [dim]{result['reports_dir']}[/dim]")
    console.print("")
    for row in summary["results"]:
        before = row["baseline"]["counts"].get("repetition_patterns", 0)
        after = row["final"]["counts"].get("repetition_patterns", 0)
        console.print(
            f"  Chapter {row['chapter_number']:02d}: "
            f"{row['disposition']} (repetition_patterns {before} -> {after})"
        )


@cli.command("next")
@click.option("--project-dir", "-p", type=click.Path(), required=True,
              help="Path to the project directory")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def next_chapter(project_dir, verbose):
    """Generate and fully polish the next chapter.

    Each invocation writes one chapter through the complete pipeline:
    draft -> structural revision -> voice/dialogue revision -> polish.
    Run again to produce the next chapter.  Works across multiple
    novels — just point -p at different project directories.
    """
    from sovereign_ink.utils.logging import setup_logging

    project_dir = Path(project_dir).resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(project_dir / "logs", verbose=verbose)

    console.print(Panel(
        "[bold cyan]Sovereign Ink[/bold cyan] — Next Chapter",
        expand=False
    ))

    from sovereign_ink.pipeline.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator(project_dir)
        incoming_trace = os.environ.get("SENTRY_TRACE")
        incoming_baggage = os.environ.get("SENTRY_BAGGAGE")
        if incoming_trace:
            sentry_sdk.continue_trace(
                {"sentry-trace": incoming_trace, "baggage": incoming_baggage or ""},
            )
        _txn = sentry_sdk.start_transaction(op="pipeline", name="sovereign-ink.next_chapter")
        _txn.set_tag("project", project_dir.name)
        _txn.__enter__()

        # 1. Ensure stages 1-3 are complete
        _ensure_prerequisites(orchestrator)

        # 2. Determine next unfinished chapter
        structure = orchestrator.state_manager.load_novel_structure()
        if structure is None:
            console.print("[red]No novel structure found. Run 'sovereign-ink new' first.[/red]")
            sys.exit(1)

        total_chapters = len(structure.chapter_outlines)
        ch_num = orchestrator.state_manager.get_next_unaccepted_chapter(total_chapters)

        if ch_num is None:
            console.print(
                f"\n[bold green]All {total_chapters} chapters are fully polished![/bold green]"
            )
            console.print(
                f"Run [bold]sovereign-ink export -p {project_dir}[/bold] to assemble the manuscript."
            )
            _txn.__exit__(None, None, None)
            sentry_sdk.flush(timeout=10)
            orchestrator.cleanup()
            return

        _txn.set_tag("chapter_number", str(ch_num))
        sentry_sdk.logger.info("Chapter {chapter} generation started", chapter=ch_num, project=project_dir.name, stage="next_chapter")
        console.print(
            f"\n[cyan]Generating chapter {ch_num}/{total_chapters}...[/cyan]\n"
        )

        # 3. Generate + revise until chapter reaches accepted state
        from sovereign_ink.pipeline.errors import ContractEnforcementError
        from sovereign_ink.pipeline.stages.stage4_prose_generation import ProseGenerationStage
        from sovereign_ink.pipeline.stages.stage5_revision import RevisionPipelineStage

        gen_stage = ProseGenerationStage(
            state_manager=orchestrator.state_manager,
            llm_client=orchestrator.llm,
            prompt_renderer=orchestrator.prompts,
            config=orchestrator.config,
            pipeline_state=orchestrator.pipeline_state,
        )
        rev_stage = RevisionPipelineStage(
            state_manager=orchestrator.state_manager,
            llm_client=orchestrator.llm,
            prompt_renderer=orchestrator.prompts,
            config=orchestrator.config,
            pipeline_state=orchestrator.pipeline_state,
        )

        # Pre-flight: ensure scene breakdown exists for this chapter
        _ensure_scene_breakdowns(orchestrator, ch_num)

        # Snapshot original config so we can restore after escalation
        config_snapshot = _save_config_snapshot(orchestrator.config)
        converged = False

        try:
            for escalation_level in range(len(_ESCALATION_LEVELS)):
                # Reset config to original, then apply this escalation level
                _restore_config_snapshot(orchestrator.config, config_snapshot)
                _apply_escalation_level(orchestrator.config, escalation_level)

                # Re-read limits from (possibly mutated) config
                max_attempts = max(
                    int(getattr(orchestrator.config, "next_max_convergence_attempts", 12)), 1
                )
                max_identical_streak = max(
                    int(getattr(orchestrator.config, "next_max_identical_failure_streak", 3)), 1
                )
                attempts = 0
                last_failure_signature = ""
                identical_failure_streak = 0

                if escalation_level > 0:
                    _reset_chapter_for_retry(orchestrator, ch_num)
                    console.print(
                        f"\n[yellow]⬆ Escalating to relaxation level {escalation_level} "
                        f"(of {len(_ESCALATION_LEVELS) - 1})[/yellow]"
                    )
                    overrides = _ESCALATION_LEVELS[escalation_level]
                    for k, v in overrides.items():
                        console.print(f"  [dim]{k} = {v}[/dim]")

                level_exhausted = False
                while True:
                    attempts += 1
                    console.print(
                        f"[cyan]Chapter {ch_num} convergence attempt {attempts}"
                        f" (level {escalation_level})[/cyan]"
                    )
                    if attempts > max_attempts:
                        _persist_convergence_failure(
                            orchestrator=orchestrator,
                            chapter_number=ch_num,
                            attempts=attempts - 1,
                            reason=f"max_attempts_exceeded_level_{escalation_level}",
                            signature=last_failure_signature or "none",
                        )
                        level_exhausted = True
                        break

                    try:
                        gen_stage.generate_single_chapter(ch_num)
                        rev_stage.revise_single_chapter(ch_num)
                    except ContractEnforcementError as exc:
                        chapter_state = orchestrator.state_manager.load_chapter_state(ch_num) or {}
                        signature = _build_failure_signature(
                            chapter_state=chapter_state,
                            fallback=f"contract:{getattr(exc, 'error_code', 'unknown')}",
                        )
                        if signature == last_failure_signature:
                            identical_failure_streak += 1
                        else:
                            last_failure_signature = signature
                            identical_failure_streak = 1
                        console.print(
                            "[yellow]Contract validation failed; continuing autonomous repair loop. "
                            f"({exc.error_code})[/yellow]"
                        )
                        if identical_failure_streak >= max_identical_streak:
                            _persist_convergence_failure(
                                orchestrator=orchestrator,
                                chapter_number=ch_num,
                                attempts=attempts,
                                reason=f"repeated_identical_contract_failure_level_{escalation_level}",
                                signature=signature,
                            )
                            level_exhausted = True
                            break
                        continue

                    chapter_state = orchestrator.state_manager.load_chapter_state(ch_num) or {}
                    if chapter_state.get("accepted", False):
                        converged = True
                        sentry_sdk.metrics.distribution(
                            "chapter.convergence_attempts", attempts,
                            attributes={"project": project_dir.name, "escalation_level": str(escalation_level)},
                        )
                        break

                    signature = _build_failure_signature(
                        chapter_state=chapter_state,
                        fallback="chapter_not_accepted",
                    )
                    if signature == last_failure_signature:
                        identical_failure_streak += 1
                    else:
                        last_failure_signature = signature
                        identical_failure_streak = 1
                    if identical_failure_streak >= max_identical_streak:
                        _persist_convergence_failure(
                            orchestrator=orchestrator,
                            chapter_number=ch_num,
                            attempts=attempts,
                            reason=f"repeated_identical_non_accept_level_{escalation_level}",
                            signature=signature,
                        )
                        level_exhausted = True
                        break

                    console.print(
                        "[yellow]Chapter not yet accepted; re-running convergence loop.[/yellow]"
                    )

                if converged:
                    break

                if level_exhausted:
                    console.print(
                        f"[yellow]Level {escalation_level} exhausted after {attempts} attempts.[/yellow]"
                    )

            if not converged:
                sentry_sdk.logger.error("Convergence exhausted for chapter {chapter}", chapter=ch_num, project=project_dir.name)
                raise RuntimeError(
                    f"Chapter {ch_num} failed to converge after exhausting all "
                    f"{len(_ESCALATION_LEVELS)} escalation levels."
                )
        finally:
            # Always restore original config regardless of outcome
            _restore_config_snapshot(orchestrator.config, config_snapshot)

        # 5. Report result
        polished_path = project_dir / "drafts" / "v3_polish" / f"chapter_{ch_num:02d}.md"
        polished = orchestrator.state_manager.load_chapter_draft(ch_num, "v3_polish")
        word_count = len(polished.split()) if polished else 0

        sentry_sdk.metrics.count("chapters.completed", 1, attributes={"project": project_dir.name})
        sentry_sdk.metrics.distribution("chapter.word_count", word_count, attributes={"project": project_dir.name})
        sentry_sdk.metrics.distribution(
            "chapter.cost_usd", orchestrator.llm.cumulative_cost,
            attributes={"project": project_dir.name, "chapter": str(ch_num)},
        )
        sentry_sdk.metrics.distribution(
            "chapter.total_tokens",
            orchestrator.llm.cumulative_input_tokens + orchestrator.llm.cumulative_output_tokens,
            attributes={"project": project_dir.name},
        )

        next_unaccepted = orchestrator.state_manager.get_next_unaccepted_chapter(total_chapters)
        remaining = 0 if next_unaccepted is None else (total_chapters - ch_num)
        console.print(
            f"\n[bold green]Chapter {ch_num}/{total_chapters} polished! "
            f"({word_count:,} words)[/bold green]"
        )
        console.print(f"  [dim]{polished_path}[/dim]")

        if remaining > 0:
            console.print(
                f"\n  {remaining} chapter{'s' if remaining != 1 else ''} remaining. "
                f"Run [bold]sovereign-ink next -p {project_dir}[/bold] again."
            )
        else:
            console.print(
                f"\n  [bold green]All chapters complete![/bold green] "
                f"Run [bold]sovereign-ink export -p {project_dir}[/bold] to assemble the manuscript."
            )

        # Save final state
        orchestrator.pipeline_state.total_tokens_used = (
            orchestrator.llm.cumulative_input_tokens + orchestrator.llm.cumulative_output_tokens
        )
        orchestrator.pipeline_state.total_cost_estimate = orchestrator.llm.cumulative_cost
        orchestrator.state_manager.save_pipeline_state(orchestrator.pipeline_state)

        console.print(
            f"\n  Tokens this run: {orchestrator.llm.cumulative_input_tokens + orchestrator.llm.cumulative_output_tokens:,}"
        )
        console.print(f"  Cost this run: ${orchestrator.llm.cumulative_cost:.4f}")

        _txn.__exit__(None, None, None)
        sentry_sdk.flush(timeout=10)
        orchestrator.cleanup()
    except KeyboardInterrupt:
        _txn.__exit__(None, None, None)
        sentry_sdk.flush(timeout=10)
        console.print("\n[yellow]Interrupted. Progress saved — run again to continue.[/yellow]")
        sys.exit(1)
    except Exception as e:
        _txn.__exit__(type(e), e, e.__traceback__)
        sentry_sdk.flush(timeout=10)
        console.print(f"\n[red]Error: {e}[/red]")
        logging.getLogger(__name__).exception("Chapter generation failed")
        sys.exit(1)


def _ensure_prerequisites(orchestrator):
    """Run stages 1-3 if they haven't completed yet."""
    from sovereign_ink.models import StageStatus

    stages_needed = ["interactive_setup", "world_building", "structural_planning"]
    all_done = all(
        orchestrator.pipeline_state.stages.get(s)
        and orchestrator.pipeline_state.stages[s].status == StageStatus.COMPLETED
        for s in stages_needed
    )

    if not all_done:
        console.print("[cyan]Running prerequisite stages (setup, world building, structure)...[/cyan]\n")
        orchestrator.run(stop_after="structural_planning")
        console.print()


def _build_failure_signature(chapter_state: dict, fallback: str) -> str:
    failures = chapter_state.get("last_failures") or []
    if isinstance(failures, list):
        compact_failures = [str(item).strip() for item in failures if str(item).strip()]
    else:
        compact_failures = [str(failures).strip()] if str(failures).strip() else []
    state_name = str(chapter_state.get("state", "")).strip()
    accepted = bool(chapter_state.get("accepted", False))
    if compact_failures:
        return f"{state_name}|accepted={accepted}|{';'.join(compact_failures[:6])}"
    return f"{state_name}|accepted={accepted}|{fallback}"


def _persist_convergence_failure(
    orchestrator,
    chapter_number: int,
    attempts: int,
    reason: str,
    signature: str,
) -> None:
    state_dir = orchestrator.state_manager.project_dir / "state" / "convergence_failures"
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "chapter_number": chapter_number,
        "attempts": attempts,
        "reason": reason,
        "signature": signature,
        "recorded_at": datetime.now().isoformat(),
    }
    failure_path = state_dir / f"chapter_{chapter_number:02d}_latest.json"
    failure_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Self-healing escalation helpers
# ---------------------------------------------------------------------------


def _save_config_snapshot(config) -> dict:
    """Capture current config values for all escalation-affected fields."""
    return {f: getattr(config, f) for f in _ESCALATION_CONFIG_FIELDS}


def _restore_config_snapshot(config, snapshot: dict) -> None:
    """Restore config from a saved snapshot."""
    for field, value in snapshot.items():
        setattr(config, field, value)


def _apply_escalation_level(config, level: int) -> None:
    """Apply escalation overrides for the given level."""
    if level < 0 or level >= len(_ESCALATION_LEVELS):
        return
    for field, value in _ESCALATION_LEVELS[level].items():
        setattr(config, field, value)


def _reset_chapter_for_retry(orchestrator, ch_num: int) -> None:
    """Reset chapter state and drafts for a fresh retry at a new escalation level."""
    project_dir = orchestrator.state_manager.project_dir

    # Reset chapter state file
    state_path = project_dir / "state" / "chapter_states" / f"chapter_{ch_num:02d}.json"
    if state_path.exists():
        state_path.write_text(json.dumps({
            "chapter_number": ch_num,
            "state": "",
            "accepted": False,
            "accepted_draft_version": None,
            "attempt_count": 0,
            "last_failures": [],
            "accepted_at": None,
            "last_updated_at": None,
        }, indent=2), encoding="utf-8")

    # Delete convergence failure file
    failure_path = project_dir / "state" / "convergence_failures" / f"chapter_{ch_num:02d}_latest.json"
    failure_path.unlink(missing_ok=True)

    # Delete in-progress drafts for this chapter across all draft directories
    drafts_dir = project_dir / "drafts"
    if drafts_dir.exists():
        for draft_dir in drafts_dir.iterdir():
            if draft_dir.is_dir():
                draft_file = draft_dir / f"chapter_{ch_num:02d}.md"
                draft_file.unlink(missing_ok=True)


def _ensure_scene_breakdowns(orchestrator, ch_num: int) -> None:
    """Generate scene breakdown for *ch_num* if it is missing from the structure."""
    structure = orchestrator.state_manager.load_novel_structure()
    if structure is None:
        return
    existing = {sb.chapter_number for sb in (structure.scene_breakdowns or [])}
    if ch_num in existing:
        return

    console.print(
        f"[cyan]Scene breakdown missing for chapter {ch_num} — generating now...[/cyan]"
    )
    from sovereign_ink.pipeline.stages.stage3_structural_planning import (
        StructuralPlanningStage,
    )

    stage = StructuralPlanningStage(
        state_manager=orchestrator.state_manager,
        llm_client=orchestrator.llm,
        prompt_renderer=orchestrator.prompts,
        config=orchestrator.config,
        pipeline_state=orchestrator.pipeline_state,
    )
    novel_spec = orchestrator.state_manager.load_novel_spec()
    world_state = orchestrator.state_manager.load_world_state()
    system_prompt = stage.prompts.render_system_prompt(
        era_tone_guide=world_state.era_tone_guide
    )
    stage._build_scene_breakdowns(system_prompt, novel_spec, world_state)
    console.print("[green]Scene breakdowns generated.[/green]")


@cli.command("migrate-compliance")
@click.option("--project-dir", "-p", type=click.Path(exists=True), required=True,
              help="Path to the project directory")
def migrate_compliance(project_dir):
    """Backfill chapter compliance artifacts from legacy gate files."""
    from sovereign_ink.utils.compliance_migration import backfill_compliance_reports

    project_path = Path(project_dir).resolve()
    created = backfill_compliance_reports(project_path)
    console.print(
        f"[green]Compliance migration complete.[/green] "
        f"Created {created} report(s)."
    )


@cli.command()
@click.option("--project-dir", "-p", type=click.Path(exists=True), required=True,
              help="Path to the project directory")
@click.option("--version", type=str, default=None,
              help="Draft version to export (e.g., v0_raw, v7_final). Defaults to latest.")
def export(project_dir, version):
    """Assemble and export the final manuscript."""
    from sovereign_ink.utils.logging import setup_logging

    project_dir = Path(project_dir).resolve()
    setup_logging(project_dir / "logs")

    from sovereign_ink.pipeline.orchestrator import PipelineOrchestrator

    try:
        orchestrator = PipelineOrchestrator(project_dir)

        # Run just the assembly stage
        orchestrator.run(start_from="assembly_export")

        manuscript_path = project_dir / "output" / "manuscript.md"
        if manuscript_path.exists():
            word_count = len(manuscript_path.read_text().split())
            console.print(f"\n[bold green]Manuscript exported![/bold green]")
            console.print(f"Location: {manuscript_path}")
            console.print(f"Word count: {word_count:,}")

        orchestrator.cleanup()
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        sys.exit(1)


@cli.command()
@click.option(
    "--project-dir",
    "-p",
    type=click.Path(),
    default=None,
    help="Path to the project directory to publish (required unless --all).",
)
@click.option(
    "--all",
    "publish_all",
    is_flag=True,
    default=False,
    help="Publish all novels listed under `novels:` in generation_config.yaml.",
)
def publish(project_dir, publish_all):
    """Copy polished chapters into the repo-level published/ folder."""
    if publish_all and project_dir:
        console.print("[red]Use either --all or --project-dir, not both.[/red]")
        sys.exit(1)
    if not publish_all and not project_dir:
        console.print("[red]Provide --all or --project-dir.[/red]")
        sys.exit(1)

    anchor = Path(project_dir).resolve() if project_dir else Path.cwd().resolve()
    repo_root = _find_repo_root(anchor)
    if repo_root is None:
        console.print(
            "[red]Could not find generation_config.yaml in this directory tree.[/red]"
        )
        sys.exit(1)

    try:
        novels = _load_publish_novels(repo_root)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        sys.exit(1)

    selected = novels
    if project_dir and not publish_all:
        target = Path(project_dir).resolve()
        selected = [
            novel
            for novel in novels
            if (repo_root / str(novel["project_dir"])).resolve() == target
        ]
        if not selected:
            console.print(
                "[red]No matching novel entry found in generation_config.yaml "
                f"for project directory: {target}[/red]"
            )
            sys.exit(1)

    published_root = repo_root / "published"
    published_root.mkdir(parents=True, exist_ok=True)

    console.print(Panel("[bold cyan]Sovereign Ink[/bold cyan] — Publish", expand=False))
    console.print(f"Repo root: [dim]{repo_root}[/dim]")
    console.print(f"Published output: [dim]{published_root}[/dim]\n")

    published_count = 0
    skipped_count = 0
    for novel in selected:
        try:
            if _publish_single_novel(repo_root, published_root, novel):
                published_count += 1
            else:
                skipped_count += 1
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            sys.exit(1)

    console.print(
        f"\n[bold green]Publish complete.[/bold green] "
        f"Published: {published_count}, skipped: {skipped_count}"
    )


def _find_repo_root(anchor: Path) -> Path | None:
    """Find nearest ancestor config, preferring one with `novels:` mapping."""
    if anchor.is_file():
        anchor = anchor.parent
    fallback: Path | None = None
    for candidate in [anchor, *anchor.parents]:
        config_path = candidate / "generation_config.yaml"
        if not config_path.exists():
            continue
        if fallback is None:
            fallback = candidate
        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            novels = raw.get("novels")
            if isinstance(novels, list) and novels:
                return candidate
        except Exception:
            continue
    return fallback


def _load_publish_novels(repo_root: Path) -> list[dict]:
    """Load and validate novels mapping from generation_config.yaml."""
    config_path = repo_root / "generation_config.yaml"
    with open(config_path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    novels = raw.get("novels")
    if not isinstance(novels, list) or not novels:
        raise ValueError(
            "generation_config.yaml must include a non-empty `novels:` list for publish."
        )

    required = {"project_dir", "slug", "description"}
    validated: list[dict] = []
    for idx, entry in enumerate(novels, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"`novels[{idx}]` must be a mapping.")
        missing = sorted(required - set(entry.keys()))
        if missing:
            raise ValueError(
                f"`novels[{idx}]` is missing required keys: {', '.join(missing)}"
            )
        validated.append(
            {
                "project_dir": str(entry["project_dir"]).strip(),
                "slug": str(entry["slug"]).strip(),
                "title": str(entry.get("title", "")).strip(),
                "description": str(entry["description"]).strip(),
            }
        )
    return validated


def _resolve_publish_title(repo_root: Path, novel: dict) -> str:
    """Resolve publish title from novel_spec first, then config fallback."""
    project_dir = (repo_root / novel["project_dir"]).resolve()
    spec_path = project_dir / "config" / "novel_spec.json"
    spec_title = ""

    if spec_path.exists():
        try:
            spec_raw = json.loads(spec_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid JSON in novel spec: {spec_path} ({exc})"
            ) from exc

        if not isinstance(spec_raw, dict):
            raise ValueError(f"Novel spec must be a JSON object: {spec_path}")
        spec_title = str(spec_raw.get("title", "")).strip()

    config_title = str(novel.get("title", "")).strip()
    resolved = spec_title or config_title
    if not resolved:
        raise ValueError(
            "Missing publish title. Provide a non-empty `title` in either "
            f"{spec_path} or generation_config.yaml novels entry for "
            f"project_dir={novel['project_dir']}."
        )
    return resolved


def _publish_single_novel(repo_root: Path, published_root: Path, novel: dict) -> bool:
    """Publish one novel's polished chapters into published/<slug>/."""
    source_dir = (
        repo_root / novel["project_dir"] / "drafts" / "v3_polish"
    ).resolve()
    dest_dir = (published_root / novel["slug"]).resolve()

    if not source_dir.exists() or not source_dir.is_dir():
        console.print(
            f"[yellow]WARNING: source not found: {source_dir} "
            f"(slug={novel['slug']})[/yellow]"
        )
        return False

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    chapter_files = sorted(
        f for f in source_dir.glob("chapter_*.md") if f.is_file()
    )

    chapter_count = 0
    for chapter_file in chapter_files:
        new_name = chapter_file.name.replace("_", "-")
        shutil.copy2(chapter_file, dest_dir / new_name)
        chapter_count += 1

    meta = {
        "title": _resolve_publish_title(repo_root, novel),
        "slug": novel["slug"],
        "chapterCount": chapter_count,
        "description": novel["description"],
    }
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )

    console.print(
        f"[green]✓ {novel['slug']}: {chapter_count} chapters published[/green]"
    )
    return True


def _display_spec(spec):
    """Display the NovelSpec in a nice format."""
    table = Table(title="Novel Specification", show_header=False, box=None)
    table.add_column("Field", style="cyan", width=20)
    table.add_column("Value")

    table.add_row("Title", spec.title or "(to be generated)")
    table.add_row("Era", f"{spec.era_start}–{spec.era_end}")
    table.add_row("Region", spec.region)
    table.add_row("Central Event", spec.central_event)
    table.add_row("Tone", spec.tone_intensity.replace("_", " ").title())
    table.add_row("POV Count", str(spec.pov_count))
    table.add_row("Protagonist Type", spec.protagonist_type.replace("_", " ").title())
    table.add_row("Themes", ", ".join(spec.thematic_focus))
    table.add_row("Target Length", spec.desired_length.replace("_", " ").title())
    if spec.synopsis:
        table.add_row("Synopsis", spec.synopsis[:200] + ("..." if len(spec.synopsis) > 200 else ""))
    if spec.additional_notes:
        table.add_row("Notes", spec.additional_notes)

    console.print()
    console.print(table)
