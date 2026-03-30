"""Stage 4: Prose Generation — generate novel prose chapter by chapter."""

import logging
import json
import re
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt

from sovereign_ink.pipeline.base import PipelineStage
from sovereign_ink.pipeline.errors import ContractEnforcementError
from sovereign_ink.models import ChapterState, ChapterStateStatus, ContextSummary
from sovereign_ink.models import (
    AdversarialValidationResult,
    AdversarialValidatorResponse,
    ComplianceReport,
    DeterministicValidationResult,
    RequirementResult,
    SceneContractResult,
    SemanticValidationResult,
    SemanticValidatorResponse,
)
from sovereign_ink.utils.phrase_tracker import (
    load_banned_phrases,
    load_banned_constructions,
    update_banned_phrases,
)
from sovereign_ink.utils.text_quality import (
    build_chapter_ending_warning,
    compute_quality_delta,
    detect_incomplete_chapter_ending,
    format_regression_report,
    run_chapter_gates,
    run_chapter_contract_checks,
    run_scene_contract_checks,
    gate_ending_tonal_monotony,
    GateResult,
)

logger = logging.getLogger(__name__)
console = Console()

BASELINE_BANNED_PHRASES = ("particular", "which was")

_GATE_CORRECTION_EXEMPLARS = """
## CORRECTION EXEMPLARS — BEFORE/AFTER

Use these concrete examples to understand the transformation required.

### Offstage Opposition → On-Page Collision

BEFORE (fails gate):
> Word came that Talleyrand had rejected the memorandum. Livingston heard
> through a secretary that France considered the American position
> untenable. Reports suggested that Napoleon was reconsidering.

AFTER (passes gate):
> Talleyrand produced the memorandum from beneath a stack of papers and
> set it on the desk between them. "A creditable effort," he said, "but
> France does not negotiate the sovereignty of its territories on the
> basis of American legal theory." He slid a counter-document across the
> polished surface. Livingston picked it up, read the first paragraph,
> and set it down without finishing. "Then we have nothing further to
> discuss through this channel." He stood.

WHY IT WORKS: The opponent ACTS on page (produces, sets, slides). The POV
RESPONDS with action (picks up, sets down, stands). Conflict is dramatized
through observable behavior, not reported through intermediaries.

### Abstract Jeopardy → Concrete Immediate Risk

BEFORE (fails gate):
> Jefferson considered the constitutional implications of the purchase.
> The question of executive authority weighed on his mind as he thought
> about the future of the republic.

AFTER (passes gate):
> If he did not sign Monroe's commission before the Senate reconvened at
> dawn, Pickering would force a floor vote demanding disclosure of the
> negotiation parameters — and Jefferson had no constitutional answer that
> would survive the afternoon. He reached for the pen.

WHY IT WORKS: A deadline (dawn), a concrete adversarial action (floor vote),
a personal cost (no constitutional answer), and a POV action (reaches for pen).

### Rhythm Monotony → Varied Cadence

BEFORE (fails gate):
> Livingston studied the memorandum with care and noted that the language
> had shifted since the previous draft in ways that suggested a deeper
> strategic recalculation on the part of the French ministry. He understood
> that this recalculation would require him to adjust his own position
> accordingly and to communicate the adjustment to Monroe before the next
> round of discussions began in earnest.

AFTER (passes gate):
> Livingston read the memorandum twice. The language had shifted.
> He set it down. Whatever game Talleyrand was playing, the old rules
> no longer applied — and Monroe would need to know before morning.

WHY IT WORKS: Long analytical sentences are broken by short declarative
ones. Paragraph lengths vary. The reader's eye accelerates and decelerates
with the prose, matching the character's cognitive rhythm.

### Narrator Psychologizing → Externalized Gesture

BEFORE (fails gate):
> He suspected that Talleyrand's offer was not what it appeared to be.
> He was not certain whether the terms concealed a trap or merely
> reflected French indifference. He understood that his response would
> determine the course of the negotiation. He felt that the weight of
> the decision was almost unbearable.

AFTER (passes gate):
> Talleyrand's offer sat on the desk between them. Livingston turned it
> face-down, aligned its edges with the blotter, and looked up without
> reading the final clause. "I will need the evening," he said.

WHY IT WORKS: The narrator stops explaining what the character thinks/
suspects/feels and instead shows the character DOING something that
reveals his state — handling the document with excessive precision,
refusing to finish reading it, buying time with a request. The reader
infers the psychology from behavior.
""".strip()


def _extract_year(time_period: str) -> int | None:
    """Pull the first 4-digit year from a time_period string like 'April 1830'."""
    match = re.search(r"\b(1[0-9]{3})\b", time_period or "")
    return int(match.group(1)) if match else None


def _resolve_major_players(major_players, chapter_year: int | None) -> list[dict]:
    """Build a list of dicts with ``name``, ``role``, and ``current_title`` resolved
    to the chapter's year for passing into the generation prompt."""
    resolved = []
    for mp in major_players:
        current_title = mp.best_title(chapter_year)
        resolved.append({
            "name": mp.name,
            "role": mp.role,
            "current_title": current_title,
        })
    return resolved


def _keywords(text: str) -> set[str]:
    """Extract stable lexical signals from contract text."""
    stop = {
        "the", "and", "that", "with", "from", "this", "have", "will", "into",
        "their", "there", "where", "which", "while", "after", "before", "must",
        "should", "about", "could", "would", "through", "being", "than", "then",
        "they", "them", "been", "were", "your", "ours", "hers", "his", "its",
    }
    return {
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", text or "")
        if len(t) >= 5 and t.lower() not in stop
    }


