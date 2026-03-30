"""Stage 5: Consolidated 3-Pass Revision Pipeline."""

import json
import logging
import re
from datetime import datetime
from rich.console import Console

from sovereign_ink.pipeline.base import PipelineStage
from sovereign_ink.pipeline.errors import ContractEnforcementError
from sovereign_ink.utils.phrase_tracker import load_banned_phrases, load_banned_constructions
from sovereign_ink.utils.text_quality import (
    build_quality_snapshot,
    compute_quality_delta,
    detect_within_chapter_repetition,
    detect_duplicate_passages,
    detect_exposition_drag,
    detect_low_immediate_jeopardy,
    detect_low_propulsion_endings,
    format_repetition_report,
    format_low_propulsion_endings_report,
    format_duplicate_report,
    format_regression_report,
    run_all_quality_checks,
    run_chapter_gates,
    run_scene_contract_checks,
    detect_incomplete_chapter_ending,
)
from sovereign_ink.models import ChapterStateStatus
from sovereign_ink.pipeline.stages.stage4_prose_generation import ProseGenerationStage

logger = logging.getLogger(__name__)
console = Console()

REVISION_PASSES = [
    {
        "number": 1,
        "name": "structural",
        "version": "v1_structural",
        "focus": "Structural coherence + stakes escalation",
    },
    {
        "number": 2,
        "name": "voice_and_dialogue",
        "version": "v2_voice_and_dialogue",
        "focus": "Character voice differentiation + dialogue quality",
    },
    {
        "number": 3,
        "name": "polish",
        "version": "v3_polish",
        "focus": "Repetition removal + thematic coherence + final polish",
    },
]


