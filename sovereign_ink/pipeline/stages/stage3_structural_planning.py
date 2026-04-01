"""Stage 3: Structural Planning — act structure, chapter outlines, scene breakdowns, continuity ledger."""

from __future__ import annotations

import logging

import sentry_sdk
from pydantic import BaseModel
from rich.console import Console

from sovereign_ink.models import (
    ActStructure,
    ChapterOutline,
    CharacterKnowledge,
    ContinuityLedger,
    NovelSpec,
    NovelStructure,
    OpenThread,
    PoliticalCapital,
    RelationshipState,
    SceneBreakdown,
    TimelineEntry,
    WorldState,
    validate_pressure_architecture,
)
from sovereign_ink.pipeline.base import PipelineStage

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Wrapper models for list-typed structured responses
# ---------------------------------------------------------------------------

class ChapterOutlineList(BaseModel):
    """Wrapper so generate_structured can return a list of chapter outlines."""

    chapter_outlines: list[ChapterOutline]


class SceneBreakdownList(BaseModel):
    """Wrapper so generate_structured can return a list of scene breakdowns."""

    scene_breakdowns: list[SceneBreakdown]


# ---------------------------------------------------------------------------
# Sub-step registry
# ---------------------------------------------------------------------------

_SUB_STEPS = [
    "act_structure",
    "chapter_outlines",
    "scene_breakdowns",
    "continuity_ledger",
    "assemble_structure",
]