class ProseGenerationStage(PipelineStage):
    STAGE_NAME = "prose_generation"
    OUTLINE_CRITICAL_ERROR_CODES = {
        "chapter_acceptance_failed",
        "quality_gates_failed",
        "scene_contracts_failed",
        "chapter_convergence_exhausted",
        "completion_gate_failed",
        "ending_variation_failed",
        "deterministic_validation_failed",
        "semantic_validation_failed",
        "adversarial_validation_failed",
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
        error_code: str = "contract_enforcement_failed",
    ) -> None:
        is_critical = error_code in self.OUTLINE_CRITICAL_ERROR_CODES
        if is_critical or self._strict_contract_mode():
            raise ContractEnforcementError(
                message,
                chapter_number=ch_num,
                stage_name=self.STAGE_NAME,
                error_code=error_code,
            )
        logger.warning("Chapter %d non-blocking contract failure: %s", ch_num, message)

    def _save_chapter_state(
        self,
        ch_num: int,
        state: ChapterStateStatus,
        *,
        accepted: bool = False,
        accepted_draft_version: str | None = None,
        last_failures: list[str] | None = None,
        increment_attempt: bool = False,
    ) -> None:
        previous = self.state_manager.load_chapter_state(ch_num) or {}
        attempts = int(previous.get("attempt_count", 0))
        if increment_attempt:
            attempts += 1
        chapter_state = ChapterState(
            chapter_number=ch_num,
            state=state,
            accepted=accepted,
            accepted_draft_version=accepted_draft_version,
            attempt_count=attempts,
            last_failures=list(last_failures or []),
            accepted_at=datetime.now() if accepted else None,
            last_updated_at=datetime.now(),
        )
        self.state_manager.save_chapter_state(ch_num, chapter_state)

    def _structural_failures(
        self,
        chapter_content: str,
        scene_breakdown,
        chapter_outline,
    ) -> list[str]:
        failures: list[str] = []
        if chapter_outline is None:
            failures.append("Missing chapter outline.")
            return failures
        required_chapter_fields = [
            "hard_reveal",
            "soft_reversal",
            "on_page_opposing_move",
            "petty_moment",
            "ending_mode",
        ]
        for field in required_chapter_fields:
            value = (getattr(chapter_outline, field, "") or "").strip()
            if not value:
                failures.append(f"Chapter field '{field}' is empty.")

        if scene_breakdown is None or not getattr(scene_breakdown, "scenes", None):
            failures.append("Missing scene breakdown for chapter.")
            return failures

        scenes_text = self._split_chapter_into_scenes(chapter_content)
        expected = len(scene_breakdown.scenes)
        actual = len(scenes_text)
        scene_count_tolerance = max(
            int(getattr(self.config, "stage4_scene_count_tolerance", 0)),
            0,
        )
        if abs(expected - actual) > scene_count_tolerance:
            failures.append(
                f"Scene count mismatch: expected {expected} scenes, found {actual} scenes in prose."
            )

        for idx, scene in enumerate(scene_breakdown.scenes):
            if scene.scene_number != idx + 1:
                failures.append(
                    f"Scene ordering mismatch in structure: expected scene_number={idx + 1}, "
                    f"found {scene.scene_number}."
                )
            if not (scene.opponent_move or "").strip():
                failures.append(f"Scene {scene.scene_number}: missing opponent_move.")
            if not (scene.pov_countermove or "").strip():
                failures.append(f"Scene {scene.scene_number}: missing pov_countermove.")
            if scene.scene_number == expected and not (scene.required_end_hook or "").strip():
                failures.append(
                    f"Scene {scene.scene_number}: missing required_end_hook for terminal scene."
                )
        return failures

    def _index_evidence_spans(self, chapter_content: str, requirement_results: list[RequirementResult]) -> None:
        chapter_lower = chapter_content.lower()
        for req in requirement_results:
            for ev in req.evidence:
                quote = (ev.quote or "").strip()
                if not quote:
                    continue
                idx = chapter_lower.find(quote.lower())
                if idx >= 0:
                    ev.start_char = idx
                    ev.end_char = idx + len(quote)

    def _run_semantic_contract_validator(
        self,
        ch_num: int,
        chapter_content: str,
        chapter_outline,
        scene_breakdown,
    ) -> SemanticValidationResult:
        if not getattr(self.config, "semantic_validator_enabled", False):
            return SemanticValidationResult(
                passed=True,
                confidence=1.0,
                failures=[],
                requirement_results=[],
                raw_validator="semantic_validator_disabled",
            )

        chapter_beats = {
            "hard_reveal": chapter_outline.hard_reveal,
            "soft_reversal": chapter_outline.soft_reversal,
            "on_page_opposing_move": chapter_outline.on_page_opposing_move,
            "petty_moment": chapter_outline.petty_moment,
            "ending_mode": chapter_outline.ending_mode,
        }
        scene_contracts = [
            {
                "scene_number": s.scene_number,
                "opponent_move": s.opponent_move,
                "pov_countermove": s.pov_countermove,
                "required_end_hook": s.required_end_hook,
            }
            for s in scene_breakdown.scenes
        ] if scene_breakdown else []
        user_prompt = self.prompts.render_validation(
            "semantic_contract",
            chapter_number=ch_num,
            chapter_beats_json=json.dumps(chapter_beats, ensure_ascii=True, indent=2),
            scene_contracts_json=json.dumps(scene_contracts, ensure_ascii=True, indent=2),
            chapter_text=chapter_content,
        )
        try:
            response = self.llm.generate_structured(
                system_prompt=self.prompts.render_system_prompt(),
                user_prompt=user_prompt,
                response_model=SemanticValidatorResponse,
                model=getattr(self.config, "semantic_validator_model", self.config.model_revision_structural),
                temperature=0.0,
                # Keep validator outputs compact and schema-conformant.
                max_tokens=min(self.config.max_tokens_per_call, 3500),
            )
        except Exception as exc:
            logger.warning(
                "Chapter %d semantic validator malformed/truncated output: %s",
                ch_num,
                exc,
            )
            return SemanticValidationResult(
                passed=False,
                confidence=0.0,
                failures=[f"semantic_validator_malformed_output: {exc}"],
                requirement_results=[],
                raw_validator="semantic_validator_malformed_output",
            )
        self._index_evidence_spans(chapter_content, response.requirement_results)
        missing_evidence = [
            r.requirement
            for r in response.requirement_results
            if r.passed and not r.evidence
        ]
        failures = []
        if missing_evidence:
            failures.append(
                f"Missing evidence spans for: {', '.join(missing_evidence)}"
            )
        if response.confidence < float(getattr(self.config, "semantic_confidence_threshold", 0.70)):
            failures.append(
                f"Semantic confidence below threshold ({response.confidence:.2f})"
            )
        passed = bool(response.passed and not failures)
        return SemanticValidationResult(
            passed=passed,
            confidence=response.confidence,
            requirement_results=response.requirement_results,
            failures=failures,
            raw_validator="semantic_validator",
        )

    def _should_trigger_adversarial(
        self,
        deterministic: DeterministicValidationResult,
        semantic: SemanticValidationResult,
    ) -> bool:
        if not getattr(self.config, "adversarial_verifier_enabled", False):
            return False
        trigger = getattr(self.config, "adversarial_trigger", "both")
        if trigger == "never":
            return False
        # "always" runs the adversarial verifier unconditionally, catching
        # missing chapter beats that the semantic validator may have passed.
        if trigger == "always":
            return True
        disagreement = deterministic.passed != semantic.passed
        low_conf = semantic.confidence < float(
            getattr(self.config, "semantic_confidence_threshold", 0.70)
        )
        if trigger == "disagreement":
            return disagreement
        if trigger == "low_confidence":
            return low_conf
        return disagreement or low_conf

    def _run_adversarial_validator(
        self,
        ch_num: int,
        chapter_content: str,
        chapter_outline,
        scene_breakdown,
        deterministic: DeterministicValidationResult,
        semantic: SemanticValidationResult,
    ) -> AdversarialValidationResult:
        if not self._should_trigger_adversarial(deterministic, semantic):
            return AdversarialValidationResult(triggered=False, passed=True, reason="")
        chapter_beats = {
            "hard_reveal": chapter_outline.hard_reveal,
            "soft_reversal": chapter_outline.soft_reversal,
            "on_page_opposing_move": chapter_outline.on_page_opposing_move,
            "petty_moment": chapter_outline.petty_moment,
            "ending_mode": chapter_outline.ending_mode,
        }
        scene_contracts = [
            {
                "scene_number": s.scene_number,
                "opponent_move": s.opponent_move,
                "pov_countermove": s.pov_countermove,
                "required_end_hook": s.required_end_hook,
            }
            for s in scene_breakdown.scenes
        ] if scene_breakdown else []
        user_prompt = self.prompts.render_validation(
            "adversarial_contract",
            chapter_number=ch_num,
            deterministic_json=json.dumps(deterministic.model_dump(), ensure_ascii=True, indent=2),
            semantic_json=json.dumps(semantic.model_dump(), ensure_ascii=True, indent=2),
            chapter_beats_json=json.dumps(chapter_beats, ensure_ascii=True, indent=2),
            scene_contracts_json=json.dumps(scene_contracts, ensure_ascii=True, indent=2),
            chapter_text=chapter_content,
        )
        try:
            response = self.llm.generate_structured(
                system_prompt=self.prompts.render_system_prompt(),
                user_prompt=user_prompt,
                response_model=AdversarialValidatorResponse,
                model=getattr(self.config, "adversarial_verifier_model", self.config.model_revision_structural),
                temperature=0.0,
                max_tokens=min(self.config.max_tokens_per_call, 4096),
            )
        except Exception as exc:
            logger.warning(
                "Chapter %d adversarial validator malformed/truncated output: %s",
                ch_num,
                exc,
            )
            return AdversarialValidationResult(
                triggered=True,
                passed=False,
                reason=f"adversarial_validator_malformed_output: {exc}",
                requirement_results=[],
            )
        self._index_evidence_spans(chapter_content, response.requirement_results)
        return AdversarialValidationResult(
            triggered=True,
            passed=response.passed,
            reason=response.reason,
            requirement_results=response.requirement_results,
        )

    def _evaluate_compliance(
        self,
        ch_num: int,
        chapter_content: str,
        chapter_outline,
        scene_breakdown,
        scene_reports: list[dict] | None = None,
    ) -> ComplianceReport:
        structural_failures = self._structural_failures(
            chapter_content=chapter_content,
            scene_breakdown=scene_breakdown,
            chapter_outline=chapter_outline,
        )
        chapter_contract_result = run_chapter_contract_checks(
            chapter_content, chapter_outline
        )
        deterministic_failures = list(structural_failures)
        if not chapter_contract_result.get("passed", False):
            deterministic_failures.extend(chapter_contract_result.get("failures", []))

        scene_contracts_passed = True
        scene_results: list[SceneContractResult] = []
        if scene_reports:
            scene_contracts_passed = all(r.get("passed", False) for r in scene_reports)
            for report in scene_reports:
                scene_results.append(
                    SceneContractResult(
                        scene_number=report.get("scene_number", 0),
                        passed=bool(report.get("passed", False)),
                        retries=int(report.get("retries", 0)),
                        failures=list(report.get("failures", [])),
                    )
                )

        deterministic = DeterministicValidationResult(
            passed=not deterministic_failures and scene_contracts_passed,
            structural_passed=not structural_failures,
            scene_contracts_passed=scene_contracts_passed,
            chapter_contracts_passed=bool(chapter_contract_result.get("passed", False)),
            failures=deterministic_failures,
            scene_results=scene_results,
            chapter_requirements=[
                RequirementResult(
                    requirement=failure,
                    passed=False,
                    reason=failure,
                )
                for failure in chapter_contract_result.get("failures", [])
            ],
        )
        semantic = self._run_semantic_contract_validator(
            ch_num=ch_num,
            chapter_content=chapter_content,
            chapter_outline=chapter_outline,
            scene_breakdown=scene_breakdown,
        )
        adversarial = self._run_adversarial_validator(
            ch_num=ch_num,
            chapter_content=chapter_content,
            chapter_outline=chapter_outline,
            scene_breakdown=scene_breakdown,
            deterministic=deterministic,
            semantic=semantic,
        )

        bypass_flags = []
        if not getattr(self.config, "enable_pressure_contracts", False):
            bypass_flags.append("enable_pressure_contracts=false")
        if not getattr(self.config, "enable_quality_gates", False):
            bypass_flags.append("enable_quality_gates=false")
        if not getattr(self.config, "semantic_validator_enabled", False):
            bypass_flags.append("semantic_validator_enabled=false")
        acceptance_passed = (
            deterministic.passed
            and semantic.passed
            and (adversarial.passed if adversarial.triggered else True)
        )
        return ComplianceReport(
            chapter_number=ch_num,
            status="passed" if acceptance_passed else "failed",
            acceptance_passed=acceptance_passed,
            bypass_flags_used=bypass_flags,
            deterministic=deterministic,
            semantic=semantic,
            adversarial=adversarial,
            retries={
                "chapter_gate_retries": int(
                    getattr(self.config, "gate_max_chapter_retries", 0)
                ),
                "scene_contract_retries": int(
                    getattr(self.config, "gate_max_scene_retries", 0)
                ),
            },
            model_routing={
                "semantic_validator": getattr(self.config, "semantic_validator_model", ""),
                "adversarial_verifier": getattr(
                    self.config, "adversarial_verifier_model", ""
                ),
            },
        )

    @staticmethod
    def _collect_failed_requirements(report: ComplianceReport) -> list[str]:
        failures = list(report.deterministic.failures)
        failures.extend(report.semantic.failures)
        if report.adversarial.triggered and not report.adversarial.passed:
            failures.append(report.adversarial.reason or "adversarial_failed")
        return [f for f in failures if f]

    def _repair_chapter_from_failures(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        failed_requirements: list[str],
    ) -> str:
        requirement_block = "\n".join(f"- {item}" for item in failed_requirements)
        user_prompt = "\n".join(
            [
                "## CONTRACT REPAIR (MANDATORY)",
                "",
                "Repair ONLY the failed requirements listed below.",
                "Preserve scene order/count and all existing scene boundary markers (`---`).",
                "Do not introduce extra scenes or reorder existing scenes.",
                "",
                "### Failed Requirements",
                requirement_block,
                "",
                "### Current Chapter",
                chapter_content,
                "",
                "Output ONLY the revised chapter markdown.",
            ]
        )
        response = self.llm.generate_streaming(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_revision_structural,
            temperature=self.config.temperature_revision,
            max_tokens=self.config.max_tokens_per_call,
        )
        return response.content

    def _build_chapter_contract_preflight(self, chapter_outline, scene_breakdown) -> dict:
        """Audit chapter beat mapping into scene metadata before drafting."""
        beats = {
            "hard_reveal": (getattr(chapter_outline, "hard_reveal", "") or "").strip(),
            "soft_reversal": (getattr(chapter_outline, "soft_reversal", "") or "").strip(),
            "on_page_opposing_move": (
                getattr(chapter_outline, "on_page_opposing_move", "") or ""
            ).strip(),
            "petty_moment": (getattr(chapter_outline, "petty_moment", "") or "").strip(),
        }
        scene_texts: list[tuple[int, str]] = []
        for scene in getattr(scene_breakdown, "scenes", []) or []:
            merged = "\n".join(
                [
                    getattr(scene, "setting", "") or "",
                    getattr(scene, "turn", "") or "",
                    getattr(scene, "consequences", "") or "",
                    getattr(scene, "continuity_notes", "") or "",
                    getattr(scene, "opponent_move", "") or "",
                    getattr(scene, "pov_countermove", "") or "",
                    getattr(scene, "required_end_hook", "") or "",
                ]
            ).lower()
            scene_texts.append((int(getattr(scene, "scene_number", 0) or 0), merged))

        missing_beats: list[str] = []
        coverage: dict[str, list[int]] = {}
        for beat_name, beat_text in beats.items():
            if not beat_text:
                missing_beats.append(beat_name)
                coverage[beat_name] = []
                continue
            tokens = _keywords(beat_text)
            matched_scenes: list[int] = []
            for scene_number, merged in scene_texts:
                overlap = sum(1 for token in tokens if token in merged)
                if overlap >= 2:
                    matched_scenes.append(scene_number)
            coverage[beat_name] = matched_scenes
            if not matched_scenes:
                missing_beats.append(beat_name)

        return {
            "chapter_number": int(getattr(chapter_outline, "chapter_number", 0) or 0),
            "scene_count": len(scene_texts),
            "coverage": coverage,
            "missing_beats": missing_beats,
            "all_beats_mapped": len(missing_beats) == 0,
        }

    @staticmethod
    def _render_preflight_contract_directives(preflight: dict) -> str:
        """Build focused generation directives when beat mapping is missing."""
        missing = list(preflight.get("missing_beats", []))
        if not missing:
            return ""
        bullet_list = "\n".join(f"- {beat}" for beat in missing)
        return "\n".join(
            [
                "## CONTRACT PREFLIGHT DIRECTIVE (MANDATORY)",
                "",
                "The structure preflight detected chapter-level beats that are not",
                "explicitly mapped in scene metadata. You MUST realize these beats",
                "on page in this chapter's prose:",
                bullet_list,
                "",
                "Do not add extra scenes. Preserve expected scene count and `---`",
                "scene separators while making these beats explicit in scene action.",
            ]
        )

    def check_prerequisites(self) -> bool:
        structure = self.state_manager.load_novel_structure()
        world = self.state_manager.load_world_state()
        return structure is not None and world is not None

    def _generate_scene_by_scene_chapter(
        self,
        *,
        ch_num: int,
        base_prompt: str,
        system_prompt: str,
        scene_breakdown,
    ) -> str:
        """Generate chapter deterministically scene-by-scene and reassemble."""
        scenes: list[str] = []
        total_scenes = len(scene_breakdown.scenes) if scene_breakdown else 0
        if total_scenes == 0:
            response = self.llm.generate_streaming(
                system_prompt=system_prompt,
                user_prompt=base_prompt,
                model=self.config.model_prose_generation,
                temperature=self.config.temperature_prose,
                max_tokens=self.config.max_tokens_per_call,
            )
            return response.content

        scene_target_words = max(
            int(self.config.target_words_per_chapter / total_scenes),
            250,
        )
        for scene in scene_breakdown.scenes:
            scene_prompt = "\n".join(
                [
                    base_prompt,
                    "",
                    "## SCENE-LOCAL GENERATION (MANDATORY)",
                    (
                        f"Write ONLY scene {scene.scene_number} of {total_scenes}. "
                        "Do not write other scenes."
                    ),
                    "Do not output scene separators (`---`) in this response.",
                    (
                        f"Target length: ~{scene_target_words} words for this scene."
                    ),
                    (
                        "Required scene contract:\n"
                        f"- opponent_move: {scene.opponent_move}\n"
                        f"- pov_countermove: {scene.pov_countermove}\n"
                        f"- required_end_hook: {scene.required_end_hook or '(none)'}"
                    ),
                ]
            )
            scene_response = self.llm.generate_streaming(
                system_prompt=system_prompt,
                user_prompt=scene_prompt,
                model=self.config.model_prose_generation,
                temperature=self.config.temperature_prose,
                max_tokens=min(self.config.max_tokens_per_call, 4096),
            )
            scene_text = scene_response.content.strip()
            split = self._split_chapter_into_scenes(scene_text)
            scenes.append(split[0].strip() if split else scene_text)
            console.print(
                f"    [cyan]Scene {scene.scene_number}/{total_scenes} generated[/cyan]"
            )
        return "\n\n---\n\n".join(scenes)

    # ------------------------------------------------------------------
    # Single-chapter generation (reusable)
    # ------------------------------------------------------------------

    def generate_single_chapter(self, ch_num: int) -> str:
        """Generate a single chapter's v0_raw draft, summary, continuity
        update, and banned-phrase update.  Returns the chapter text.

        This is the building-block used by both ``run()`` (batch mode) and
        the ``sovereign-ink next`` CLI command.
        """
        novel_spec = self.state_manager.load_novel_spec()
        world_state = self.state_manager.load_world_state()
        structure = self.state_manager.load_novel_structure()

        summaries_data = self.state_manager.load_context_summaries()
        context_summaries: list[ContextSummary] = []
        if summaries_data:
            context_summaries = [
                ContextSummary(**s) if isinstance(s, dict) else s
                for s in summaries_data
            ]
        summarised_chapters = {
            cs.chapter_number if isinstance(cs, ContextSummary)
            else cs.get("chapter_number")
            for cs in context_summaries
        }

        ledger_data = self.state_manager.load_continuity_ledger()
        continuity_ledger: dict = ledger_data if ledger_data else {}

        system_prompt = self.prompts.render_system_prompt(
            era_tone_guide=world_state.era_tone_guide
        )
        state_dir = self.state_manager.project_dir / "state"
        banned_phrases = load_banned_phrases(state_dir)
        banned_phrases = sorted(set(banned_phrases) | set(BASELINE_BANNED_PHRASES))
        banned_constructions = load_banned_constructions(state_dir)

        chapter_outline = None
        chapter_idx = 0
        for idx, co in enumerate(structure.chapter_outlines):
            if co.chapter_number == ch_num:
                chapter_outline = co
                chapter_idx = idx
                break
        if chapter_outline is None:
            raise ValueError(f"No chapter outline found for chapter {ch_num}")

        existing = self.state_manager.load_chapter_draft(ch_num, "v0_raw")
        chapter_state = self.state_manager.load_chapter_state(ch_num) or {}
        fully_accepted = self.state_manager.is_chapter_fully_accepted(ch_num)
        if fully_accepted and existing:
            logger.info(
                "Chapter %d is fully accepted at v3_polish; reusing cached v0_raw.",
                ch_num,
            )
            return existing
        # Check stage-4-level compliance independently of overall acceptance.
        # If stage-5 (revision) failed but stage-4 compliance already passed,
        # do not re-draft — let stage-5 retry with the existing validated draft.
        stage4_compliance = self.state_manager.load_compliance_report(ch_num)
        stage4_passed = bool(
            stage4_compliance and stage4_compliance.get("acceptance_passed", False)
        )
        if existing and not stage4_passed:
            logger.info(
                "Chapter %d has draft but stage-4 compliance not achieved; regenerating for convergence.",
                ch_num,
            )
            existing = None
        if existing and ch_num in summarised_chapters and chapter_state.get("accepted", False):
            logger.info("Chapter %d already exists with summary, returning cached", ch_num)
            return existing

        if existing:
            chapter_content = existing
            word_count = len(chapter_content.split())
            console.print(
                f"  [yellow]Recovering summary for Chapter {ch_num}: "
                f"{chapter_outline.title} ({word_count} words)[/yellow]"
            )
        else:
            total_chapters = len(structure.chapter_outlines)
            console.print(
                f"  [yellow]Writing Chapter {ch_num}/{total_chapters}: "
                f"{chapter_outline.title}[/yellow]"
            )

            scene_breakdown = None
            for sb in structure.scene_breakdowns:
                if sb.chapter_number == ch_num:
                    scene_breakdown = sb
                    break
            preflight = self._build_chapter_contract_preflight(
                chapter_outline, scene_breakdown
            )
            preflight_path = (
                self.state_manager.project_dir
                / "state"
                / "quality_reports"
                / f"chapter_{ch_num:02d}_preflight.json"
            )
            self.state_manager._write_json(preflight_path, preflight)

            chapter_characters = [
                c
                for c in world_state.characters
                if c.name == chapter_outline.pov_character
                or any(
                    r.character_name == chapter_outline.pov_character
                    for r in c.relationships
                )
            ]
            if not chapter_characters:
                chapter_characters = world_state.characters

            prior_summary_text = ""
            if context_summaries:
                for cs in context_summaries:
                    summary = (
                        cs
                        if isinstance(cs, ContextSummary)
                        else ContextSummary(**cs)
                    )
                    prior_summary_text += (
                        f"\n### Chapter {summary.chapter_number} Summary\n"
                        f"{summary.summary}\n"
                    )

            next_outlines = structure.chapter_outlines[chapter_idx + 1 : chapter_idx + 3]
            prior_chapter_texts: dict[int, str] = {}
            for prior_outline in structure.chapter_outlines[:chapter_idx]:
                prior_num = prior_outline.chapter_number
                prior_text = (
                    self.state_manager.load_chapter_draft(prior_num, "v3_polish")
                    or self.state_manager.load_chapter_draft(prior_num, "v0_raw")
                )
                if prior_text:
                    prior_chapter_texts[prior_num] = prior_text
            chapter_ending_warning = build_chapter_ending_warning(prior_chapter_texts)

            chapter_year = _extract_year(chapter_outline.time_period)
            resolved_players = _resolve_major_players(
                world_state.historical_context.major_players, chapter_year
            )

            user_prompt = self.prompts.render_generation(
                chapter_outline=chapter_outline.model_dump(),
                scene_breakdown=(
                    scene_breakdown.model_dump() if scene_breakdown else None
                ),
                era_tone_guide=world_state.era_tone_guide.model_dump(),
                character_profiles=[
                    c.model_dump() for c in chapter_characters
                ],
                major_players=resolved_players,
                synopsis=novel_spec.synopsis if novel_spec else None,
                continuity_ledger=continuity_ledger,
                prior_summaries=prior_summary_text,
                next_chapter_outlines=[o.model_dump() for o in next_outlines],
                target_words=(
                    chapter_outline.estimated_word_count
                    or self.config.target_words_per_chapter
                ),
                banned_phrases=banned_phrases,
                banned_constructions=banned_constructions,
                chapter_ending_warning=chapter_ending_warning,
            )
            preflight_directives = self._render_preflight_contract_directives(
                preflight
            )
            if preflight_directives:
                user_prompt = f"{user_prompt}\n\n{preflight_directives}"

            self._save_chapter_state(
                ch_num,
                ChapterStateStatus.DRAFTING,
                accepted=False,
                increment_attempt=True,
            )
            if getattr(self.config, "generate_scene_by_scene_default", True):
                chapter_content = self._generate_scene_by_scene_chapter(
                    ch_num=ch_num,
                    base_prompt=user_prompt,
                    system_prompt=system_prompt,
                    scene_breakdown=scene_breakdown,
                )
            else:
                response = self.llm.generate_streaming(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=self.config.model_prose_generation,
                    temperature=self.config.temperature_prose,
                    max_tokens=self.config.max_tokens_per_call,
                )
                chapter_content = response.content
            word_count = len(chapter_content.split())

            scene_reports: list[dict] = []
            if getattr(self.config, "enable_pressure_contracts", False):
                chapter_content, scene_reports = self._apply_scene_contracts(
                    ch_num, chapter_content, system_prompt,
                    scene_breakdown, chapter_outline,
                )
                word_count = len(chapter_content.split())

            if self.config.enable_quality_gates:
                chapter_content = self._apply_chapter_gates(
                    ch_num, chapter_content, system_prompt
                )
                word_count = len(chapter_content.split())

            if getattr(self.config, "enable_ending_variation_gate", False):
                chapter_content = self._apply_ending_variation_gate(
                    ch_num, chapter_content, system_prompt
                )
                word_count = len(chapter_content.split())

            if getattr(self.config, "enable_length_guardrails", False):
                chapter_content = self._apply_generation_length_guardrails(
                    ch_num=ch_num,
                    chapter_content=chapter_content,
                    system_prompt=system_prompt,
                    chapter_outline=chapter_outline,
                )
                word_count = len(chapter_content.split())

            if getattr(self.config, "enable_chapter_completion_gate", False):
                chapter_content = self._apply_completion_gate(
                    ch_num=ch_num,
                    chapter_content=chapter_content,
                    system_prompt=system_prompt,
                )
                word_count = len(chapter_content.split())

            self._save_chapter_state(
                ch_num,
                ChapterStateStatus.DETERMINISTIC_VALIDATION,
                accepted=False,
            )
            compliance_report = self._evaluate_compliance(
                ch_num=ch_num,
                chapter_content=chapter_content,
                chapter_outline=chapter_outline,
                scene_breakdown=scene_breakdown,
                scene_reports=scene_reports,
            )
            self.state_manager.save_compliance_report(ch_num, compliance_report.model_dump())

            repair_attempt = 0
            convergence_window = max(int(getattr(self.config, "max_contract_retries", 2)), 1)
            max_total_repairs = max(
                int(getattr(self.config, "stage4_max_total_repair_attempts", 12)),
                convergence_window,
            )
            while not compliance_report.acceptance_passed:
                repair_attempt += 1
                failed_requirements = self._collect_failed_requirements(compliance_report)
                self._save_chapter_state(
                    ch_num,
                    ChapterStateStatus.REPAIR,
                    accepted=False,
                    last_failures=failed_requirements,
                )
                if repair_attempt >= max_total_repairs:
                    self._maybe_fail_contract(
                        ch_num,
                        "Chapter convergence exhausted after "
                        f"{repair_attempt} repair attempts. Last failures: "
                        f"{'; '.join(failed_requirements[:8]) if failed_requirements else 'none'}",
                        error_code="chapter_convergence_exhausted",
                    )
                chapter_content = self._repair_chapter_from_failures(
                    ch_num=ch_num,
                    chapter_content=chapter_content,
                    system_prompt=system_prompt,
                    failed_requirements=failed_requirements,
                )
                if getattr(self.config, "enable_pressure_contracts", False):
                    chapter_content, scene_reports = self._apply_scene_contracts(
                        ch_num, chapter_content, system_prompt,
                        scene_breakdown, chapter_outline,
                    )
                self._save_chapter_state(
                    ch_num,
                    ChapterStateStatus.REVALIDATE,
                    accepted=False,
                    last_failures=failed_requirements,
                )
                compliance_report = self._evaluate_compliance(
                    ch_num=ch_num,
                    chapter_content=chapter_content,
                    chapter_outline=chapter_outline,
                    scene_breakdown=scene_breakdown,
                    scene_reports=scene_reports,
                )
                self.state_manager.save_compliance_report(
                    ch_num, compliance_report.model_dump()
                )

                if compliance_report.acceptance_passed:
                    break

                # Avoid getting stuck in a local minimum: periodically re-draft.
                if repair_attempt % convergence_window == 0:
                    logger.warning(
                        "Chapter %d not accepted after %d repair attempts; re-drafting from generation prompt.",
                        ch_num,
                        repair_attempt,
                    )
                    chapter_content = self._generate_scene_by_scene_chapter(
                        ch_num=ch_num,
                        base_prompt=user_prompt,
                        system_prompt=system_prompt,
                        scene_breakdown=scene_breakdown,
                    )
                    if getattr(self.config, "enable_pressure_contracts", False):
                        chapter_content, scene_reports = self._apply_scene_contracts(
                            ch_num, chapter_content, system_prompt,
                            scene_breakdown, chapter_outline,
                        )
                    compliance_report = self._evaluate_compliance(
                        ch_num=ch_num,
                        chapter_content=chapter_content,
                        chapter_outline=chapter_outline,
                        scene_breakdown=scene_breakdown,
                        scene_reports=scene_reports,
                    )
                    self.state_manager.save_compliance_report(
                        ch_num, compliance_report.model_dump()
                    )

            self._save_chapter_state(
                ch_num,
                ChapterStateStatus.ACCEPTED,
                accepted=True,
                accepted_draft_version="v0_raw",
            )

            self.state_manager.save_chapter_draft(
                ch_num, chapter_content, "v0_raw"
            )

        summary = self._generate_chapter_summary(
            system_prompt, chapter_content, ch_num
        )
        context_summaries.append(summary)
        self.state_manager.save_context_summaries(
            [
                s.model_dump() if hasattr(s, "model_dump") else s
                for s in context_summaries
            ]
        )

        continuity_ledger = self._update_continuity(
            system_prompt, chapter_content, continuity_ledger, ch_num
        )
        self.state_manager.save_continuity_ledger(continuity_ledger)

        update_banned_phrases(
            state_dir=state_dir,
            chapter_number=ch_num,
            chapter_text=chapter_content,
            llm_client=self.llm,
            system_prompt=system_prompt,
            model=self.config.model_utility,
        )
        banned_phrases = load_banned_phrases(state_dir)

        console.print(
            f"    [green]✓ Chapter {ch_num} draft complete "
            f"({word_count} words, {len(banned_phrases)} banned phrases)[/green]"
        )

        return chapter_content

    # ------------------------------------------------------------------
    # Batch mode (existing behavior)
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._mark_started()

        try:
            structure = self.state_manager.load_novel_structure()

            total_chapters = len(structure.chapter_outlines)
            if self.config.max_chapters is not None:
                total_chapters = min(total_chapters, self.config.max_chapters)

            console.print(
                f"\n[bold cyan]Generating {total_chapters} chapters...[/bold cyan]\n"
            )

            for chapter_outline in structure.chapter_outlines[:total_chapters]:
                ch_num = chapter_outline.chapter_number
                self._update_sub_step(f"chapter_{ch_num}")
                self.generate_single_chapter(ch_num)

                if self.config.enable_quality_checkpoint and ch_num in self.config.checkpoint_after_chapters:
                    action = self._quality_checkpoint(ch_num, total_chapters)
                    if action == "abort":
                        console.print("\n[bold red]Pipeline aborted by user.[/bold red]")
                        self._mark_failed("Aborted at quality checkpoint")
                        return

            self._mark_completed()
            console.print("\n[bold green]All chapters generated![/bold green]")

        except Exception as e:
            self._mark_failed(str(e))
            raise

    def _quality_checkpoint(self, after_chapter: int, total_chapters: int) -> str:
        """Pause for user review after a batch of early chapters."""
        console.print(
            f"\n[bold yellow]{'─' * 60}[/bold yellow]"
        )
        console.print(
            f"[bold yellow]QUALITY CHECKPOINT — "
            f"Chapters 1–{after_chapter} of {total_chapters} generated[/bold yellow]"
        )
        console.print(
            f"[bold yellow]{'─' * 60}[/bold yellow]\n"
        )

        for ch in range(1, after_chapter + 1):
            draft = self.state_manager.load_chapter_draft(ch, "v0_raw")
            if draft:
                wc = len(draft.split())
                draft_path = self.state_manager.project_dir / "drafts" / "v0_raw" / f"chapter_{ch:02d}.md"
                console.print(f"  Chapter {ch}: {wc} words — [dim]{draft_path}[/dim]")

        console.print(
            "\n[cyan]Please review the chapter files above before continuing.[/cyan]"
        )
        console.print(
            "[cyan]This is your chance to catch quality issues early.[/cyan]\n"
        )

        choice = Prompt.ask(
            "Action",
            choices=["continue", "abort"],
            default="continue",
        )
        return choice

    # ------------------------------------------------------------------
    # Length guardrails (Phase 8)
    # ------------------------------------------------------------------

    def _apply_generation_length_guardrails(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        chapter_outline,
    ) -> str:
        """Constrain overlong chapters with targeted compression passes."""
        max_words = max(int(self.config.max_words_per_chapter), 1)
        soft_cap = int(
            max_words * float(getattr(self.config, "length_soft_cap_ratio", 1.10))
        )
        hard_cap = int(
            max_words * float(getattr(self.config, "length_hard_cap_ratio", 1.25))
        )
        soft_cap = max(soft_cap, max_words)
        hard_cap = max(hard_cap, soft_cap)

        word_count = len(chapter_content.split())
        if word_count <= soft_cap:
            return chapter_content

        console.print(
            f"    [yellow]Length guardrail: chapter {ch_num} is {word_count} words "
            f"(soft cap {soft_cap}, hard cap {hard_cap}) — running targeted compression[/yellow]"
        )
        max_retries = max(int(getattr(self.config, "length_guard_max_retries", 2)), 1)
        current = chapter_content
        best = chapter_content
        best_wc = len(best.split())
        ending_mode = getattr(chapter_outline, "ending_mode", "")

        for retry in range(1, max_retries + 1):
            compressed = self._compress_to_word_budget(
                ch_num=ch_num,
                chapter_content=current,
                system_prompt=system_prompt,
                soft_cap=soft_cap,
                hard_cap=hard_cap,
                ending_mode=ending_mode,
            )
            compressed_wc = len(compressed.split())
            if compressed_wc < best_wc:
                best = compressed
                best_wc = compressed_wc

            delta = compute_quality_delta(current, compressed)
            harmful = any(
                r["metric"] in {"sensory_deficit_scenes", "immediate_jeopardy_deficit_scenes"}
                for r in delta["regressions"]
            )
            if harmful:
                logger.warning(
                    "Chapter %d compression retry %d increased sensory/jeopardy deficits",
                    ch_num,
                    retry,
                )
                current = current
                continue

            current = compressed
            if compressed_wc <= soft_cap:
                console.print(
                    f"    [green]Length guardrail satisfied after retry {retry}: "
                    f"{compressed_wc} words[/green]"
                )
                return compressed

        if best_wc > hard_cap:
            logger.warning(
                "Chapter %d remains over hard cap after compression retries: %d words > %d",
                ch_num,
                best_wc,
                hard_cap,
            )
            console.print(
                f"    [yellow]Length guardrail unresolved after retries: {best_wc} words "
                f"(hard cap {hard_cap})[/yellow]"
            )
        return best

    def _compress_to_word_budget(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        soft_cap: int,
        hard_cap: int,
        ending_mode: str = "",
    ) -> str:
        """Targeted compression that preserves stakes, sensory detail, and ending shape."""
        baseline_words = len(chapter_content.split())
        quality_delta = compute_quality_delta(chapter_content, chapter_content)
        regression_context = format_regression_report(quality_delta, "length_guard")
        mode_line = f"- Preserve ending mode: {ending_mode}" if ending_mode else ""
        user_prompt = "\n".join([
            "## TARGETED LENGTH COMPRESSION (MANDATORY)",
            "",
            f"Current words: {baseline_words}",
            f"Target words: <= {soft_cap}",
            f"Absolute hard cap: {hard_cap}",
            "",
            "Compress by deleting redundancy and flattening repeated exposition.",
            "Do NOT remove scenes, scene breaks, opposition moves, deadlines, or sensory anchors.",
            "Maintain or improve immediate jeopardy and non-visual sensory grounding.",
            mode_line,
            "",
            "Priority cuts:",
            "1) repeated reflections about same idea",
            "2) duplicated qualifiers and throat-clearing transitions",
            "3) repeated metaphor families and n-gram patterns",
            "",
            "Output ONLY the revised chapter in markdown with existing scene breaks.",
            "",
            "## CHAPTER TO COMPRESS",
            chapter_content,
            "",
            regression_context,
        ])
        response = self.llm.generate_streaming(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_revision_polish,
            temperature=self.config.temperature_revision,
            max_tokens=self.config.max_tokens_per_call,
        )
        return response.content

    # ------------------------------------------------------------------
    # Quality gates (pre-save)
    # ------------------------------------------------------------------

    def _gate_thresholds(self) -> dict[str, int | float]:
        return {
            "max_jeopardy_deficit_scenes": self.config.gate_max_jeopardy_deficit_scenes,
            "max_exposition_drag_runs": self.config.gate_max_exposition_drag_runs,
            "rhythm_cv_threshold": self.config.gate_rhythm_cv_threshold,
            "short_sentence_ratio_threshold": self.config.gate_short_sentence_ratio_threshold,
            "max_psychologizing_per_1k_words": self.config.gate_max_psychologizing_per_1k_words,
        }

    def _apply_chapter_gates(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
    ) -> str:
        """Run acceptance gates on generated prose and retry on failure."""
        gate_results = run_chapter_gates(chapter_content, self._gate_thresholds())
        failed = {k: v for k, v in gate_results.items() if not v.passed}

        if not failed:
            console.print(f"    [green]All quality gates passed[/green]")
            self._save_gate_results(ch_num, gate_results, retry=0)
            return chapter_content

        gate_names = ", ".join(failed.keys())
        console.print(
            f"    [yellow]Gate failures: {gate_names} — "
            f"running pre-save correction[/yellow]"
        )

        max_retries = self.config.gate_max_chapter_retries
        for retry in range(1, max_retries + 1):
            correction_parts = [
                "## PRE-SAVE GATE CORRECTIONS (MANDATORY)",
                "",
                "The following quality gates FAILED on the generated chapter. "
                "You MUST fix these issues while preserving scene structure, "
                "narrative flow, and word count.",
                "",
            ]
            for result in failed.values():
                if result.report:
                    correction_parts.append(result.report)
                    correction_parts.append("")

            correction_parts.append(_GATE_CORRECTION_EXEMPLARS)
            correction_context = "\n".join(correction_parts)

            opus_eligible = getattr(
                self.config,
                "opus_eligible_gates",
                ["offstage_opposition", "immediate_jeopardy"],
            )
            structural_failures = {k for k in failed if k in opus_eligible}
            use_opus = (
                retry >= max_retries
                and getattr(self.config, "gate_opus_scene_escalation", True)
                and bool(structural_failures)
            )
            model = (
                self.config.model_revision_structural_opus
                if use_opus
                else self.config.model_revision_structural
            )
            if use_opus:
                console.print(
                    f"    [yellow]Escalating to Opus for retry {retry}[/yellow]"
                )

            chapter_content = self._gate_correction_pass(
                ch_num, chapter_content, system_prompt, correction_context,
                model_override=model,
            )

            gate_results = run_chapter_gates(
                chapter_content, self._gate_thresholds()
            )
            failed = {k: v for k, v in gate_results.items() if not v.passed}

            if not failed:
                console.print(
                    f"    [green]All gates passed after retry {retry}[/green]"
                )
                self._save_gate_results(ch_num, gate_results, retry=retry)
                return chapter_content

        still_failed = ", ".join(failed.keys())
        console.print(
            f"    [yellow]Gates still failing after {max_retries} "
            f"retry(s): {still_failed}[/yellow]"
        )
        logger.warning(
            "Chapter %d: gates still failing after %d retries: %s",
            ch_num, max_retries, still_failed,
        )
        self._save_gate_results(ch_num, gate_results, retry=max_retries)
        self._maybe_fail_contract(
            ch_num,
            f"Quality gates failed after retries: {still_failed}",
            error_code="quality_gates_failed",
        )
        return chapter_content

    def _apply_ending_variation_gate(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
    ) -> str:
        """Cross-chapter gate: detect and correct repeating ending tonal shapes.

        Loads the prior chapter's v0_raw draft (if available), builds a dict of
        chapter texts, runs ``gate_ending_tonal_monotony``, and if it fails,
        injects an ending-variation correction pass.
        """
        # Build chapter texts dict: prior chapter + current
        chapter_texts: dict[int, str] = {}
        if ch_num > 1:
            prior_text = self.state_manager.load_chapter_draft(ch_num - 1, "v0_raw")
            if prior_text:
                chapter_texts[ch_num - 1] = prior_text
        chapter_texts[ch_num] = chapter_content

        # In the pipeline we compare only the prior chapter vs current, so we
        # pass max_consecutive_similar=1 to fail on any consecutive similar pair.
        # The config value is preserved for future multi-chapter comparisons.
        max_consecutive = 1
        similarity_threshold = getattr(
            self.config, "gate_ending_similarity_threshold", 0.70
        )

        gate_result = gate_ending_tonal_monotony(
            chapter_texts,
            max_consecutive_similar=max_consecutive,
            similarity_threshold=similarity_threshold,
        )

        if gate_result.passed:
            console.print(
                f"    [green]Ending variation gate passed[/green]"
            )
            return chapter_content

        console.print(
            f"    [yellow]Ending variation gate failed — "
            f"running ending correction pass[/yellow]"
        )
        logger.warning(
            "Chapter %d: ending tonal monotony gate failed: %s",
            ch_num, gate_result.report[:200],
        )

        correction_context = "\n".join([
            "## ENDING VARIATION CORRECTION (MANDATORY)",
            "",
            gate_result.report,
            "",
            "Rewrite the final 200–300 words of this chapter to match the "
            "assigned ending_mode. Consult the ENDING MODE REFERENCE in the "
            "original chapter prompt for concrete examples. The current ending "
            "shares the same dark/reflective/solitary shape as the previous "
            "chapter. Change the mode, not just the surface words.",
        ])

        corrected = self._gate_correction_pass(
            ch_num, chapter_content, system_prompt, correction_context,
        )
        chapter_texts[ch_num] = corrected
        post_gate = gate_ending_tonal_monotony(
            chapter_texts,
            max_consecutive_similar=max_consecutive,
            similarity_threshold=similarity_threshold,
        )
        if not post_gate.passed:
            self._maybe_fail_contract(
                ch_num,
                "Ending variation gate remained failing after correction pass.",
                error_code="ending_variation_failed",
            )
        return corrected

    def _gate_correction_pass(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        correction_context: str,
        model_override: str | None = None,
    ) -> str:
        """Run a targeted correction pass to address gate failures."""
        user_prompt = self.prompts.render_revision(
            "structural",
            chapter_content=chapter_content,
            chapter_number=ch_num,
            chapter_outline={},
            novel_structure_summary="",
            quality_audit=correction_context,
            original_draft=chapter_content,
            v0_word_count=len(chapter_content.split()),
            word_count_floor=max(
                int(len(chapter_content.split()) * 0.85),
                self.config.min_words_per_chapter,
            ),
        )

        model = model_override or self.config.model_revision_structural
        response = self.llm.generate_streaming(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=self.config.temperature_revision,
            max_tokens=self.config.max_tokens_per_call,
        )
        return response.content

    def _apply_completion_gate(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
    ) -> str:
        """Detect and repair incomplete/truncated chapter endings.

        If the chapter appears truncated (missing sentence-final punctuation,
        unmatched quotes, dangling function words, bare dashes), rewrites only
        the final ~300-500 words to produce a clean endpoint.  Retries up to
        ``gate_max_completion_retries`` times.  On persistent failure, logs a
        warning and continues with an explicit gate-fail marker persisted to
        the gate results JSON.
        """
        max_retries = max(int(getattr(self.config, "gate_max_completion_retries", 2)), 1)
        current = chapter_content

        for retry in range(max_retries + 1):
            finding = detect_incomplete_chapter_ending(current)
            if not finding:
                if retry > 0:
                    console.print(
                        f"    [green]Completion gate passed after repair attempt {retry}[/green]"
                    )
                return current

            if retry == 0:
                console.print(
                    f"    [yellow]Completion gate: chapter {ch_num} ending appears "
                    f"incomplete — running tail repair[/yellow]"
                )
                logger.warning(
                    "Chapter %d: completion gate failed: %s",
                    ch_num,
                    "; ".join(finding.get("reasons", [])),
                )

            if retry >= max_retries:
                console.print(
                    f"    [yellow]Completion gate: still failing after {max_retries} "
                    f"repair attempt(s)[/yellow]"
                )
                logger.warning(
                    "Chapter %d: completion gate persistently failing after %d retries",
                    ch_num, max_retries,
                )
                # Persist explicit failure marker into gate results
                from sovereign_ink.utils.text_quality import gate_complete_chapter_ending
                fail_result = gate_complete_chapter_ending(current)
                existing_gates = {
                    "complete_chapter_ending_persistent_failure": fail_result.to_dict()
                }
                data = {
                    "chapter_number": ch_num,
                    "completion_gate_failed": True,
                    "completion_gate_reasons": finding.get("reasons", []),
                    "gates": existing_gates,
                    "all_passed": False,
                }
                path = (
                    self.state_manager.project_dir
                    / "state"
                    / "quality_reports"
                    / f"chapter_{ch_num:02d}_completion_gate.json"
                )
                self.state_manager._write_json(path, data)
                self._maybe_fail_contract(
                    ch_num,
                    "Completion gate persistently failing after retries.",
                    error_code="completion_gate_failed",
                )
                return current

            current = self._repair_incomplete_chapter_tail(
                ch_num=ch_num,
                chapter_content=current,
                system_prompt=system_prompt,
                finding=finding,
            )

        return current

    def _repair_incomplete_chapter_tail(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        finding: dict,
    ) -> tuple[str, list[dict]]:
        """Rewrite only the last ~300-500 words to produce a clean chapter ending.

        Preserves the chapter body (everything except the last ~500 words) and
        provides the last ~800 chars as continuity context.  Explicitly instructs
        the model to complete the existing scene only — no new plot events.
        """
        words = chapter_content.split()
        # Split ~500 words from the end at a clean paragraph boundary
        split_word_target = max(0, len(words) - 500)
        body_approximate = " ".join(words[:split_word_target])
        last_para_break = body_approximate.rfind("\n\n")
        if last_para_break >= 0 and last_para_break > len(body_approximate) - 800:
            split_idx = last_para_break + 2
        else:
            split_idx = len(body_approximate)

        body = chapter_content[:split_idx].rstrip()
        tail = chapter_content[split_idx:].lstrip()
        body_context_tail = body[-800:] if len(body) > 800 else body

        reasons_text = "\n".join(f"- {r}" for r in finding.get("reasons", []))

        user_prompt = "\n\n".join([
            "## CHAPTER TAIL COMPLETION REPAIR (MANDATORY)",
            "",
            "The chapter ending below is INCOMPLETE or TRUNCATED. "
            "The following issues were detected:",
            "",
            reasons_text,
            "",
            "**Instructions:**",
            "- Complete the existing sentence and scene naturally.",
            "- Do NOT introduce new plot events, characters, or scenes.",
            "- End the chapter with a clean sentence-final punctuation mark.",
            "- Preserve narrative continuity with the body context.",
            "- Match the existing prose style and POV voice.",
            "- Output ONLY the repaired tail — no commentary, no headers.",
            "---",
            "## PRECEDING BODY CONTEXT (do NOT rewrite this section)",
            "",
            body_context_tail,
            "---",
            "## TAIL TO REPAIR (complete and output this section only)",
            "",
            tail if tail else "(tail is empty — the chapter was cut at the paragraph break above; write a clean closing beat of 2-4 sentences)",
        ])

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_revision_structural,
            temperature=self.config.temperature_revision,
            max_tokens=1024,
        )
        repaired_tail = response.content.strip()
        return body + "\n\n" + repaired_tail

    def _save_gate_results(
        self,
        ch_num: int,
        gate_results: dict[str, GateResult],
        retry: int,
    ) -> None:
        """Persist gate outcomes so Stage 5 can reference them."""
        data = {
            "chapter_number": ch_num,
            "retry_count": retry,
            "gates": {
                name: result.to_dict() for name, result in gate_results.items()
            },
            "all_passed": all(r.passed for r in gate_results.values()),
        }
        path = (
            self.state_manager.project_dir
            / "state"
            / "quality_reports"
            / f"chapter_{ch_num:02d}_gates.json"
        )
        self.state_manager._write_json(path, data)

    # ------------------------------------------------------------------
    # Scene-level pressure contract enforcement
    # ------------------------------------------------------------------

    def _apply_scene_contracts(
        self,
        ch_num: int,
        chapter_content: str,
        system_prompt: str,
        scene_breakdown,
        chapter_outline,
    ) -> str:
        """Check each scene against its pressure contract and rewrite failures."""
        if scene_breakdown is None:
            return chapter_content, []

        scenes_text = self._split_chapter_into_scenes(chapter_content)
        contracts = scene_breakdown.scenes
        if not contracts or len(scenes_text) == 0:
            return chapter_content, []

        max_scene_retries = getattr(self.config, "gate_max_scene_retries", 2)
        use_opus_escalation = getattr(
            self.config, "gate_opus_scene_escalation", True
        )
        scene_reports: list[dict] = []
        any_rewritten = False

        for idx, contract in enumerate(contracts):
            if idx >= len(scenes_text):
                break

            scene_text = scenes_text[idx]
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

            if check["passed"]:
                scene_reports.append({
                    "scene_number": contract.scene_number,
                    "passed": True,
                    "failures": [],
                    "retries": 0,
                })
                continue

            console.print(
                f"    [yellow]Scene {contract.scene_number} contract failures: "
                f"{', '.join(check['failures'])}[/yellow]"
            )

            rewritten = scene_text
            for retry in range(1, max_scene_retries + 1):
                model = self.config.model_revision_structural
                if (
                    retry >= max_scene_retries
                    and use_opus_escalation
                ):
                    model = self.config.model_revision_structural_opus

                rewritten = self._rewrite_scene_from_contract(
                    scene_text=rewritten,
                    contract=contract,
                    failures=check["failures"],
                    system_prompt=system_prompt,
                    model=model,
                )
                check = run_scene_contract_checks(
                    rewritten,
                    contract,
                    enable_physical_interruption_contracts=bool(
                        getattr(self.config, "enable_physical_interruption_contracts", False)
                    ),
                    enable_narrative_register=bool(
                        getattr(self.config, "enable_narrative_register", False)
                    ),
                )
                if check["passed"]:
                    console.print(
                        f"    [green]Scene {contract.scene_number} contract "
                        f"satisfied after retry {retry}[/green]"
                    )
                    break

            scenes_text[idx] = rewritten
            any_rewritten = any_rewritten or (rewritten != scene_text)
            scene_reports.append({
                "scene_number": contract.scene_number,
                "passed": check["passed"],
                "failures": check["failures"],
                "retries": retry if not check["passed"] else retry,
            })

        self._save_scene_contract_results(ch_num, scene_reports)

        any_failed = any(not r["passed"] for r in scene_reports)
        if any_failed:
            failed_scene_ids = [str(r["scene_number"]) for r in scene_reports if not r["passed"]]
            self._maybe_fail_contract(
                ch_num,
                f"Scene contracts failed after retries for scene(s): {', '.join(failed_scene_ids)}",
                error_code="scene_contracts_failed",
            )
        if any_rewritten:
            return self._reassemble_scenes(scenes_text), scene_reports
        return chapter_content, scene_reports

    @staticmethod
    def _split_chapter_into_scenes(text: str) -> list[str]:
        """Split chapter text by markdown scene breaks (---)."""
        import re
        parts = re.split(r"\n\s*---\s*\n", text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _reassemble_scenes(scenes: list[str]) -> str:
        """Reassemble scene parts with markdown scene breaks."""
        return "\n\n---\n\n".join(scenes)

    def _rewrite_scene_from_contract(
        self,
        scene_text: str,
        contract,
        failures: list[str],
        system_prompt: str,
        model: str,
    ) -> str:
        """Rewrite a single scene to satisfy its pressure contract."""
        failure_directives = "\n".join(f"- {f}" for f in failures)

        contract_block = (
            f"Gate Profile: {contract.gate_profile}\n"
            f"Opponent Actor: {contract.opponent_actor}\n"
            f"Opponent Move (MUST appear on page): {contract.opponent_move}\n"
            f"POV Countermove (MUST appear on page): {contract.pov_countermove}\n"
            f"Failure Event If No Action: {contract.failure_event_if_no_action}\n"
        )
        if contract.deadline_or_clock:
            contract_block += (
                f"Deadline / Clock: {contract.deadline_or_clock}\n"
            )
        if contract.required_end_hook:
            contract_block += (
                f"Required End Hook: {contract.required_end_hook}\n"
            )

        user_prompt = (
            "## SCENE CONTRACT REWRITE (MANDATORY)\n\n"
            "The following scene failed its pressure contract checks. "
            "You MUST rewrite it to satisfy the contract while preserving "
            "narrative quality, word count, and continuity.\n\n"
            "### Contract Failures\n"
            f"{failure_directives}\n\n"
            "### Pressure Contract\n"
            f"{contract_block}\n"
            "### Scene Goal\n"
            f"{contract.goal}\n\n"
            "### Scene Opposition\n"
            f"{contract.opposition}\n\n"
            "### Current Scene Text\n\n"
            f"{scene_text}\n\n"
            "### Instructions\n"
            "Rewrite the scene so that:\n"
            "1. The opponent_move appears as concrete on-page action\n"
            "2. The pov_countermove appears as concrete on-page response\n"
            "3. Immediate jeopardy is explicit before scene midpoint\n"
            "4. The failure_event is referenced or implied in the stakes\n"
            "5. Preserve the scene's turn, consequences, and emotional beat\n"
            "6. Maintain word count within 15% of the original\n\n"
            "Output ONLY the rewritten scene prose. No commentary."
        )

        response = self.llm.generate_streaming(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=self.config.temperature_revision,
            max_tokens=self.config.max_tokens_per_call,
        )
        return response.content

    def _save_scene_contract_results(
        self,
        ch_num: int,
        scene_reports: list[dict],
    ) -> None:
        """Persist per-scene contract check outcomes."""
        data = {
            "chapter_number": ch_num,
            "scene_contracts": scene_reports,
            "all_passed": all(r["passed"] for r in scene_reports),
        }
        path = (
            self.state_manager.project_dir
            / "state"
            / "quality_reports"
            / f"chapter_{ch_num:02d}_scene_contracts.json"
        )
        self.state_manager._write_json(path, data)

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    def _generate_chapter_summary(
        self, system_prompt: str, chapter_content: str, chapter_number: int
    ) -> ContextSummary:
        """Generate a rolling context summary for the chapter."""
        user_prompt = self.prompts.render_utility(
            "chapter_summary",
            chapter_content=chapter_content,
            chapter_number=chapter_number,
            target_words=self.config.summary_target_words,
        )

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_utility,
            temperature=0.3,
            max_tokens=2048,
        )

        try:
            data = json.loads(response.content)
            return ContextSummary(
                chapter_number=chapter_number,
                summary=data.get("summary", response.content),
                key_events=data.get("key_events", []),
                character_states=data.get("character_states", {}),
            )
        except (json.JSONDecodeError, Exception):
            return ContextSummary(
                chapter_number=chapter_number,
                summary=response.content[:1000],
                key_events=[],
                character_states={},
            )

    def _update_continuity(
        self,
        system_prompt: str,
        chapter_content: str,
        current_ledger: dict,
        chapter_number: int,
    ) -> dict:
        """Update the continuity ledger after a chapter."""
        compressed_ledger = self._compress_ledger(current_ledger)

        user_prompt = self.prompts.render_utility(
            "continuity_update",
            chapter_content=chapter_content,
            continuity_ledger=compressed_ledger,
            chapter_number=chapter_number,
        )

        response = self.llm.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.config.model_utility,
            temperature=0.2,
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
            content = self.llm._repair_json(content)
            updated = json.loads(content)
            return updated
        except (json.JSONDecodeError, Exception):
            logger.warning(
                "Failed to parse continuity update for chapter %d, keeping previous ledger",
                chapter_number,
            )
            return current_ledger

    @staticmethod
    def _compress_ledger(ledger: dict) -> dict:
        """Compress the continuity ledger to reduce token usage."""
        if not ledger or not isinstance(ledger, dict):
            return ledger

        compressed = {}
        for key, value in ledger.items():
            if isinstance(value, dict):
                compressed_dict = {}
                for k, v in value.items():
                    if isinstance(v, list) and len(v) > 5:
                        compressed_dict[k] = v[-5:]
                    elif isinstance(v, str) and len(v) > 200:
                        compressed_dict[k] = v[:200] + "..."
                    else:
                        compressed_dict[k] = v
                compressed[key] = compressed_dict
            elif isinstance(value, list):
                if len(value) > 10:
                    compressed[key] = value[-10:]
                else:
                    compressed[key] = value
            elif isinstance(value, str) and len(value) > 300:
                compressed[key] = value[:300] + "..."
            else:
                compressed[key] = value

        if "character_knowledge" in compressed and isinstance(compressed["character_knowledge"], dict):
            for char, facts in compressed["character_knowledge"].items():
                if isinstance(facts, list) and len(facts) > 5:
                    compressed["character_knowledge"][char] = facts[-5:]

        if "open_questions" in compressed and isinstance(compressed["open_questions"], list):
            if len(compressed["open_questions"]) > 8:
                compressed["open_questions"] = compressed["open_questions"][-8:]

        return compressed