class RevisionPipelineStage(PipelineStage):
    STAGE_NAME = "revision_pipeline"
    OUTLINE_CRITICAL_ERROR_CODES = {
        "revision_contract_failed",
        "revision_pass_contract_failed",
        "revision_final_acceptance_failed",
        "ending_propulsion_failed",
    }

    def _strict_contract_mode(self) -> bool:
        mode = getattr(self.config, "contract_enforcement_mode", "safe")
        fail_closed = bool(getattr(self.config, "contract_fail_closed", False))
        return mode == "strict" or fail_closed

    def _maybe_fail_contract(
        self,
        ch_num: int,
        message: str,
        *,
        error_code: str = "revision_contract_failed",
    ) -> None:
        is_critical = error_code in self.OUTLINE_CRITICAL_ERROR_CODES
        if is_critical or self._strict_contract_mode():
            raise ContractEnforcementError(
                message,
                chapter_number=ch_num,
                stage_name=self.STAGE_NAME,
                error_code=error_code,
            )
        logger.warning("Chapter %d non-blocking revision failure: %s", ch_num, message)

    def check_prerequisites(self) -> bool:
        drafts = self.state_manager.load_all_chapter_drafts("v0_raw")
        return len(drafts) > 0

    def _stage4_validator(self) -> ProseGenerationStage:
        stage = ProseGenerationStage.__new__(ProseGenerationStage)
        stage.state_manager = self.state_manager
        stage.llm = self.llm
        stage.prompts = self.prompts
        stage.config = self.config
        return stage

    def _validate_revision_contracts(
        self,
        *,
        ch_num: int,
        chapter_content: str,
        structure,
        final_acceptance: bool,
    ):
        validator = self._stage4_validator()
        chapter_outline = None
        scene_breakdown = None
        if structure:
            for co in structure.chapter_outlines:
                if co.chapter_number == ch_num:
                    chapter_outline = co
                    break
            for sb in structure.scene_breakdowns:
                if sb.chapter_number == ch_num:
                    scene_breakdown = sb
                    break
        scene_reports: list[dict] = []
        if scene_breakdown and getattr(scene_breakdown, "scenes", None):
            split_scenes = validator._split_chapter_into_scenes(chapter_content)
            for idx, contract in enumerate(scene_breakdown.scenes):
                scene_text = split_scenes[idx] if idx < len(split_scenes) else ""
                check = run_scene_contract_checks(
                    scene_text,
                    contract,
                    enable_physical_interruption_contracts=bool(
                        getattr(self.config, "enable_physical_interruption_contracts", False)
                    ),
                    enable_narrative_register=bool(
                        getattr(self.config, "enable_narrative_register", False)
                    ),
                )
                scene_reports.append(
                    {
                        "scene_number": contract.scene_number,
                        "passed": check.get("passed", False),
                        "failures": check.get("failures", []),
                        "retries": 0,
                    }
                )
        original_trigger = getattr(self.config, "adversarial_trigger", "both")
        setattr(self.config, "adversarial_trigger", "never")
        try:
            report = validator._evaluate_compliance(
                ch_num=ch_num,
                chapter_content=chapter_content,
                chapter_outline=chapter_outline,
                scene_breakdown=scene_breakdown,
                scene_reports=scene_reports,
            )
        finally:
            setattr(self.config, "adversarial_trigger", original_trigger)
        # Revision acceptance enforces:
        #   1. Structural integrity (scene count, chapter beats, ending hook).
        #   2. Semantic validator (chapter-level requirements).
        # It does NOT re-run the adversarial verifier because:
        #   - The adversarial check already passed in Stage 4 on v0_raw.
        #   - Revision changes prose phrasing; re-running adversarial on each
        #     revision version produces inconsistent verdicts and infinite loops.
        #   - Scene-level phrase contracts (gesture, interruption) are also
        #     excluded for the same reason — they were validated in Stage 4.
        revision_accepted = (
            report.deterministic.structural_passed
            and report.semantic.passed
        )
        # Keep the persisted report aligned with revision acceptance semantics.
        # Stage 5 intentionally relaxes deterministic lexical checks from Stage 4,
        # so acceptance_passed/status should reflect revision_accepted here.
        report.acceptance_passed = bool(revision_accepted)
        report.status = "passed" if revision_accepted else "failed"
        return report, revision_accepted

    # ------------------------------------------------------------------
    # Single-chapter revision (reusable)
    # ------------------------------------------------------------------

    def revise_single_chapter(self, ch_num: int) -> str:
        """Run all configured revision passes on a single chapter,
        from v0_raw through to v3_polish.  Returns the final polished text.

        This is the building-block used by both ``run()`` (batch mode)
        and the ``sovereign-ink next`` CLI command.
        """
        structure = self.state_manager.load_novel_structure()
        world_state = self.state_manager.load_world_state()

        novel_structure_summary = self._build_structure_summary(structure)
        system_prompt = self.prompts.render_system_prompt(
            era_tone_guide=world_state.era_tone_guide if world_state else None
        )
        state_dir = self.state_manager.project_dir / "state"
        banned_phrases = load_banned_phrases(state_dir)

        # P1: Run quality audit on v0_raw before revision passes
        v0_content = self.state_manager.load_chapter_draft(ch_num, "v0_raw")
        quality_audit_report = ""
        structural_quality_reports: dict[str, str] = {}
        use_opus_structural = False
        gate_escalation_context = ""
        if v0_content:
            quality_audit_report = self._run_quality_audit(
                ch_num, v0_content, system_prompt, structure
            )
            # P0/P5/P6: Run code-level quality checks
            structural_quality_reports = run_all_quality_checks(v0_content)
            if structural_quality_reports:
                checks = ", ".join(structural_quality_reports.keys())
                console.print(
                    f"    [yellow]Quality issues detected: {checks}[/yellow]"
                )

            # Load Stage 4 gate results for escalation awareness
            gate_data = self.state_manager.load_gate_results(ch_num)
            if gate_data and not gate_data.get("all_passed", True):
                gate_escalation_context = self._build_gate_escalation_context(
                    gate_data
                )

            if self.config.enable_selective_opus_structural_revision:
                snapshot = build_quality_snapshot(v0_content)
                counts = snapshot.get("counts", {})
                word_count = max(int(snapshot.get("word_count", 0)), 1)
                immediate_deficit_count = int(
                    counts.get("immediate_jeopardy_deficit_scenes", 0)
                )
                immediate_per_10k = immediate_deficit_count / (word_count / 10000.0)
                offstage_flag = int(
                    counts.get("offstage_opposition_overuse_flag", 0)
                ) == 1
                opus_eligible = getattr(
                    self.config,
                    "opus_eligible_gates",
                    ["offstage_opposition", "immediate_jeopardy"],
                )
                use_opus_structural = False
                if "offstage_opposition" in opus_eligible:
                    use_opus_structural = use_opus_structural or offstage_flag
                if "immediate_jeopardy" in opus_eligible:
                    use_opus_structural = use_opus_structural or (
                        immediate_per_10k
                        > self.config.immediate_jeopardy_opus_threshold_per_10k_words
                    )
                if use_opus_structural:
                    console.print(
                        "    [yellow]Selective Opus trigger active for structural "
                        "revision on this chapter[/yellow]"
                    )

        num_passes = min(self.config.num_revision_passes, len(REVISION_PASSES))
        final_content = ""
        chapter_outline = None
        if structure:
            for co in structure.chapter_outlines:
                if co.chapter_number == ch_num:
                    chapter_outline = co
                    break

        # Inter-pass quality tracking: accumulate regression warnings for subsequent passes
        regression_warnings = ""

        for pass_info in REVISION_PASSES[:num_passes]:
            pass_num = pass_info["number"]
            pass_name = pass_info["name"]
            version = pass_info["version"]

            existing = self.state_manager.load_chapter_draft(ch_num, version)
            chapter_state = self.state_manager.load_chapter_state(ch_num) or {}
            fully_accepted = self.state_manager.is_chapter_fully_accepted(ch_num)
            if existing and fully_accepted:
                logger.info(
                    "Chapter %d revision pass %d (%s) already exists, skipping",
                    ch_num, pass_num, pass_name,
                )
                final_content = existing
                continue

            if pass_num == 1:
                source_version = "v0_raw"
            else:
                source_version = REVISION_PASSES[pass_num - 2]["version"]

            source_content = self.state_manager.load_chapter_draft(ch_num, source_version)
            if not source_content:
                raise ValueError(
                    f"Cannot revise chapter {ch_num}: missing {source_version} draft"
                )

            extra_audit_context = ""
            parts: list[str] = []

            if pass_num == 1 and quality_audit_report:
                parts.append(quality_audit_report)
            if pass_num == 1 and gate_escalation_context:
                parts.append(gate_escalation_context)

            if pass_num == 1:
                for report in structural_quality_reports.values():
                    parts.append(report)
            elif pass_num == 2:
                # Inject a quality baseline snapshot so the voice pass knows
                # exactly which metrics it must not worsen.
                voice_preservation_reports = self._build_voice_preservation_context(
                    source_content
                )
                for report in voice_preservation_reports.values():
                    parts.append(report)
            elif pass_num == 3:
                pass_quality_reports = self._build_polish_quality_reports(
                    source_content
                )
                for report in pass_quality_reports.values():
                    parts.append(report)

            if regression_warnings:
                parts.append(regression_warnings)

            extra_audit_context = "\n\n".join(parts)

            # Phase 9D: For long chapters on the polish pass, run dedup surgery first.
            if pass_num == 3 and getattr(self.config, "enable_long_chapter_dedup_first", False):
                word_count = len(source_content.split())
                dedup_cap = int(getattr(self.config, "dedup_first_soft_cap_words", 5000))
                if word_count > dedup_cap:
                    console.print(
                        f"    [cyan]Long chapter ({word_count} words > {dedup_cap} cap) — "
                        f"running dedup-first pass before polish[/cyan]"
                    )
                    deduped_content = self._targeted_dedup_pass(
                        ch_num=ch_num,
                        chapter_content=source_content,
                        system_prompt=system_prompt,
                    )
                    if deduped_content != source_content:
                        self.state_manager.save_chapter_draft(
                            ch_num, deduped_content, "v2_voice_and_dialogue_post_dedup"
                        )
                        source_content = deduped_content

            # For the voice pass, optionally use a targeted diagnose/patch
            # approach instead of a full chapter rewrite, when enabled in config.
            if (
                pass_num == 2
                and getattr(self.config, "enable_targeted_voice_revision", False)
            ):
                chapter_outline_dict = (
                    chapter_outline.model_dump() if chapter_outline else {}
                )
                targeted_kwargs: dict = {}
                if world_state:
                    targeted_kwargs["character_profiles"] = [
                        c.model_dump() for c in world_state.characters
                    ]
                console.print(
                    f"    [cyan]Voice pass: targeted diagnose/patch mode[/cyan]"
                )
                final_content = self._targeted_voice_revision(
                    ch_num=ch_num,
                    chapter_content=source_content,
                    system_prompt=system_prompt,
                    chapter_outline_dict=chapter_outline_dict,
                    extra_kwargs=targeted_kwargs,
                )
                self.state_manager.save_chapter_draft(ch_num, final_content, version)
            else:
                final_content = self._revise_single_chapter(
                    ch_num=ch_num,
                    chapter_content=source_content,
                    pass_info=pass_info,
                    system_prompt=system_prompt,
                    novel_structure_summary=novel_structure_summary,
                    world_state=world_state,
                    structure=structure,
                    banned_phrases=banned_phrases,
                    quality_audit=extra_audit_context,
                    use_opus_structural=use_opus_structural,
                )

            # P0: Post-revision duplicate check with auto-retry
            dupes = detect_duplicate_passages(final_content)
            if dupes and pass_num <= 2:
                dupe_report = format_duplicate_report(dupes)
                console.print(
                    f"    [red]Duplicates detected after {pass_name} — retrying[/red]"
                )
                self.state_manager.save_chapter_draft(
                    ch_num, final_content, f"{version}_pre_dedup"
                )
                final_content = self._revise_single_chapter(
                    ch_num=ch_num,
                    chapter_content=final_content,
                    pass_info=pass_info,
                    system_prompt=system_prompt,
                    novel_structure_summary=novel_structure_summary,
                    world_state=world_state,
                    structure=structure,
                    banned_phrases=banned_phrases,
                    quality_audit=dupe_report,
                    is_dedup_retry=True,
                    use_opus_structural=use_opus_structural,
                )

            # C3b: Voice pass regression guard — retry from pre-voice input if
            # the voice pass introduced new quality regressions.
            if pass_num == 2:
                max_regression_retry = getattr(
                    self.config, "voice_pass_max_regression_retry", 1
                )
                if max_regression_retry > 0:
                    voice_delta = compute_quality_delta(source_content, final_content)
                    if voice_delta["has_regressions"]:
                        regressed_names = ", ".join(
                            r["metric"] for r in voice_delta["regressions"]
                        )
                        console.print(
                            f"    [yellow]Voice pass introduced regressions "
                            f"({regressed_names}) — retrying from pre-voice "
                            f"input with regression context[/yellow]"
                        )
                        regression_context = format_regression_report(
                            voice_delta, pass_name
                        )
                        self.state_manager.save_chapter_draft(
                            ch_num, final_content,
                            f"{version}_pre_regression_retry"
                        )
                        combined_audit = (
                            regression_context + "\n\n" + extra_audit_context
                            if extra_audit_context
                            else regression_context
                        )
                        final_content = self._revise_single_chapter(
                            ch_num=ch_num,
                            chapter_content=source_content,
                            pass_info=pass_info,
                            system_prompt=system_prompt,
                            novel_structure_summary=novel_structure_summary,
                            world_state=world_state,
                            structure=structure,
                            banned_phrases=banned_phrases,
                            quality_audit=combined_audit,
                            use_opus_structural=False,
                        )

            # Phase 10: Regression guard runs BEFORE the ending check so that
            # compression inside _revise_single_chapter cannot overwrite a
            # propulsive ending that was written by _apply_ending_propulsion_retries.
            if pass_num in (1, 3):
                max_retry = int(getattr(self.config, "pass_regression_max_retry", 1))
                for retry_idx in range(max_retry):
                    delta = compute_quality_delta(source_content, final_content)
                    critical = self._critical_regressions(delta)
                    if not critical:
                        break
                    regressed_names = ", ".join(r["metric"] for r in critical)
                    console.print(
                        f"    [yellow]{pass_name} pass critical regressions "
                        f"({regressed_names}) — retrying from pre-pass input "
                        f"({retry_idx + 1}/{max_retry})[/yellow]"
                    )
                    regression_context = format_regression_report(delta, pass_name)
                    # Phase 9C: inject momentum-recovery macro when exposition drag regressed
                    drag_regressed = any(
                        r["metric"] == "exposition_drag_runs" for r in critical
                    )
                    if drag_regressed:
                        momentum_macro = self._build_exposition_momentum_macro(delta)
                        regression_context = regression_context + "\n\n" + momentum_macro
                    # Phase 11: inject jeopardy-recovery macro when jeopardy deficit regressed
                    jeopardy_regressed = any(
                        r["metric"] == "immediate_jeopardy_deficit_scenes" for r in critical
                    )
                    if jeopardy_regressed:
                        jeopardy_macro = self._build_jeopardy_recovery_macro(
                            delta, final_content
                        )
                        regression_context = regression_context + "\n\n" + jeopardy_macro
                    combined_audit = (
                        regression_context + "\n\n" + extra_audit_context
                        if extra_audit_context
                        else regression_context
                    )
                    self.state_manager.save_chapter_draft(
                        ch_num, final_content, f"{version}_pre_regression_retry"
                    )
                    final_content = self._revise_single_chapter(
                        ch_num=ch_num,
                        chapter_content=source_content,
                        pass_info=pass_info,
                        system_prompt=system_prompt,
                        novel_structure_summary=novel_structure_summary,
                        world_state=world_state,
                        structure=structure,
                        banned_phrases=banned_phrases,
                        quality_audit=combined_audit,
                        use_opus_structural=(pass_num == 1 and use_opus_structural),
                    )
                    # Phase 10: No per-iteration ending retry inside the regression
                    # loop — the guaranteed final check below runs after all
                    # compression is done, so it cannot be overwritten.
                post_delta = compute_quality_delta(source_content, final_content)
                post_critical = self._critical_regressions(post_delta)
                if post_critical:
                    regressed_names = ", ".join(r["metric"] for r in post_critical)
                    self._maybe_fail_contract(
                        ch_num,
                        f"Critical revision regressions persisted after retries: {regressed_names}",
                        error_code="critical_revision_regressions",
                    )

                # Phase 10C: When exposition drag is in the critical set and the
                # first retry did not reduce drag, run a second targeted pass that
                # references specific dragging paragraph locations.
                if pass_num == 3 and getattr(
                    self.config, "critical_retry_include_exposition_drag", False
                ):
                    drag_after = detect_exposition_drag(final_content)
                    drag_before_count = len(detect_exposition_drag(source_content))
                    if drag_after and len(drag_after) >= drag_before_count:
                        console.print(
                            "    [yellow]Exposition drag did not improve after retry — "
                            "running targeted paragraph-level drag correction[/yellow]"
                        )
                        targeted_macro = self._build_targeted_exposition_macro(drag_after)
                        drag_audit = (
                            targeted_macro + "\n\n" + extra_audit_context
                            if extra_audit_context
                            else targeted_macro
                        )
                        self.state_manager.save_chapter_draft(
                            ch_num, final_content, f"{version}_pre_drag_retry"
                        )
                        final_content = self._revise_single_chapter(
                            ch_num=ch_num,
                            chapter_content=final_content,
                            pass_info=pass_info,
                            system_prompt=system_prompt,
                            novel_structure_summary=novel_structure_summary,
                            world_state=world_state,
                            structure=structure,
                            banned_phrases=banned_phrases,
                            quality_audit=drag_audit,
                            use_opus_structural=False,
                        )

            # Phase 10: Guaranteed final ending check — runs AFTER all compression
            # passes (including regression retries) so length guardrails can never
            # truncate a propulsive ending.  Persists the result as v3_polish.
            if pass_num == 3:
                if getattr(self.config, "enable_smart_repetition_pass", False):
                    self.state_manager.save_chapter_draft(
                        ch_num, final_content, "v3_polish_pre_smart_repetition"
                    )
                    final_content = self._run_smart_repetition_pass(
                        ch_num=ch_num,
                        chapter_content=final_content,
                        system_prompt=system_prompt,
                        chapter_outline=chapter_outline,
                        structure=structure,
                    )
                final_content = self._apply_revision_ending_final_check(
                    final_content=final_content,
                    chapter_outline=chapter_outline,
                    system_prompt=system_prompt,
                    ch_num=ch_num,
                    version=version,
                )

            report, pass_ok = self._validate_revision_contracts(
                ch_num=ch_num,
                chapter_content=final_content,
                structure=structure,
                final_acceptance=(pass_num == num_passes),
            )
            pass_report_path = (
                self.state_manager.project_dir
                / "state"
                / "quality_reports"
                / f"chapter_{ch_num:02d}_revision_pass_{pass_num}_compliance.json"
            )
            self.state_manager._write_json(pass_report_path, report.model_dump())
            if not pass_ok:
                failed = list(report.deterministic.failures)
                failed.extend(report.semantic.failures)
                self.state_manager.save_chapter_state(
                    ch_num,
                    {
                        "chapter_number": ch_num,
                        "state": ChapterStateStatus.REVALIDATE.value,
                        "accepted": False,
                        "accepted_draft_version": None,
                        "attempt_count": int(
                            (self.state_manager.load_chapter_state(ch_num) or {}).get(
                                "attempt_count", 0
                            )
                        ),
                        "last_failures": failed,
                        "accepted_at": None,
                        "last_updated_at": datetime.now().isoformat(),
                    },
                )
                self._maybe_fail_contract(
                    ch_num,
                    f"Revision pass {pass_num} contract revalidation failed.",
                    error_code="revision_pass_contract_failed",
                )
            if pass_num == num_passes:
                self.state_manager.save_compliance_report(ch_num, report.model_dump())
                self.state_manager.save_chapter_state(
                    ch_num,
                    {
                        "chapter_number": ch_num,
                        "state": ChapterStateStatus.ACCEPTED.value,
                        "accepted": True,
                        "accepted_draft_version": "v3_polish",
                        "attempt_count": int(
                            (self.state_manager.load_chapter_state(ch_num) or {}).get(
                                "attempt_count", 0
                            )
                        ),
                        "last_failures": [],
                        "accepted_at": datetime.now().isoformat(),
                        "last_updated_at": datetime.now().isoformat(),
                    },
                )

            # Inter-pass quality tracking: compute delta after each pass (except the last)
            if pass_num < num_passes:
                delta = compute_quality_delta(source_content, final_content)
                if delta["has_regressions"]:
                    regression_warnings = format_regression_report(delta, pass_name)
                    regressed_names = ", ".join(
                        r["metric"] for r in delta["regressions"]
                    )
                    console.print(
                        f"    [yellow]Regressions after {pass_name}: "
                        f"{regressed_names}[/yellow]"
                    )
                else:
                    regression_warnings = ""

        self._persist_quality_artifacts(
            chapter_number=ch_num,
            v0_content=v0_content or "",
            polished_content=final_content,
        )
        return final_content

    @staticmethod
    def _build_polish_quality_reports(chapter_text: str) -> dict[str, str]:
        """Select polish-relevant quality reports for the final pass."""
        reports = run_all_quality_checks(chapter_text)
        polish_keys = {
            "repetition",
            "frequency_outliers",
            "dialogue_uniformity",
            "metaphor_saturation",
            "surprise_density",
            "offstage_opposition",
            "ending_propulsion",
            "exposition_drag",
            "emotional_control_monotony",
            "sensory_deficit",  # Ensure polish pass sees and preserves sensory grounding
        }
        return {k: v for k, v in reports.items() if k in polish_keys}

    @staticmethod
    def _build_voice_preservation_context(chapter_text: str) -> dict[str, str]:
        """Build a quality-baseline snapshot for the voice pass.

        Reports the current counts for metrics that the voice pass commonly
        worsens.  This is injected into the voice pass prompt so the LLM
        knows exactly which quality dimensions it must not degrade.
        """
        snapshot = build_quality_snapshot(chapter_text)
        counts = snapshot.get("counts", {})

        lines = [
            "## CURRENT QUALITY BASELINE — Voice Pass Must Not Worsen These",
            "",
            "The following metrics were measured on the draft entering this "
            "voice revision pass. Your output MUST NOT produce higher counts "
            "for any of these metrics:",
            "",
            f"- Repetition patterns: {counts.get('repetition_patterns', 0)}",
            f"- Frequency outlier terms: {counts.get('frequency_outlier_terms', 0)}",
            f"- Sensory deficit scenes: {counts.get('sensory_deficit_scenes', 0)}",
            f"- Immediate jeopardy deficit scenes: "
            f"{counts.get('immediate_jeopardy_deficit_scenes', 0)}",
            "",
        ]

        # List existing repetition patterns so the LLM avoids adding more instances
        raw_reps = snapshot.get("raw", {}).get("repetition", [])
        if raw_reps:
            lines.append(
                "**Existing repetition patterns — do NOT add further instances:**"
            )
            for rep in raw_reps[:10]:
                lines.append(f'- "{rep["pattern"]}" ({rep["count"]}x)')
            lines.append("")

        # List scenes already deficient in sensory detail
        sensory_deficits = snapshot.get("raw", {}).get("sensory_deficit", [])
        if sensory_deficits:
            lines.append(
                "**Scenes with sensory deficits — do NOT strip any remaining "
                "sensory detail from these scenes:**"
            )
            for d in sensory_deficits:
                cats = ", ".join(d["categories"]) if d["categories"] else "none"
                lines.append(
                    f"- Scene {d['scene_number']}: {d['total_hits']} non-visual "
                    f"refs, categories present: {cats}"
                )
            lines.append("")

        return {"voice_preservation": "\n".join(lines)}

    def _targeted_voice_revision(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        chapter_outline_dict: dict,
        extra_kwargs: dict,
    ) -> str:
        """Two-phase targeted voice revision: diagnose then patch.

        Phase 1 (diagnose): Send the full chapter to a lightweight diagnostic
        prompt that returns a JSON list of {paragraph_index, issue, suggested_fix}.
        Only paragraphs with genuine voice/dialogue problems are flagged.

        Phase 2 (patch): For each flagged paragraph, send ONLY that paragraph
        (with minimal surrounding context) to the LLM for a focused rewrite and
        splice the result back.  All other paragraphs are copied verbatim,
        eliminating regression surface area.
        """
        # Phase 1: Diagnose
        diagnosis_prompt = self.prompts.render_revision(
            "voice_diagnosis",
            chapter_content=chapter_content,
            chapter_number=ch_num,
            chapter_outline=chapter_outline_dict,
            character_profiles=extra_kwargs.get("character_profiles", []),
        )
        diagnosis_response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=diagnosis_prompt,
            model=self.config.model_revision_creative,
            temperature=0.3,
            max_tokens=4096,
        )
        patches = self._parse_voice_diagnosis(diagnosis_response.content)

        if not patches:
            logger.info("Chapter %d: voice diagnosis found no issues — keeping draft", ch_num)
            return chapter_content

        logger.info(
            "Chapter %d: voice diagnosis flagged %d paragraph(s) for patching",
            ch_num, len(patches),
        )

        # Phase 2: Patch each flagged paragraph individually
        # Split on double newlines, preserving scene break markers
        paragraphs = chapter_content.split("\n\n")
        for patch in patches:
            idx = patch.get("paragraph_index", -1)
            if not isinstance(idx, int) or idx < 0 or idx >= len(paragraphs):
                continue
            # Skip actual scene-break markers
            if paragraphs[idx].strip() == "---":
                continue

            original_para = paragraphs[idx]
            context_before = "\n\n".join(paragraphs[max(0, idx - 2) : idx])
            context_after = "\n\n".join(
                paragraphs[idx + 1 : min(len(paragraphs), idx + 3)]
            )

            patch_prompt = "\n\n".join([
                f"## VOICE PATCH — Paragraph {idx + 1}",
                "",
                f"Issue type: {patch.get('issue_type', 'voice')}",
                f"Issue: {patch.get('issue', '')}",
                f"Suggested fix: {patch.get('suggested_fix', '')}",
                "---",
                "### Preceding context (do NOT rewrite)",
                context_before,
                "---",
                "### Paragraph to rewrite",
                original_para,
                "---",
                "### Following context (do NOT rewrite)",
                context_after,
                "---",
                "Rewrite ONLY the paragraph above to fix the identified voice issue. "
                "Preserve ALL sensory detail, jeopardy markers, and factual content. "
                "The replacement must have similar word count to the original. "
                "Output ONLY the rewritten paragraph — no commentary, no headers.",
            ])

            patch_response = self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=patch_prompt,
                model=self.config.model_revision_creative,
                temperature=self.config.temperature_revision,
                max_tokens=1024,
            )
            paragraphs[idx] = patch_response.content.strip()

        return "\n\n".join(paragraphs)

    @staticmethod
    def _parse_voice_diagnosis(content: str) -> list[dict]:
        """Parse the JSON array returned by the voice diagnosis pass.

        Returns an empty list on parse failure so the caller can fall back
        to the full-chapter revision path.
        """
        import json as _json

        text = content.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # Find the first "[" in case there's preamble text
        start = text.find("[")
        if start < 0:
            logger.warning("Voice diagnosis returned no JSON array")
            return []

        # Find the matching "]"
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for i, ch in enumerate(text[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end < 0:
            logger.warning("Voice diagnosis returned malformed JSON array")
            return []

        try:
            patches = _json.loads(text[start : end + 1])
            if not isinstance(patches, list):
                return []
            return [p for p in patches if isinstance(p, dict)]
        except _json.JSONDecodeError as exc:
            logger.warning("Voice diagnosis JSON parse error: %s", exc)
            return []

    @staticmethod
    def _extract_first_json_array(content: str) -> str:
        """Extract the first balanced JSON array from model output."""
        start = content.find("[")
        if start < 0:
            raise json.JSONDecodeError("No JSON array start found", content, 0)

        depth = 0
        in_string = False
        escaped = False
        for idx, ch in enumerate(content[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return content[start : idx + 1]

        raise json.JSONDecodeError(
            "Unbalanced JSON array in model output", content, start
        )

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        text = content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:] if lines and lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def _parse_repetition_critic_json(self, content: str) -> list[dict] | None:
        """Parse critic output array. Returns None when malformed."""
        text = self._strip_markdown_fences(content)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            try:
                payload = json.loads(self._extract_first_json_array(text))
            except json.JSONDecodeError:
                return None

        if not isinstance(payload, list):
            return None

        findings: list[dict] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            start = raw.get("start_paragraph")
            end = raw.get("end_paragraph")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if start < 0 or end < start:
                continue
            findings.append(raw)
        return findings

    def _parse_repetition_editor_json(self, content: str) -> dict | None:
        """Parse editor output object. Returns None when malformed."""
        text = self._strip_markdown_fences(content)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            try:
                payload = json.loads(self._extract_first_json_object(text))
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        rewritten = payload.get("rewritten_span", "")
        if not isinstance(rewritten, str) or not rewritten.strip():
            return None
        return payload

    def _parse_repetition_judge_json(self, content: str) -> dict | None:
        """Parse judge output object. Returns None when malformed."""
        text = self._strip_markdown_fences(content)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            try:
                payload = json.loads(self._extract_first_json_object(text))
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        return payload

    @staticmethod
    def _build_paragraph_index_map(blocks: list[str]) -> dict[int, int]:
        """Map logical paragraph index (excluding scene markers) to block index."""
        para_to_block: dict[int, int] = {}
        para_idx = 0
        for block_idx, block in enumerate(blocks):
            stripped = block.strip()
            if not stripped or stripped == "---":
                continue
            para_to_block[para_idx] = block_idx
            para_idx += 1
        return para_to_block

    @staticmethod
    def _repetition_pattern_key(pattern: str) -> str:
        value = str(pattern or "").strip().lower()
        if " — e.g. " in value:
            return value.split(" — e.g. ", 1)[0].strip()
        return value

    @classmethod
    def _repetition_burden(
        cls,
        repetitions: list[dict],
        target_pattern_keys: set[str] | None = None,
    ) -> int:
        burden = 0
        keys = target_pattern_keys or set()
        for item in repetitions:
            key = cls._repetition_pattern_key(str(item.get("pattern", "")))
            if keys and key not in keys:
                continue
            count = int(item.get("count", 0) or 0)
            burden += max(count - 2, 0)
        return burden

    @classmethod
    def _detect_repetition_targets_for_paragraphs(
        cls, paragraphs: dict[int, str], repetitions: list[dict]
    ) -> list[dict]:
        targets: list[dict] = []
        for item in repetitions:
            pattern = str(item.get("pattern", "")).strip()
            if not pattern:
                continue
            marker = cls._repetition_pattern_key(pattern)
            marker = marker.lower()
            if not marker:
                continue
            matched_paragraphs: list[int] = []
            for para_idx, para_text in paragraphs.items():
                if marker and marker in para_text.lower():
                    matched_paragraphs.append(para_idx)
            targets.append(
                {
                    "pattern": pattern,
                    "pattern_key": marker,
                    "count": int(item.get("count", 0) or 0),
                    "ngram_size": int(item.get("ngram_size", 0) or 0),
                    "paragraphs": matched_paragraphs,
                }
            )
        return targets

    @staticmethod
    def _target_pattern_keys_for_span(
        start_para: int, end_para: int, detector_targets: list[dict]
    ) -> list[str]:
        span_keys: list[str] = []
        for target in detector_targets:
            paras = target.get("paragraphs", [])
            if not isinstance(paras, list):
                continue
            if any(start_para <= int(p) <= end_para for p in paras):
                key = str(target.get("pattern_key", "")).strip()
                if key:
                    span_keys.append(key)
        # de-dup while preserving order
        deduped: list[str] = []
        seen: set[str] = set()
        for key in span_keys:
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def _extract_protected_anchors(
        self,
        *,
        ch_num: int,
        chapter_outline,
        structure,
    ) -> list[str]:
        """Collect protected anchor text fragments that edits must preserve."""
        anchors: list[str] = []
        if chapter_outline:
            for field in (
                "hard_reveal",
                "on_page_opposing_move",
                "required_end_hook",
                "chapter_goal",
                "turn",
                "consequences",
            ):
                value = getattr(chapter_outline, field, "")
                if isinstance(value, str) and value.strip():
                    anchors.append(value.strip())

        if structure:
            scene_breakdown = None
            for sb in structure.scene_breakdowns:
                if sb.chapter_number == ch_num:
                    scene_breakdown = sb
                    break
            if scene_breakdown and getattr(scene_breakdown, "scenes", None):
                for scene in scene_breakdown.scenes:
                    for field in (
                        "required_end_hook",
                        "opponent_move",
                        "failure_event_if_no_action",
                        "pov_countermove",
                        "turn",
                        "consequences",
                    ):
                        value = getattr(scene, field, "")
                        if isinstance(value, str) and value.strip():
                            anchors.append(value.strip())

        # Dedupe while preserving order.
        deduped: list[str] = []
        seen: set[str] = set()
        for item in anchors:
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _span_anchor_hits(span: str, anchors: list[str]) -> list[str]:
        """Return protected anchors that overlap with span text."""
        span_l = span.lower()
        hits: list[str] = []
        for anchor in anchors:
            tokens = [t for t in anchor.lower().split() if len(t) >= 4]
            if not tokens:
                continue
            # Consider anchor "present" when at least two meaningful tokens overlap.
            overlap = sum(1 for tok in tokens[:10] if tok in span_l)
            if overlap >= 2:
                hits.append(anchor)
        return hits

    def _semantic_anchor_violation(
        self,
        *,
        system_prompt: str,
        original_span: str,
        rewritten_span: str,
        anchor_hits: list[str],
    ) -> tuple[bool, str]:
        """Model-assisted semantic guard for protected-anchor integrity."""
        if not anchor_hits:
            return False, ""

        prompt = "\n\n".join(
            [
                "Evaluate whether the rewritten text changes the semantic meaning",
                "of protected anchor evidence from the original text.",
                "Return JSON ONLY with this schema:",
                '{"violation": <bool>, "reason": "<string>"}',
                "",
                "Protected anchors:",
                *[f"- {a}" for a in anchor_hits[:6]],
                "",
                "Original span:",
                original_span,
                "",
                "Rewritten span:",
                rewritten_span,
            ]
        )
        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=prompt,
            model=getattr(self.config, "smart_repetition_model_judge", self.config.model_revision_polish),
            temperature=0.0,
            max_tokens=256,
        )
        payload = self._parse_repetition_judge_json(response.content)
        if not payload:
            return True, "anchor_check_malformed"
        return bool(payload.get("violation", False)), str(payload.get("reason", "")).strip()

    def _persist_smart_repetition_artifact(
        self, ch_num: int, artifact: dict, artifact_path=None
    ) -> None:
        path = (
            artifact_path
            if artifact_path is not None
            else (
                self.state_manager.project_dir
                / "state"
                / "quality_reports"
                / f"chapter_{ch_num:02d}_smart_repetition.json"
            )
        )
        self.state_manager._write_json(path, artifact)

    def _run_smart_repetition_pass(
        self,
        *,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        chapter_outline,
        structure,
        persist_artifact: bool = True,
        artifact_path=None,
    ) -> str:
        """Run critic -> editor -> judge targeted repetition pass."""
        blocks = chapter_content.split("\n\n")
        para_map = self._build_paragraph_index_map(blocks)
        if len(para_map) < 3:
            return chapter_content
        logical_paragraphs = {
            para_idx: blocks[block_idx]
            for para_idx, block_idx in para_map.items()
        }
        repetition_findings = detect_within_chapter_repetition(chapter_content)
        detector_targets = self._detect_repetition_targets_for_paragraphs(
            logical_paragraphs,
            repetition_findings[:20],
        )
        repetition_report = format_repetition_report(repetition_findings)

        anchors = self._extract_protected_anchors(
            ch_num=ch_num,
            chapter_outline=chapter_outline,
            structure=structure,
        )
        chapter_outline_dict = chapter_outline.model_dump() if chapter_outline else {}
        retry_limit = max(int(getattr(self.config, "smart_repetition_retry_limit", 2)), 0)

        critic_prompt = self.prompts.render_revision(
            "repetition_critic",
            chapter_number=ch_num,
            chapter_outline=chapter_outline_dict,
            chapter_content=chapter_content,
            protected_anchors=anchors,
            max_findings=int(getattr(self.config, "smart_repetition_max_critic_findings", 10)),
            detector_repetition_report=repetition_report,
            detector_repetition_targets=detector_targets,
        )

        critic_findings: list[dict] = []
        critic_tokens = 0
        critic_cost = 0.0
        for _ in range(retry_limit + 1):
            critic_response = self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=critic_prompt,
                model=getattr(self.config, "smart_repetition_model_critic", self.config.model_revision_polish),
                temperature=0.2,
                max_tokens=4096,
            )
            critic_tokens += int(critic_response.input_tokens) + int(critic_response.output_tokens)
            critic_cost += float(critic_response.cost_estimate)
            parsed = self._parse_repetition_critic_json(critic_response.content)
            if parsed is not None:
                critic_findings = parsed
                break

        max_findings = int(getattr(self.config, "smart_repetition_max_critic_findings", 10))
        max_paras = int(getattr(self.config, "smart_repetition_max_paragraphs", 6))
        findings = critic_findings[:max_findings]
        if not findings:
            artifact = {
                "chapter_number": ch_num,
                "status": "no_findings_or_parse_failure",
                "critic_findings_count": 0,
                "accepted_edits_count": 0,
                "rejected_edits_count": 0,
                "cost": {
                    "critic_tokens": critic_tokens,
                    "critic_cost_estimate": round(critic_cost, 6),
                },
                "detector_repetition_targets": detector_targets[:12],
            }
            self._last_smart_repetition_artifact = artifact
            if persist_artifact:
                self._persist_smart_repetition_artifact(
                    ch_num, artifact, artifact_path=artifact_path
                )
            return chapter_content

        accepted = []
        rejected = []
        edited_paragraphs = 0
        total_editor_tokens = 0
        total_judge_tokens = 0
        total_editor_cost = 0.0
        total_judge_cost = 0.0

        for idx, finding in enumerate(findings, start=1):
            if edited_paragraphs >= max_paras:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "paragraph_budget_exhausted",
                        "finding": finding,
                    }
                )
                continue

            start_para = int(finding.get("start_paragraph", -1))
            end_para = int(finding.get("end_paragraph", -1))
            if start_para not in para_map or end_para not in para_map:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "paragraph_index_out_of_range",
                        "finding": finding,
                    }
                )
                continue

            start_block = para_map[start_para]
            end_block = para_map[end_para]
            if end_block < start_block:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "invalid_span_bounds",
                        "finding": finding,
                    }
                )
                continue

            original_span = "\n\n".join(blocks[start_block : end_block + 1])
            anchor_hits = self._span_anchor_hits(original_span, anchors)
            span_target_keys = self._target_pattern_keys_for_span(
                start_para,
                end_para,
                detector_targets,
            )
            enriched_finding = dict(finding)
            if span_target_keys:
                enriched_finding["target_pattern_keys"] = span_target_keys
            window = max(int(getattr(self.config, "smart_repetition_anchor_window_paragraphs", 1)), 0)
            ctx_start = max(0, start_block - window)
            ctx_end = min(len(blocks), end_block + window + 1)
            context_before = "\n\n".join(blocks[ctx_start:start_block])
            context_after = "\n\n".join(blocks[end_block + 1 : ctx_end])

            editor_prompt = self.prompts.render_revision(
                "repetition_editor",
                chapter_number=ch_num,
                chapter_outline=chapter_outline_dict,
                finding=enriched_finding,
                original_span=original_span,
                context_before=context_before,
                context_after=context_after,
                protected_anchors=anchors,
                anchor_hits=anchor_hits,
                target_pattern_keys=span_target_keys,
            )

            editor_payload = None
            editor_response = None
            for _ in range(retry_limit + 1):
                editor_response = self.llm.generate(
                    system_prompt=system_prompt,
                    user_prompt=editor_prompt,
                    model=getattr(self.config, "smart_repetition_model_editor", self.config.model_revision_polish),
                    temperature=self.config.temperature_revision,
                    max_tokens=2048,
                )
                total_editor_tokens += int(editor_response.input_tokens) + int(editor_response.output_tokens)
                total_editor_cost += float(editor_response.cost_estimate)
                editor_payload = self._parse_repetition_editor_json(editor_response.content)
                if editor_payload is not None:
                    break
            if not editor_payload:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "editor_payload_malformed",
                        "finding": finding,
                    }
                )
                continue

            rewritten_span = str(editor_payload.get("rewritten_span", "")).strip()
            replacement_blocks = rewritten_span.split("\n\n")
            original_block_count = (end_block - start_block + 1)
            if len(replacement_blocks) != original_block_count:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "editor_changed_span_block_count",
                        "finding": finding,
                    }
                )
                continue

            judge_prompt = self.prompts.render_revision(
                "repetition_judge",
                chapter_number=ch_num,
                chapter_outline=chapter_outline_dict,
                finding=enriched_finding,
                original_span=original_span,
                rewritten_span=rewritten_span,
                protected_anchors=anchors,
                anchor_hits=anchor_hits,
                target_pattern_keys=span_target_keys,
            )
            judge_payload = None
            for _ in range(retry_limit + 1):
                judge_response = self.llm.generate(
                    system_prompt=system_prompt,
                    user_prompt=judge_prompt,
                    model=getattr(self.config, "smart_repetition_model_judge", self.config.model_revision_polish),
                    temperature=0.0,
                    max_tokens=1024,
                )
                total_judge_tokens += int(judge_response.input_tokens) + int(judge_response.output_tokens)
                total_judge_cost += float(judge_response.cost_estimate)
                judge_payload = self._parse_repetition_judge_json(judge_response.content)
                if judge_payload is not None:
                    break

            if not judge_payload:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "judge_payload_malformed",
                        "finding": finding,
                    }
                )
                continue

            decision = str(judge_payload.get("decision", "reject")).strip().lower()
            confidence = float(judge_payload.get("confidence", 0.0) or 0.0)
            fidelity_ok = bool(judge_payload.get("fidelity_ok", False))
            min_conf = float(getattr(self.config, "smart_repetition_judge_min_confidence", 0.75))
            required_conf = min_conf + (0.10 if anchor_hits else 0.0)

            if anchor_hits:
                violation, reason = self._semantic_anchor_violation(
                    system_prompt=system_prompt,
                    original_span=original_span,
                    rewritten_span=rewritten_span,
                    anchor_hits=anchor_hits,
                )
                if violation:
                    fidelity_ok = False
                    judge_payload["anchor_violation_reason"] = reason

            should_accept = (
                decision == "accept"
                and confidence >= required_conf
                and fidelity_ok
            )
            effectiveness_before = 0
            effectiveness_after = 0
            if should_accept and bool(
                getattr(self.config, "smart_repetition_require_effective_reduction", True)
            ):
                target_keys = set(span_target_keys)
                before_repetitions = detect_within_chapter_repetition(original_span)
                after_repetitions = detect_within_chapter_repetition(rewritten_span)
                effectiveness_before = self._repetition_burden(
                    before_repetitions,
                    target_keys if target_keys else None,
                )
                effectiveness_after = self._repetition_burden(
                    after_repetitions,
                    target_keys if target_keys else None,
                )
                if effectiveness_before > 0 and effectiveness_after >= effectiveness_before:
                    should_accept = False
                    judge_payload["effectiveness_rejection_reason"] = (
                        "no_measurable_repetition_reduction"
                    )
                    judge_payload["effectiveness_before"] = effectiveness_before
                    judge_payload["effectiveness_after"] = effectiveness_after
            if not should_accept and str(getattr(self.config, "smart_repetition_tiebreak_mode", "conservative_keep_original")) != "conservative_keep_original":
                # Non-conservative mode remains opt-in; default behavior keeps original.
                should_accept = False

            logger.info(
                "Smart repetition span decision chapter=%d span=%d decision=%s confidence=%.3f anchor_hits=%d",
                ch_num,
                idx,
                decision,
                confidence,
                len(anchor_hits),
            )

            if should_accept:
                blocks[start_block : end_block + 1] = replacement_blocks
                edited_paragraphs += max((end_para - start_para + 1), 1)
                accepted.append(
                    {
                        "finding_index": idx,
                        "finding": enriched_finding,
                        "anchor_hits": anchor_hits,
                        "target_pattern_keys": span_target_keys,
                        "judge": judge_payload,
                        "effectiveness_before": effectiveness_before,
                        "effectiveness_after": effectiveness_after,
                        "before": original_span,
                        "after": rewritten_span,
                    }
                )
            else:
                rejected.append(
                    {
                        "finding_index": idx,
                        "reason": "judge_rejected_or_low_confidence",
                        "finding": enriched_finding,
                        "target_pattern_keys": span_target_keys,
                        "judge": judge_payload,
                    }
                )

        revised_content = "\n\n".join(blocks)
        artifact = {
            "chapter_number": ch_num,
            "status": "completed",
            "critic_findings_count": len(findings),
            "accepted_edits_count": len(accepted),
            "rejected_edits_count": len(rejected),
            "accepted_edits": accepted,
            "rejected_edits": rejected,
            "detector_repetition_targets": detector_targets[:12],
            "cost": {
                "critic_tokens": critic_tokens,
                "editor_tokens": total_editor_tokens,
                "judge_tokens": total_judge_tokens,
                "total_tokens": critic_tokens + total_editor_tokens + total_judge_tokens,
                "critic_cost_estimate": round(critic_cost, 6),
                "editor_cost_estimate": round(total_editor_cost, 6),
                "judge_cost_estimate": round(total_judge_cost, 6),
                "total_cost_estimate": round(critic_cost + total_editor_cost + total_judge_cost, 6),
            },
        }
        self._last_smart_repetition_artifact = artifact
        if persist_artifact:
            self._persist_smart_repetition_artifact(
                ch_num, artifact, artifact_path=artifact_path
            )
        return revised_content

    def run_smart_repetition_on_text(
        self,
        *,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        chapter_outline=None,
        structure=None,
        persist_artifact: bool = False,
        artifact_path=None,
    ) -> tuple[str, dict]:
        """Run smart repetition pass on arbitrary chapter text.

        This adapter intentionally avoids full Stage 5 orchestration and is useful
        for experimentation workflows that operate on copied chapter files.
        """
        revised = self._run_smart_repetition_pass(
            ch_num=ch_num,
            chapter_content=chapter_content,
            system_prompt=system_prompt,
            chapter_outline=chapter_outline,
            structure=structure,
            persist_artifact=persist_artifact,
            artifact_path=artifact_path,
        )
        artifact = getattr(self, "_last_smart_repetition_artifact", {}) or {}
        return revised, artifact

    @staticmethod
    def _build_ending_retry_context(
        ending_deficit: dict,
        ending_mode: str,
        strict_template: bool = False,
    ) -> str:
        """Build focused retry instructions for ending-only polish.

        When ``strict_template=True`` (fallback path after normal retries
        exhausted), adds an unambiguous behavioral contract that denies
        reflective deceleration unless an active external consequence is present.
        """
        base = format_low_propulsion_endings_report(ending_deficit)
        mode_line = (
            f"- Target ending mode: {ending_mode}"
            if ending_mode
            else "- Target ending mode: unresolved external pressure (no reflective deceleration)"
        )
        lines = [
            "## ENDING-ONLY RETRY DIRECTIVE (MANDATORY)",
            "",
            base,
            "",
            "Rewrite ONLY the final 250-400 words of the chapter.",
            "Preserve everything before that boundary unless continuity requires a minimal bridge sentence.",
            mode_line,
            "Ensure the final beat introduces unresolved external pressure that compels immediate continuation.",
            "Mandatory ending elements:",
            "- Include at least one concrete external-action marker in the final 120 words (arrival, vote, deadline, knock, order, departure, opening door, ambush, summons, accusation, forced choice).",
            "- Leave that pressure unresolved at cut-off; do not resolve or summarize.",
            "- Avoid reflective deceleration terms in the last paragraph (thought, wondered, reflected, alone, quiet, contemplated, mused).",
            "- Do not reuse stock urgency templates already present earlier in the chapter.",
        ]
        if strict_template:
            lines += [
                "",
                "## STRICT ENDING CONTRACT (ENFORCED — previous attempts failed)",
                "",
                "REQUIRED: The final ~150 words MUST contain at least one of these unresolved external force markers:",
                "  deadline (a specific time or event boundary), threat (explicit danger to a named person or goal),",
                "  opposition move (an antagonist or rival takes visible action), irreversible commitment (a decision",
                "  that cannot be undone), or immediate action window (a narrow time slot forcing instant response).",
                "",
                "FORBIDDEN unless an active external consequence is simultaneously present:",
                "  - Pure reflection (the POV character alone, thinking, feeling, not acting or being acted upon)",
                "  - Stillness as the final image (an empty room, a character staring into distance, silence)",
                "  - Summary prose that recaps what just happened without adding forward pressure",
                "  - Introspective questions ('Would it be enough?', 'What had he done?') as the final beat",
                "",
                "If the existing scene cannot be extended with genuine external pressure, END the chapter on a",
                "concrete action beat mid-motion (a character leaving, arriving, speaking a decisive line, or",
                "receiving news) — NOT on their reaction or inner state.",
            ]
        return "\n".join(lines)

    def _targeted_dedup_pass(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
    ) -> str:
        """Paragraph-level dedup surgery for chapters exceeding the soft cap.

        Uses the repetition payload from ``build_quality_snapshot`` to identify
        hot paragraphs, then rewrites only those paragraphs — preserving scene
        boundaries, factual claims, and turn outcomes.  All other paragraphs are
        copied verbatim to minimise regression surface area.
        """
        snapshot = build_quality_snapshot(chapter_content)
        raw_reps = snapshot.get("raw", {}).get("repetition", [])

        if not raw_reps:
            logger.info("Chapter %d: dedup pass — no repetition patterns found, skipping", ch_num)
            return chapter_content

        # Identify the top repeated patterns (most frequent first)
        sorted_reps = sorted(raw_reps, key=lambda r: r.get("count", 0), reverse=True)
        top_patterns = [r["pattern"] for r in sorted_reps[:8]]
        patterns_text = "\n".join(f'- "{p}" ({sorted_reps[i].get("count", "?")}x)' for i, p in enumerate(top_patterns))

        paragraphs = chapter_content.split("\n\n")

        # Flag paragraphs that contain at least one top repeated pattern
        def _para_has_repetition(para: str) -> bool:
            lower = para.lower()
            return any(p.lower() in lower for p in top_patterns)

        flagged_indices = [
            i for i, para in enumerate(paragraphs)
            if para.strip() and para.strip() != "---" and _para_has_repetition(para)
        ]

        if not flagged_indices:
            return chapter_content

        console.print(
            f"    [cyan]Dedup-first pass: {len(flagged_indices)} paragraph(s) flagged "
            f"across {len(paragraphs)} total — patching repetitive paragraphs[/cyan]"
        )

        for idx in flagged_indices:
            original_para = paragraphs[idx]
            context_before = "\n\n".join(paragraphs[max(0, idx - 2) : idx])
            context_after = "\n\n".join(
                paragraphs[idx + 1 : min(len(paragraphs), idx + 3)]
            )

            patch_prompt = "\n\n".join([
                f"## DEDUP PATCH — Paragraph {idx + 1}",
                "",
                "The paragraph below contains one or more of these over-repeated patterns:",
                "",
                patterns_text,
                "",
                "**Instructions:**",
                "- Replace each instance of the repeated pattern with a varied alternative.",
                "- Preserve all factual content, scene boundaries (`---`), character names, and turn outcomes.",
                "- Do NOT add new plot events or change what happens.",
                "- Match the original prose style and POV voice.",
                "- The replacement must have a similar word count to the original.",
                "- Output ONLY the rewritten paragraph — no commentary, no headers.",
                "---",
                "### Preceding context (do NOT rewrite)",
                context_before,
                "---",
                "### Paragraph to rewrite",
                original_para,
                "---",
                "### Following context (do NOT rewrite)",
                context_after,
            ])

            response = self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=patch_prompt,
                model=self.config.model_revision_creative,
                temperature=self.config.temperature_revision,
                max_tokens=1024,
            )
            paragraphs[idx] = response.content.strip()

        deduped = "\n\n".join(paragraphs)

        # Non-regression check: if repetition worsened somehow, fall back
        delta = compute_quality_delta(chapter_content, deduped)
        rep_regressions = [
            r for r in delta.get("regressions", [])
            if r["metric"] == "repetition_patterns"
        ]
        if rep_regressions:
            logger.warning(
                "Chapter %d: dedup pass introduced repetition regression — retrying from pre-dedup input",
                ch_num,
            )
            console.print(
                "    [yellow]Dedup pass worsened repetition — retrying with repetition-specific context[/yellow]"
            )
            rep_context = "\n".join([
                "## REPETITION REGRESSION CORRECTION (MANDATORY)",
                "",
                "The previous dedup attempt WORSENED repetition patterns.",
                "Specifically eliminate every instance of the following patterns (keep only 1 per chapter):",
                "",
                patterns_text,
                "",
                "Rewrite only the paragraphs that contain these patterns.",
                "Preserve scene boundaries, factual content, and turn outcomes.",
                "Output the full chapter with only the patched paragraphs changed.",
            ])
            retry_response = self.llm.generate_streaming(
                system_prompt=system_prompt,
                user_prompt=rep_context + "\n\n## CHAPTER\n\n" + chapter_content,
                model=self.config.model_revision_polish,
                temperature=self.config.temperature_revision,
                max_tokens=self.config.max_tokens_per_call,
            )
            return retry_response.content

        return deduped

    @staticmethod
    def _build_exposition_momentum_macro(delta: dict) -> str:
        """Build a momentum-recovery macro for exposition-drag regression retries.

        Injected into the combined audit context when exposition_drag_runs
        worsened after a revision pass.  Provides concrete structural guidance
        for converting static exposition into active scene beats.
        """
        drag_regressions = [
            r for r in delta.get("regressions", [])
            if r["metric"] == "exposition_drag_runs"
        ]
        before = drag_regressions[0].get("before", "?") if drag_regressions else "?"
        after = drag_regressions[0].get("after", "?") if drag_regressions else "?"
        return "\n".join([
            "## EXPOSITION MOMENTUM RECOVERY (MANDATORY)",
            "",
            f"Exposition-drag runs worsened from {before} to {after} during this pass.",
            "The retry MUST NOT replace action with summary prose.",
            "",
            "For each detected exposition-drag run, apply this conversion pattern:",
            "",
            "  1. **Ask → Deny → Pressure → Countermove**",
            "     - Ask: a character wants or needs something specific.",
            "     - Deny: an opposing force (person, rule, circumstance) blocks them ON PAGE.",
            "     - Pressure: the denial has a concrete cost or deadline.",
            "     - Countermove: the POV character responds with a visible action, not a thought.",
            "",
            "  2. Force at least one on-page opposing action per flagged drag run.",
            "     An opponent must DO something (speak, move, refuse, produce a document)",
            "     — not merely be reported as having done something off-page.",
            "",
            "  3. Prohibit replacing cut exposition with equivalent summary prose.",
            "     If you compress a 3-paragraph backstory block, replace it with a",
            "     single concrete sensory detail or a character action, not a 1-paragraph",
            "     narrative summary of the same information.",
        ])

    @staticmethod
    def _build_jeopardy_recovery_macro(delta: dict, chapter_text: str = "") -> str:
        """Build a jeopardy-recovery macro for pass-regression retries.

        Injected into the combined audit context when
        immediate_jeopardy_deficit_scenes worsened after a revision pass.
        Provides concrete scene-indexed directives for injecting on-page
        opponent presence and consequence language.
        """
        jeopardy_regressions = [
            r for r in delta.get("regressions", [])
            if r["metric"] == "immediate_jeopardy_deficit_scenes"
        ]
        before = jeopardy_regressions[0].get("before", "?") if jeopardy_regressions else "?"
        after = jeopardy_regressions[0].get("after", "?") if jeopardy_regressions else "?"

        lines = [
            "## IMMEDIATE JEOPARDY RECOVERY (MANDATORY)",
            "",
            f"Immediate-jeopardy deficit scenes worsened from {before} to {after} during this pass.",
            "The retry MUST surface a concrete on-page threat before each failing scene ends.",
            "",
        ]

        # Attempt to identify specific failing scenes from the chapter text
        if chapter_text:
            failing_scenes = detect_low_immediate_jeopardy(chapter_text)
            if failing_scenes:
                lines.append("Scenes requiring jeopardy injection:")
                lines.append("")
                for item in failing_scenes[:6]:
                    scene_num = item["scene_number"]
                    risk = item["risk_hits"]
                    consequence = item["consequence_hits"]
                    preview = item.get("preview", "")
                    lines.append(
                        f"- **Scene {scene_num}**: risk markers={risk}, "
                        f"consequence verbs={consequence}"
                    )
                    if preview:
                        lines.append(f'  Starts with: "{preview[:100].strip()}..."')
                    lines.append(
                        f"  REQUIRED: the opponent must appear ON PAGE in scene {scene_num} "
                        "and perform a concrete blocking action (speak, refuse, produce "
                        "a document, physically intervene) BEFORE the scene ends."
                    )
                    lines.append("")

        lines.extend([
            "Mandatory repair pattern for each flagged scene:",
            "",
            "  1. **Immediate risk**: state the specific, concrete thing that will be lost",
            "     or destroyed if the protagonist does not act NOW — name the cost explicitly.",
            "",
            "  2. **On-page opponent**: an opposing actor must be present IN THE SCENE,",
            "     not merely referenced or remembered. They must DO something visible",
            "     (speak, move, withhold, threaten) — not merely exist off-stage.",
            "",
            "  3. **Consequence verb**: the scene must contain language that makes",
            "     the irreversible cost explicit (lose, forfeit, destroy, condemn,",
            "     cannot recover, no second chance, too late).",
            "",
            "Hard prohibitions:",
            "- Do NOT replace missing jeopardy with abstract risk language",
            "  ('the stakes were high', 'the situation was precarious').",
            "- Do NOT move the opponent off-stage into reported action.",
            "- Do NOT compress a flagged scene — only inject, do not remove prose.",
        ])
        return "\n".join(lines)

    @staticmethod
    def _build_targeted_exposition_macro(drag_findings: list[dict]) -> str:
        """Build a targeted drag-correction macro referencing specific paragraph locations.

        Used when the first regression retry did not reduce exposition drag.
        Unlike the general momentum macro, this names the exact paragraph
        ranges and provides a preview so the LLM can locate and rewrite the
        specific blocks rather than applying global stylistic changes.
        """
        lines = [
            "## TARGETED EXPOSITION DRAG CORRECTION (MANDATORY — SECOND ATTEMPT)",
            "",
            "The previous retry did NOT reduce exposition drag. A second targeted",
            "correction is required for the specific paragraph ranges listed below.",
            "Do NOT make global stylistic changes — rewrite ONLY the flagged blocks.",
            "",
            "For each flagged range, apply the ask→deny→pressure→countermove pattern:",
            "  • Ask: a character wants something specific.",
            "  • Deny: an on-page force (person, rule, circumstance) blocks them.",
            "  • Pressure: the denial has a concrete cost or deadline.",
            "  • Countermove: the POV character responds with a visible action.",
            "",
            "Flagged exposition blocks to rewrite:",
            "",
        ]
        for item in drag_findings[:6]:
            lines.append(
                f"- **Paragraphs {item['start_para']}–{item['end_para']}** "
                f"({item['paragraph_count']} consecutive exposition paragraphs)"
            )
            preview = item.get("preview", "")
            if preview:
                lines.append(f'  Starts with: "{preview[:100].strip()}..."')
            lines.append(
                "  REQUIRED: introduce at least one on-page adversarial action "
                "(dialogue, refusal, confrontation) before this block ends."
            )
            lines.append("")
        lines.extend([
            "Hard constraints:",
            "- Each rewritten block must contain dialogue or a concrete action verb.",
            "- An opponent or obstacle must act visibly — not merely be reported.",
            "- Do NOT replace cut exposition with equivalent narrative summary.",
        ])
        return "\n".join(lines)

    def _rewrite_ending_only(
        self,
        chapter_content: str,
        system_prompt: str,
        retry_context: str,
    ) -> str:
        """Rewrite only the final ~400 words to fix ending propulsion.

        Splits the chapter at the nearest paragraph boundary before the last
        ~400 words, sends only the ending segment to the LLM, and splices the
        rewritten ending back onto the preserved body.  This avoids the cost
        (~$0.15-0.20) and regression risk of rewriting the full chapter just
        to fix the ending.
        """
        words = chapter_content.split()
        # Work backwards ~400 words to find a clean paragraph split
        split_word_target = max(0, len(words) - 400)
        # Reconstruct the approximate character position of that word boundary
        body_approximate = " ".join(words[:split_word_target])
        last_para_break = body_approximate.rfind("\n\n")
        # Only use the paragraph break if it's within the last 600 chars of body
        if last_para_break >= 0 and last_para_break > len(body_approximate) - 600:
            split_idx = last_para_break + 2  # keep the blank line with body
        else:
            # Fall back to the word-boundary split
            split_idx = len(body_approximate)

        body = chapter_content[:split_idx].rstrip()
        ending = chapter_content[split_idx:].lstrip()

        # Provide the last ~800 chars of body as continuity context
        body_context_tail = body[-800:] if len(body) > 800 else body

        user_prompt = "\n\n".join([
            "## ENDING-ONLY REWRITE",
            "",
            retry_context,
            "---",
            "## CONTEXT — preceding body (do NOT rewrite this section)",
            "",
            body_context_tail,
            "---",
            "## ENDING TO REWRITE (rewrite ONLY the text below this line)",
            "",
            ending,
            "---",
            "Output ONLY the rewritten ending. Maintain narrative continuity "
            "with the body context above. Do not repeat sentences from the "
            "body. Do not add commentary or section headers.",
        ])

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_revision_polish,
            temperature=self.config.temperature_revision,
            max_tokens=2048,
        )

        rewritten_ending = response.content.strip()
        return body + "\n\n" + rewritten_ending

    def _apply_ending_propulsion_retries(
        self,
        final_content: str,
        chapter_outline,
        system_prompt: str,
        ch_num: int,
    ) -> str:
        """Run deterministic ending-only retries until propulsion passes or retries exhaust."""
        ending_deficit = detect_low_propulsion_endings(final_content)
        if not ending_deficit:
            return final_content

        ending_mode = (
            chapter_outline.ending_mode
            if chapter_outline and getattr(chapter_outline, "ending_mode", "")
            else ""
        )
        console.print(
            "    [yellow]Ending propulsion deficit detected — running targeted ending rewrite[/yellow]"
        )
        self.state_manager.save_chapter_draft(
            ch_num, final_content, "v3_polish_pre_ending_retry"
        )
        max_ending_retries = max(int(getattr(self.config, "gate_max_ending_retries", 2)), 1)
        current = final_content
        for retry in range(1, max_ending_retries + 1):
            retry_context = self._build_ending_retry_context(
                ending_deficit=ending_deficit,
                ending_mode=ending_mode,
                strict_template=False,
            )
            current = self._rewrite_ending_only(
                chapter_content=current,
                system_prompt=system_prompt,
                retry_context=retry_context,
            )
            ending_deficit = detect_low_propulsion_endings(current)
            if not ending_deficit and self._ending_has_unresolved_action(current):
                return current
            if retry < max_ending_retries:
                console.print(
                    f"    [yellow]Ending still weak — attempt {retry + 1}/{max_ending_retries}[/yellow]"
                )

        # Strict fallback: one final attempt with the explicit behavioral contract
        ending_deficit_check = detect_low_propulsion_endings(current)
        has_action = self._ending_has_unresolved_action(current)
        if ending_deficit_check or not has_action:
            console.print(
                "    [yellow]Ending still failing after normal retries — "
                "running strict-template fallback[/yellow]"
            )
            logger.warning(
                "Chapter %d: ending propulsion weak after %d retries — strict fallback",
                ch_num, max_ending_retries,
            )
            strict_deficit = ending_deficit_check or {}
            strict_context = self._build_ending_retry_context(
                ending_deficit=strict_deficit,
                ending_mode=ending_mode,
                strict_template=True,
            )
            current = self._rewrite_ending_only(
                chapter_content=current,
                system_prompt=system_prompt,
                retry_context=strict_context,
            )
        final_deficit = detect_low_propulsion_endings(current)
        if final_deficit or not self._ending_has_unresolved_action(current):
            self._maybe_fail_contract(
                ch_num,
                "Ending propulsion gate failed after all retries.",
                error_code="ending_propulsion_failed",
            )
        return current

    def _apply_revision_ending_final_check(
        self,
        final_content: str,
        chapter_outline,
        system_prompt: str,
        ch_num: int,
        version: str,
    ) -> str:
        """Guarantee a propulsive ending after all compression passes are complete.

        Runs ending-propulsion retries on ``final_content``, then persists
        the result as ``version`` (v3_polish) so the draft on disk always
        reflects the post-ending-fix content.  No further compression is
        applied afterward — this is the terminal step for the polish pass.
        """
        final_content = self._apply_ending_propulsion_retries(
            final_content=final_content,
            chapter_outline=chapter_outline,
            system_prompt=system_prompt,
            ch_num=ch_num,
        )
        self.state_manager.save_chapter_draft(ch_num, final_content, version)
        return final_content

    @staticmethod
    def _ending_has_unresolved_action(chapter_content: str) -> bool:
        """Heuristic: last ~150 words must contain at least one unresolved external force.

        Returns False (insufficient propulsion) if the ending contains only
        reflective/internal content with no external action markers.
        """
        ending_words = chapter_content.lower().split()[-150:]
        ending_text = " ".join(ending_words)

        # Expanded set: deadlines, threats, opposition moves, commitments, action windows
        action_markers = (
            "before", "until", "unless", "deadline", "vote", "arrived",
            "opened", "summoned", "dawn", "morning", "tomorrow", "now",
            "announced", "ordered", "demanded", "threatened", "warned",
            "entered", "burst", "stepped", "returned", "left", "departed",
            "signed", "refused", "denied", "arrested", "charged", "blocked",
            "delivered", "handed", "sent", "received", "read", "heard",
            "must", "will not", "cannot", "forces", "requires", "compels",
            "immediately", "tonight", "midnight", "hour", "minutes",
            "ambush", "attack", "shot", "struck", "seized", "grabbed",
        )
        has_action = any(marker in ending_text for marker in action_markers)

        # Penalise pure-reflection endings
        reflection_markers = (
            "thought", "wondered", "reflected", "remembered", "alone",
            "quiet", "silence", "contemplated", "mused", "considered",
            "realized", "understood", "knew", "felt that", "believed that",
        )
        reflection_count = sum(1 for m in reflection_markers if m in ending_text)

        # Fail if only reflection present with no action markers
        if reflection_count >= 3 and not has_action:
            return False
        return has_action

    def _apply_revision_length_guardrails(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        pass_name: str,
        chapter_outline,
    ) -> str:
        """Constrain revision output length via targeted compression."""
        max_words = max(int(self.config.max_words_per_chapter), 1)
        soft_cap = int(
            max_words * float(getattr(self.config, "revision_soft_cap_ratio", 1.15))
        )
        hard_cap = int(
            max_words * float(getattr(self.config, "revision_hard_cap_ratio", 1.30))
        )
        soft_cap = max(soft_cap, max_words)
        hard_cap = max(hard_cap, soft_cap)
        word_count = len(chapter_content.split())
        if word_count <= soft_cap:
            return chapter_content

        logger.warning(
            "Chapter %d %s pass over soft cap: %d words (soft %d hard %d)",
            ch_num, pass_name, word_count, soft_cap, hard_cap,
        )
        retries = max(int(getattr(self.config, "length_guard_max_retries", 2)), 1)
        current = chapter_content
        best = chapter_content
        best_wc = word_count
        ending_mode = getattr(chapter_outline, "ending_mode", "")
        for _ in range(retries):
            prompt = "\n".join([
                "## REVISION LENGTH GUARDRAIL COMPRESSION (MANDATORY)",
                "",
                f"Current words: {len(current.split())}",
                f"Target words: <= {soft_cap}",
                f"Hard cap: {hard_cap}",
                "",
                "Preserve chapter architecture and scene order.",
                "Do not cut immediate-jeopardy beats or non-visual sensory anchors.",
                "Cut repetition, duplicated interior monologue, and overlong exposition.",
                f"Preserve ending mode: {ending_mode}" if ending_mode else "",
                "",
                "Output only revised chapter markdown.",
                "",
                current,
            ])
            response = self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=prompt,
                model=self.config.model_revision_polish,
                temperature=self.config.temperature_revision,
                max_tokens=4096,
            )
            candidate = response.content
            candidate_wc = len(candidate.split())
            delta = compute_quality_delta(current, candidate)
            harmful = any(
                r["metric"] in {"sensory_deficit_scenes", "immediate_jeopardy_deficit_scenes"}
                for r in delta["regressions"]
            )
            if harmful:
                continue
            current = candidate
            if candidate_wc < best_wc:
                best = candidate
                best_wc = candidate_wc
            if candidate_wc <= soft_cap:
                return candidate

        if best_wc > hard_cap:
            logger.warning(
                "Chapter %d %s pass remains over hard cap (%d > %d)",
                ch_num, pass_name, best_wc, hard_cap,
            )
            self._maybe_fail_contract(
                ch_num,
                f"Revision length hard cap exceeded after retries during {pass_name}: "
                f"{best_wc} > {hard_cap}",
                error_code="revision_length_hard_cap_exceeded",
            )
        return best

    def _critical_regressions(self, delta: dict) -> list[dict]:
        """Return regressions that should trigger pass-level retry."""
        critical_metrics = set(
            getattr(
                self.config,
                "pass_regression_critical_metrics",
                [
                    "repetition_patterns",
                    "sensory_deficit_scenes",
                    "immediate_jeopardy_deficit_scenes",
                ],
            )
        )
        if getattr(self.config, "critical_retry_include_exposition_drag", False):
            critical_metrics.add("exposition_drag_runs")
        threshold = int(getattr(self.config, "pass_regression_delta_threshold", 0))
        return [
            r for r in delta.get("regressions", [])
            if r["metric"] in critical_metrics and int(r.get("delta", 0)) > threshold
        ]

    def _build_gate_escalation_context(self, gate_data: dict) -> str:
        """Build escalation context from Stage 4 gate failures that persisted
        after all retries were exhausted.

        Structural gates (in opus_eligible_gates) are labelled HIGHEST PRIORITY.
        Craft gates are labelled as mandatory fixes but are Sonnet-resolvable.
        """
        retry_count = gate_data.get("retry_count", 0)
        gates = gate_data.get("gates", {})
        failed_gates = {
            name: info for name, info in gates.items()
            if not info.get("passed", True)
        }
        if not failed_gates:
            return ""

        opus_eligible = getattr(
            self.config,
            "opus_eligible_gates",
            ["offstage_opposition", "immediate_jeopardy"],
        )

        structural_failed = {
            name: info for name, info in failed_gates.items()
            if name in opus_eligible
        }
        craft_failed = {
            name: info for name, info in failed_gates.items()
            if name not in opus_eligible
        }

        lines = [
            "## GATE ESCALATION — STAGE 4 FAILURES PERSISTED",
            "",
            f"The following quality gates failed during generation and could "
            f"not be resolved after {retry_count} correction retry(s).",
            "",
        ]

        if structural_failed:
            lines.append(
                "### STRUCTURAL FAILURES (HIGHEST PRIORITY — fix these first):"
            )
            lines.append("")
            for name, info in structural_failed.items():
                report = info.get("report", "")
                if report:
                    lines.append(report)
                    lines.append("")
                else:
                    lines.append(
                        f"- {name}: FAILED (details: {info.get('details', {})})"
                    )

        if craft_failed:
            lines.append(
                "### CRAFT FAILURES (mandatory fixes — resolve through prose revision):"
            )
            lines.append("")
            for name, info in craft_failed.items():
                report = info.get("report", "")
                if report:
                    lines.append(report)
                    lines.append("")
                else:
                    lines.append(
                        f"- {name}: FAILED (details: {info.get('details', {})})"
                    )

        return "\n".join(lines)

    def _persist_quality_artifacts(
        self,
        chapter_number: int,
        v0_content: str,
        polished_content: str,
    ) -> None:
        """Persist per-chapter and aggregate quality metrics artifacts."""
        if not v0_content or not polished_content:
            return

        v0_snapshot = build_quality_snapshot(v0_content)
        polished_snapshot = build_quality_snapshot(polished_content)

        counts_before = v0_snapshot.get("counts", {})
        counts_after = polished_snapshot.get("counts", {})
        deltas = {
            key: counts_after.get(key, 0) - counts_before.get(key, 0)
            for key in sorted(set(counts_before) | set(counts_after))
        }

        chapter_report = {
            "chapter_number": chapter_number,
            "generated_at": datetime.now().isoformat(),
            "v0_raw": v0_snapshot,
            "v3_polish": polished_snapshot,
            "count_deltas": deltas,
        }
        self.state_manager.save_quality_report(chapter_number, chapter_report)
        self._update_quality_aggregate()

    def _update_quality_aggregate(self) -> None:
        """Recompute aggregate quality metrics from all chapter reports."""
        reports = self.state_manager.load_all_quality_reports()
        if not reports:
            return

        total_words_before = 0
        total_words_after = 0
        aggregate_counts_before: dict[str, int] = {}
        aggregate_counts_after: dict[str, int] = {}

        for report in reports.values():
            before = report.get("v0_raw", {})
            after = report.get("v3_polish", {})
            total_words_before += int(before.get("word_count", 0))
            total_words_after += int(after.get("word_count", 0))
            for key, val in before.get("counts", {}).items():
                aggregate_counts_before[key] = aggregate_counts_before.get(key, 0) + int(val)
            for key, val in after.get("counts", {}).items():
                aggregate_counts_after[key] = aggregate_counts_after.get(key, 0) + int(val)

        denom_before_10k = max(total_words_before / 10000.0, 1e-9)
        denom_after_10k = max(total_words_after / 10000.0, 1e-9)

        def _norm(metric: str, counts: dict[str, int], denom: float) -> float:
            return round(counts.get(metric, 0) / denom, 4)

        chapter_count = max(len(reports), 1)

        def _rate(metric: str, counts: dict[str, int]) -> float:
            return round(counts.get(metric, 0) / chapter_count, 4)

        summary = {
            "generated_at": datetime.now().isoformat(),
            "chapters_included": sorted(reports.keys()),
            "chapter_count": chapter_count,
            "totals": {
                "v0_raw_words": total_words_before,
                "v3_polish_words": total_words_after,
                "v0_raw_counts": aggregate_counts_before,
                "v3_polish_counts": aggregate_counts_after,
            },
            "normalized_per_10k_words": {
                "v0_raw": {
                    "immediate_jeopardy_deficit_scenes_per_10k_words": _norm(
                        "immediate_jeopardy_deficit_scenes",
                        aggregate_counts_before,
                        denom_before_10k,
                    ),
                    "exposition_drag_runs_per_10k_words": _norm(
                        "exposition_drag_runs",
                        aggregate_counts_before,
                        denom_before_10k,
                    ),
                    "repetition_patterns_per_10k_words": _norm(
                        "repetition_patterns",
                        aggregate_counts_before,
                        denom_before_10k,
                    ),
                },
                "v3_polish": {
                    "immediate_jeopardy_deficit_scenes_per_10k_words": _norm(
                        "immediate_jeopardy_deficit_scenes",
                        aggregate_counts_after,
                        denom_after_10k,
                    ),
                    "exposition_drag_runs_per_10k_words": _norm(
                        "exposition_drag_runs",
                        aggregate_counts_after,
                        denom_after_10k,
                    ),
                    "repetition_patterns_per_10k_words": _norm(
                        "repetition_patterns",
                        aggregate_counts_after,
                        denom_after_10k,
                    ),
                },
            },
            "flag_rates": {
                "v0_raw": {
                    "ending_propulsion_deficit_flag_rate": _rate(
                        "ending_propulsion_deficit_flag",
                        aggregate_counts_before,
                    ),
                    "offstage_opposition_overuse_flag_rate": _rate(
                        "offstage_opposition_overuse_flag",
                        aggregate_counts_before,
                    ),
                    "dialogue_uniformity_flag_rate": _rate(
                        "dialogue_uniformity_flag",
                        aggregate_counts_before,
                    ),
                },
                "v3_polish": {
                    "ending_propulsion_deficit_flag_rate": _rate(
                        "ending_propulsion_deficit_flag",
                        aggregate_counts_after,
                    ),
                    "offstage_opposition_overuse_flag_rate": _rate(
                        "offstage_opposition_overuse_flag",
                        aggregate_counts_after,
                    ),
                    "dialogue_uniformity_flag_rate": _rate(
                        "dialogue_uniformity_flag",
                        aggregate_counts_after,
                    ),
                },
            },
        }
        self.state_manager.save_quality_aggregate(summary)

    @staticmethod
    def _count_scenes(chapter_content: str) -> int:
        """Count scenes using markdown scene separators."""
        parts = re.split(r"\n\s*---\s*\n", chapter_content)
        return len([p for p in parts if p.strip()])

    def _enforce_structural_non_regression(
        self,
        *,
        ch_num: int,
        pass_name: str,
        source_content: str,
        revised_content: str,
    ) -> str:
        """Prevent destructive structural pass outputs from entering the loop."""
        if pass_name != "structural":
            return revised_content

        source_scenes = self._count_scenes(source_content)
        revised_scenes = self._count_scenes(revised_content)
        if revised_scenes < source_scenes:
            logger.warning(
                "Chapter %d structural pass collapsed scene count (%d -> %d). "
                "Falling back to source draft for this pass.",
                ch_num,
                source_scenes,
                revised_scenes,
            )
            return source_content

        # Structural pass frequently fails by truncation mid-tail, which then
        # cascades into false contract failures in later passes.
        if detect_incomplete_chapter_ending(revised_content):
            logger.warning(
                "Chapter %d structural pass produced truncated/incomplete ending. "
                "Falling back to source draft for this pass.",
                ch_num,
            )
            return source_content

        return revised_content

    def _revise_single_chapter(
        self,
        ch_num: int,
        chapter_content: str,
        pass_info: dict,
        system_prompt: str,
        novel_structure_summary: str,
        world_state,
        structure,
        banned_phrases: list[str],
        quality_audit: str = "",
        is_dedup_retry: bool = False,
        use_opus_structural: bool = False,
    ) -> str:
        """Execute one revision pass on one chapter and save the result."""
        pass_num = pass_info["number"]
        pass_name = pass_info["name"]
        version = pass_info["version"]

        if pass_num <= 1:
            model = (
                self.config.model_revision_structural_opus
                if use_opus_structural
                else self.config.model_revision_structural
            )
        elif pass_num <= 2:
            model = self.config.model_revision_creative
        else:
            model = self.config.model_revision_polish

        chapter_outline = None
        if structure:
            for co in structure.chapter_outlines:
                if co.chapter_number == ch_num:
                    chapter_outline = co
                    break

        extra_kwargs: dict = {}

        # P8: Load original raw draft for restoration awareness across all passes
        v0_raw_content = self.state_manager.load_chapter_draft(ch_num, "v0_raw")
        if v0_raw_content:
            extra_kwargs["original_draft"] = v0_raw_content
            # P0: Compute word count floor (85% of v0_raw, min config floor)
            v0_word_count = len(v0_raw_content.split())
            extra_kwargs["v0_word_count"] = v0_word_count
            extra_kwargs["word_count_floor"] = max(
                int(v0_word_count * 0.85),
                self.config.min_words_per_chapter,
            )

        if pass_name == "polish":
            polished_drafts = self.state_manager.load_all_chapter_drafts("v3_polish")
            other_phrases = []
            for other_num, other_text in polished_drafts.items():
                if other_num != ch_num:
                    other_phrases.extend(self._extract_chapter_phrases(other_text))
            extra_kwargs["banned_phrases"] = banned_phrases
            extra_kwargs["other_chapter_phrases"] = sorted(set(other_phrases))
            # P2: Pass construction-level patterns for structural dedup
            state_dir = self.state_manager.project_dir / "state"
            extra_kwargs["banned_constructions"] = load_banned_constructions(state_dir)

        if pass_name == "voice_and_dialogue" and world_state:
            extra_kwargs["character_profiles"] = [
                c.model_dump() for c in world_state.characters
            ]
            if world_state.era_tone_guide:
                extra_kwargs["era_tone_guide"] = (
                    world_state.era_tone_guide.model_dump()
                )

        if quality_audit:
            extra_kwargs["quality_audit"] = quality_audit

        user_prompt = self.prompts.render_revision(
            pass_name,
            chapter_content=chapter_content,
            chapter_number=ch_num,
            chapter_outline=(
                chapter_outline.model_dump() if chapter_outline else {}
            ),
            novel_structure_summary=novel_structure_summary,
            **extra_kwargs,
        )

        response = self.llm.generate_streaming(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=self.config.temperature_revision,
            max_tokens=self.config.max_tokens_per_call,
        )

        revised_content = response.content
        if getattr(self.config, "enable_length_guardrails", False):
            revised_content = self._apply_revision_length_guardrails(
                ch_num=ch_num,
                chapter_content=revised_content,
                system_prompt=system_prompt,
                pass_name=pass_name,
                chapter_outline=chapter_outline,
            )
        revised_content = self._enforce_structural_non_regression(
            ch_num=ch_num,
            pass_name=pass_name,
            source_content=chapter_content,
            revised_content=revised_content,
        )
        self.state_manager.save_chapter_draft(ch_num, revised_content, version)

        console.print(
            f"    [green]✓ Chapter {ch_num} revised ({pass_name})[/green]"
        )

        return revised_content

    # ------------------------------------------------------------------
    # Batch mode (existing behavior)
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._mark_started()

        try:
            structure = self.state_manager.load_novel_structure()
            world_state = self.state_manager.load_world_state()

            novel_structure_summary = self._build_structure_summary(structure)

            system_prompt = self.prompts.render_system_prompt(
                era_tone_guide=world_state.era_tone_guide if world_state else None
            )

            state_dir = self.state_manager.project_dir / "state"
            banned_phrases = load_banned_phrases(state_dir)

            num_passes = min(self.config.num_revision_passes, len(REVISION_PASSES))

            for pass_info in REVISION_PASSES[:num_passes]:
                pass_num = pass_info["number"]
                pass_name = pass_info["name"]
                version = pass_info["version"]
                focus = pass_info["focus"]

                if pass_num == 1:
                    source_version = "v0_raw"
                else:
                    source_version = REVISION_PASSES[pass_num - 2]["version"]

                existing = self.state_manager.load_all_chapter_drafts(version)
                source_drafts = self.state_manager.load_all_chapter_drafts(
                    source_version
                )

                if existing and len(existing) >= len(source_drafts):
                    logger.info(
                        "Revision pass %d (%s) already complete, skipping",
                        pass_num,
                        pass_name,
                    )
                    continue

                self._update_sub_step(f"revision_pass_{pass_num}_{pass_name}")
                console.print(
                    f"\n[bold cyan]Revision Pass {pass_num}/{num_passes}: "
                    f"{focus}[/bold cyan]"
                )

                chapter_numbers = sorted(source_drafts.keys())

                for ch_num in chapter_numbers:
                    if ch_num in existing:
                        continue

                    chapter_content = source_drafts[ch_num]

                    self._revise_single_chapter(
                        ch_num=ch_num,
                        chapter_content=chapter_content,
                        pass_info=pass_info,
                        system_prompt=system_prompt,
                        novel_structure_summary=novel_structure_summary,
                        world_state=world_state,
                        structure=structure,
                        banned_phrases=banned_phrases,
                    )

                console.print(f"  [green]Pass {pass_num} complete[/green]")

            # C0: Persist quality artifacts for all chapters after batch revision.
            v0_drafts = self.state_manager.load_all_chapter_drafts("v0_raw")
            polished_drafts = self.state_manager.load_all_chapter_drafts("v3_polish")
            for ch_num, v0_text in sorted(v0_drafts.items()):
                polished_text = polished_drafts.get(ch_num)
                if polished_text:
                    self._persist_quality_artifacts(
                        chapter_number=ch_num,
                        v0_content=v0_text,
                        polished_content=polished_text,
                    )

            self._mark_completed()
            console.print(
                "\n[bold green]All revision passes complete![/bold green]"
            )

        except Exception as e:
            self._mark_failed(str(e))
            raise

    # ------------------------------------------------------------------
    # P1: Quality audit
    # ------------------------------------------------------------------

    def _run_quality_audit(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        structure,
    ) -> str:
        """Run a structured quality audit on the v0_raw draft.

        Returns a formatted string to inject into the structural revision prompt.
        """
        chapter_outline = None
        if structure:
            for co in structure.chapter_outlines:
                if co.chapter_number == ch_num:
                    chapter_outline = co
                    break

        scene_registers: dict[int, str] = {}
        if structure:
            for sb in structure.scene_breakdowns:
                if sb.chapter_number == ch_num:
                    for scene in sb.scenes:
                        scene_registers[scene.scene_number] = scene.register
                    break

        pov_character = chapter_outline.pov_character if chapter_outline else "Unknown"

        audit_prompt = self.prompts.render_revision(
            "quality_audit",
            chapter_content=chapter_content,
            chapter_number=ch_num,
            chapter_outline=(
                chapter_outline.model_dump() if chapter_outline else {}
            ),
            pov_character=pov_character,
            scene_registers=scene_registers,
        )

        console.print(f"    [cyan]Running quality audit on chapter {ch_num}...[/cyan]")

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=audit_prompt,
            model=self.config.model_revision_structural,
            temperature=0.3,
            max_tokens=8192,
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                lines = lines[1:] if lines[0].startswith("```") else lines
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)
            try:
                audit_data = json.loads(content)
            except json.JSONDecodeError:
                # Models sometimes prepend commentary; recover the first JSON object.
                extracted = self._extract_first_json_object(content)
                audit_data = json.loads(extracted)
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to parse quality audit JSON for chapter %d", ch_num)
            return ""

        return self._format_audit_for_revision(audit_data)

    @staticmethod
    def _extract_first_json_object(content: str) -> str:
        """Extract the first balanced JSON object from model output."""
        start = content.find("{")
        if start < 0:
            raise json.JSONDecodeError("No JSON object start found", content, 0)

        depth = 0
        in_string = False
        escaped = False
        for idx, ch in enumerate(content[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return content[start : idx + 1]

        raise json.JSONDecodeError(
            "Unbalanced JSON object in model output", content, start
        )

    @staticmethod
    def _format_audit_for_revision(audit_data: dict) -> str:
        """Convert audit JSON into a directive string for the revision prompt."""
        lines = ["## QUALITY AUDIT — MUST FIX", ""]

        scenes = audit_data.get("scenes", [])
        chapter_level = audit_data.get("chapter_level", {})

        for scene in scenes:
            sn = scene.get("scene_number", "?")
            issues = []

            agency = scene.get("pov_agency", {})
            if agency.get("status") == "PASSIVE":
                pct = agency.get("perception_pct", "?")
                issues.append(
                    f"PASSIVE POV ({pct}% perception verbs). "
                    f"Add at least one action where the POV character drives the scene."
                )

            sensory = scene.get("sensory", {})
            if sensory.get("status") == "SENSORY_DEFICIENT":
                senses = sensory.get("distinct_senses", 0)
                issues.append(
                    f"SENSORY DEFICIENT ({senses} senses). "
                    f"Add sensory details from at least 2 different senses."
                )

            dialogue = scene.get("dialogue", {})
            if dialogue.get("status") == "LECTURE":
                issues.append(
                    "LECTURE DIALOGUE. Dialogue is expository — characters deliver "
                    "information without friction. Add disagreement, subtext, or evasion."
                )

            register = scene.get("register", {})
            if register.get("status") == "REGISTER_FLAT":
                assigned = register.get("assigned", "unknown")
                actual = register.get("actual_description", "solemn")
                issues.append(
                    f"REGISTER FLAT. Assigned: {assigned}. Actual: {actual}. "
                    f"Rewrite prose to match the assigned register."
                )

            dupes = scene.get("duplicates", [])
            for d in dupes:
                issues.append(f"DUPLICATE: {d}")

            if issues:
                lines.append(f"**Scene {sn}:**")
                for issue in issues:
                    lines.append(f"- {issue}")
                lines.append("")

        worst = chapter_level.get("worst_issues", [])
        if worst:
            lines.append("**Chapter-level issues:**")
            for w in worst:
                lines.append(f"- {w}")
            lines.append("")

        reg_var = chapter_level.get("overall_register_variation", "")
        if reg_var == "FLAT":
            lines.append(
                "- OVERALL REGISTER VARIATION: FLAT. All scenes read at the same tone. "
                "This must change — vary sentence length, paragraph structure, and "
                "narrative distance to match each scene's assigned register."
            )

        if len(lines) <= 2:
            return ""

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _build_structure_summary(self, structure) -> str:
        """Build a concise structural summary for revision context."""
        if not structure:
            return "No structural information available."

        lines = ["## Novel Structure Summary\n"]

        if structure.act_structure:
            for act in structure.act_structure.acts:
                lines.append(f"### Act {act.act_number}: {act.title}")
                lines.append(f"{act.description}")
                lines.append(f"Stakes: {act.stakes_level}")
                lines.append(f"Chapters: {act.chapters}\n")

        if structure.chapter_outlines:
            lines.append("### Chapter Overview")
            for co in structure.chapter_outlines:
                lines.append(
                    f"- Ch {co.chapter_number}: {co.title} "
                    f"(POV: {co.pov_character}) — {co.chapter_goal}"
                )

        return "\n".join(lines)

    def _extract_chapter_phrases(self, chapter_text: str) -> list[str]:
        """Extract notable phrases from a chapter for cross-chapter dedup."""
        from sovereign_ink.utils.phrase_tracker import extract_notable_phrases

        return extract_notable_phrases(chapter_text)