class StructuralPlanningStage(PipelineStage):
    """Plan the novel's act/chapter/scene architecture and initialise the continuity ledger."""

    STAGE_NAME = "structural_planning"

    def check_prerequisites(self) -> bool:
        """Stage 2 must have produced a full WorldState."""
        return self.state_manager.load_world_state() is not None

    def run(self) -> None:
        self._mark_started()

        try:
            novel_spec: NovelSpec = self.state_manager.load_novel_spec()
            world_state: WorldState = self.state_manager.load_world_state()
            system_prompt = self.prompts.render_system_prompt(
                era_tone_guide=world_state.era_tone_guide
            )

            # Determine resume point
            start_idx = self._resume_index()

            for idx in range(start_idx, len(_SUB_STEPS)):
                step = _SUB_STEPS[idx]
                self._update_sub_step(step)
                console.print(f"  [cyan]Structural planning:[/cyan] {step}")

                with sentry_sdk.start_span(op="structure", name=f"structure.{step}") as span:
                    span.set_data("sub_step", step)
                    if step == "act_structure":
                        self._build_act_structure(
                            system_prompt, novel_spec, world_state
                        )
                    elif step == "chapter_outlines":
                        self._build_chapter_outlines(
                            system_prompt, novel_spec, world_state
                        )
                    elif step == "scene_breakdowns":
                        self._build_scene_breakdowns(
                            system_prompt, novel_spec, world_state
                        )
                    elif step == "continuity_ledger":
                        self._init_continuity_ledger(world_state)
                    elif step == "assemble_structure":
                        self._assemble_structure()

            self._mark_completed()

        except Exception as exc:
            self._mark_failed(str(exc))
            raise

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    def _resume_index(self) -> int:
        """Determine the first sub-step that still needs to run."""
        structure = self.state_manager.load_novel_structure()

        # If we don't have a saved structure at all, check for intermediate
        # state via the pipeline sub_step marker.
        if structure is None:
            return 0

        # Structure exists — check completeness
        if not structure.act_structure or not structure.act_structure.acts:
            return 0
        if not structure.chapter_outlines:
            return 1
        if not structure.scene_breakdowns:
            return 2
        if self.state_manager.load_continuity_ledger() is None:
            return 3
        return len(_SUB_STEPS)

    # ------------------------------------------------------------------
    # Intermediate state helpers
    # ------------------------------------------------------------------

    def _load_act_structure(self) -> ActStructure | None:
        """Load act structure from the saved (possibly partial) novel structure."""
        structure = self.state_manager.load_novel_structure()
        if structure and structure.act_structure and structure.act_structure.acts:
            return structure.act_structure
        return None

    def _load_chapter_outlines(self) -> list[ChapterOutline] | None:
        structure = self.state_manager.load_novel_structure()
        if structure and structure.chapter_outlines:
            return structure.chapter_outlines
        return None

    def _save_partial_structure(
        self,
        act_structure: ActStructure | None = None,
        chapter_outlines: list[ChapterOutline] | None = None,
        scene_breakdowns: list[SceneBreakdown] | None = None,
    ) -> None:
        """Save a (possibly incomplete) NovelStructure for crash recovery."""
        existing = self.state_manager.load_novel_structure()

        if existing:
            act_struct = act_structure or existing.act_structure
            outlines = chapter_outlines or existing.chapter_outlines
            scenes = scene_breakdowns or existing.scene_breakdowns
        else:
            act_struct = act_structure or ActStructure(num_acts=3, acts=[])
            outlines = chapter_outlines or []
            scenes = scene_breakdowns or []

        partial = NovelStructure(
            act_structure=act_struct,
            chapter_outlines=outlines,
            scene_breakdowns=scenes,
        )
        self.state_manager.save_novel_structure(partial)

    # ------------------------------------------------------------------
    # Sub-step implementations
    # ------------------------------------------------------------------

    def _build_act_structure(
        self,
        system_prompt: str,
        novel_spec: NovelSpec,
        world_state: WorldState,
    ) -> None:
        logger.info("Generating act structure …")
        user_prompt = self.prompts.render_structure(
            sub_task="act_structure",
            novel_spec=novel_spec,
            world_state=world_state,
        )
        result: ActStructure = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ActStructure,
            model=self.config.model_structural_planning,
            temperature=self.config.temperature_world_building,
        )
        self._save_partial_structure(act_structure=result)
        logger.info(
            "Act structure saved (%d acts)", result.num_acts
        )

    def _build_chapter_outlines(
        self,
        system_prompt: str,
        novel_spec: NovelSpec,
        world_state: WorldState,
    ) -> None:
        logger.info("Generating chapter outlines …")
        act_structure = self._load_act_structure()
        user_prompt = self.prompts.render_structure(
            sub_task="chapter_outlines",
            novel_spec=novel_spec,
            world_state=world_state,
            act_structure=act_structure,
            target_words=self.config.target_words_per_chapter,
            min_words=self.config.min_words_per_chapter,
            max_words=self.config.max_words_per_chapter,
        )
        result: ChapterOutlineList = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=ChapterOutlineList,
            model=self.config.model_structural_planning,
            temperature=self.config.temperature_world_building,
        )

        # Post-generation clamp: reject LLM-inflated word counts
        for co in result.chapter_outlines:
            if co.estimated_word_count > self.config.max_words_per_chapter:
                logger.warning(
                    "Chapter %d estimated_word_count %d exceeds max %d — clamping",
                    co.chapter_number,
                    co.estimated_word_count,
                    self.config.max_words_per_chapter,
                )
                co.estimated_word_count = self.config.max_words_per_chapter
            elif co.estimated_word_count < self.config.min_words_per_chapter:
                logger.warning(
                    "Chapter %d estimated_word_count %d below min %d — clamping",
                    co.chapter_number,
                    co.estimated_word_count,
                    self.config.min_words_per_chapter,
                )
                co.estimated_word_count = self.config.min_words_per_chapter

        # P8: Synopsis-POV alignment check
        if novel_spec.synopsis:
            self._check_synopsis_pov_alignment(
                novel_spec.synopsis, result.chapter_outlines, world_state
            )

        self._save_partial_structure(chapter_outlines=result.chapter_outlines)
        logger.info(
            "Saved %d chapter outlines", len(result.chapter_outlines)
        )

    def _check_synopsis_pov_alignment(
        self,
        synopsis: str,
        chapter_outlines: list[ChapterOutline],
        world_state: WorldState,
    ) -> None:
        """Warn if the chapter outlines' POV characters diverge from synopsis protagonists."""
        character_names = {c.name.lower() for c in world_state.characters}
        synopsis_lower = synopsis.lower()

        synopsis_characters = set()
        for name in character_names:
            if name in synopsis_lower:
                for c in world_state.characters:
                    if c.name.lower() == name:
                        synopsis_characters.add(c.name)

        pov_characters = {co.pov_character for co in chapter_outlines}

        missing = synopsis_characters - pov_characters
        if missing:
            console.print(
                f"\n  [yellow]⚠ Synopsis-POV mismatch:[/yellow] "
                f"The synopsis mentions {', '.join(missing)} as key characters, "
                f"but they don't appear as POV characters in any chapter outline."
            )
            console.print(
                f"  POV characters in outlines: {', '.join(sorted(pov_characters))}"
            )
            logger.warning(
                "Synopsis-POV alignment issue: synopsis characters %s not in POV set %s",
                missing,
                pov_characters,
            )

    def _build_scene_breakdowns(
        self,
        system_prompt: str,
        novel_spec: NovelSpec,
        world_state: WorldState,
    ) -> None:
        """Generate scene breakdowns one chapter at a time to stay within token limits."""
        logger.info("Generating scene breakdowns (chapter by chapter) …")
        act_structure = self._load_act_structure()
        chapter_outlines = self._load_chapter_outlines() or []

        # Check for previously saved partial breakdowns
        existing_structure = self.state_manager.load_novel_structure()
        existing_breakdowns: list[SceneBreakdown] = []
        existing_chapters: set[int] = set()
        if existing_structure and existing_structure.scene_breakdowns:
            existing_breakdowns = list(existing_structure.scene_breakdowns)
            existing_chapters = {sb.chapter_number for sb in existing_breakdowns}

        all_breakdowns = list(existing_breakdowns)

        for chapter_outline in chapter_outlines:
            ch_num = chapter_outline.chapter_number
            if ch_num in existing_chapters:
                logger.info("Scene breakdown for chapter %d already exists, skipping", ch_num)
                continue

            console.print(f"    Scenes for chapter {ch_num}: {chapter_outline.title}")
            user_prompt = self.prompts.render_structure(
                sub_task="scene_breakdowns",
                novel_spec=novel_spec,
                world_state=world_state,
                act_structure=act_structure,
                chapter_outlines=[chapter_outline],
            )
            from sovereign_ink.models import SceneBreakdown as SBModel
            result: SceneBreakdownList = self.llm.generate_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=SceneBreakdownList,
                model=self.config.model_structural_planning,
                temperature=self.config.temperature_world_building,
            )

            for sb in result.scene_breakdowns:
                if sb.chapter_number not in existing_chapters:
                    all_breakdowns.append(sb)
                    existing_chapters.add(sb.chapter_number)

            # Save after each chapter for crash recovery
            self._save_partial_structure(scene_breakdowns=all_breakdowns)

        logger.info(
            "Saved scene breakdowns for %d chapters",
            len(all_breakdowns),
        )

    def _init_continuity_ledger(self, world_state: WorldState) -> None:
        """Create an initial ContinuityLedger from the chapter outlines and world state."""
        logger.info("Initialising continuity ledger …")
        chapter_outlines = self._load_chapter_outlines() or []

        # Timeline: one entry per chapter from its time_period
        timeline = [
            TimelineEntry(
                chapter=ch.chapter_number,
                date_in_story=ch.time_period,
                event=ch.chapter_goal,
            )
            for ch in chapter_outlines
        ]

        # Character knowledge: start each character with empty knowledge
        character_knowledge = [
            CharacterKnowledge(
                character_name=cp.name,
                knows=[],
                does_not_know=[],
            )
            for cp in world_state.characters
        ]

        # Political capital: initial snapshot based on character roles
        political_capital = [
            PoliticalCapital(
                character_name=cp.name,
                capital_level="initial",
                reason=f"Starting position as {cp.role}",
            )
            for cp in world_state.characters
        ]

        # Relationships: seed from character relationship lists
        relationships: list[RelationshipState] = []
        seen_pairs: set[tuple[str, str]] = set()
        for cp in world_state.characters:
            for rel in cp.relationships:
                pair = tuple(sorted([cp.name, rel.character_name]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    relationships.append(
                        RelationshipState(
                            character_a=cp.name,
                            character_b=rel.character_name,
                            state=rel.nature,
                            last_change_chapter=1,
                        )
                    )

        # Open threads: none initially — they emerge during prose generation
        open_threads: list[OpenThread] = []

        # Institutional posture: initial stance from institution power levels
        institutional_posture = {
            inst.name: f"{inst.power_level} — {inst.public_legitimacy}"
            for inst in world_state.institutions
        }

        ledger = ContinuityLedger(
            timeline=timeline,
            character_knowledge=character_knowledge,
            political_capital=political_capital,
            relationships=relationships,
            open_threads=open_threads,
            subplot_threads=[],
            institutional_posture=institutional_posture,
        )
        self.state_manager.save_continuity_ledger(ledger)
        logger.info(
            "Continuity ledger initialised (%d timeline entries, %d characters tracked)",
            len(timeline),
            len(character_knowledge),
        )

    def _assemble_structure(self) -> None:
        """Verify the full NovelStructure is persisted and log a summary."""
        structure = self.state_manager.load_novel_structure()
        if structure is None:
            raise RuntimeError("NovelStructure could not be loaded after assembly")

        enforce_contracts = (
            getattr(self.config, "enable_pressure_contracts", False)
            or getattr(self.config, "strict_pressure_contract_validation", False)
            or getattr(self.config, "contract_enforcement_mode", "safe") == "strict"
        )
        warnings = validate_pressure_architecture(
            structure,
            enforce_contracts=enforce_contracts,
            min_words_per_chapter=self.config.min_words_per_chapter,
            max_words_per_chapter=self.config.max_words_per_chapter,
        )
        if warnings:
            console.print(
                f"\n  [yellow]Pressure-architecture validation "
                f"({len(warnings)} warning(s)):[/yellow]"
            )
            for w in warnings:
                console.print(f"    [yellow]⚠ {w}[/yellow]")
            logger.warning(
                "Structure validation produced %d warnings", len(warnings)
            )
            # Warnings in pressure-architecture validation should only block
            # execution when the explicit structure gate is enabled.
            # Strict contract mode still applies to downstream chapter validation;
            # it should not auto-fail Stage 3 on non-fatal planning warnings.
            strict_structure = bool(
                getattr(self.config, "gate_strict_structure_validation", False)
            )
            if strict_structure:
                raise RuntimeError(
                    f"Strict structure validation failed with "
                    f"{len(warnings)} warning(s). "
                    "Set gate_strict_structure_validation=false to proceed."
                )

        total_scenes = sum(
            len(sb.scenes) for sb in structure.scene_breakdowns
        )
        total_words = sum(
            ch.estimated_word_count for ch in structure.chapter_outlines
        )
        logger.info(
            "Structural planning complete: %d acts, %d chapters, %d scenes, ~%d target words",
            structure.act_structure.num_acts,
            len(structure.chapter_outlines),
            total_scenes,
            total_words,
        )
        console.print(
            f"  [green]Structure ready:[/green] "
            f"{structure.act_structure.num_acts} acts, "
            f"{len(structure.chapter_outlines)} chapters, "
            f"{total_scenes} scenes, "
            f"~{total_words:,} target words"
        )
