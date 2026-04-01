"""Stage 2: World Building — generate historical context, characters, institutions, and tone guide."""

from __future__ import annotations

import logging

import sentry_sdk
from pydantic import BaseModel
from rich.console import Console

from sovereign_ink.models import (
    CharacterProfile,
    EraToneGuide,
    HistoricalContext,
    Institution,
    NovelSpec,
    WorldState,
)
from sovereign_ink.pipeline.base import PipelineStage

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# Wrapper models for list-typed structured responses
# ---------------------------------------------------------------------------

class CharacterProfileList(BaseModel):
    """Wrapper so generate_structured can return a list of character profiles."""

    characters: list[CharacterProfile]


class InstitutionList(BaseModel):
    """Wrapper so generate_structured can return a list of institutions."""

    institutions: list[Institution]


# ---------------------------------------------------------------------------
# Sub-step registry (order matters for resume logic)
# ---------------------------------------------------------------------------

_SUB_STEPS = [
    "historical_context",
    "characters",
    "institutions",
    "era_tone_guide",
    "assemble_world_state",
]


class WorldBuildingStage(PipelineStage):
    """Build the full WorldState via four LLM calls + final assembly."""

    STAGE_NAME = "world_building"

    def check_prerequisites(self) -> bool:
        """Stage 1 must have produced a NovelSpec on disk."""
        return self.state_manager.load_novel_spec() is not None

    def run(self) -> None:
        self._mark_started()

        try:
            novel_spec: NovelSpec = self.state_manager.load_novel_spec()
            system_prompt = self.prompts.render_system_prompt()

            # Determine resume point
            start_idx = self._resume_index()

            for idx in range(start_idx, len(_SUB_STEPS)):
                step = _SUB_STEPS[idx]
                self._update_sub_step(step)
                console.print(f"  [cyan]World building:[/cyan] {step}")

                with sentry_sdk.start_span(op="world", name=f"world.{step}") as span:
                    span.set_data("sub_step", step)
                    if step == "historical_context":
                        self._build_historical_context(system_prompt, novel_spec)
                    elif step == "characters":
                        self._build_characters(system_prompt, novel_spec)
                    elif step == "institutions":
                        self._build_institutions(system_prompt, novel_spec)
                    elif step == "era_tone_guide":
                        self._build_era_tone_guide(system_prompt, novel_spec)
                    elif step == "assemble_world_state":
                        self._assemble_world_state()

            self._mark_completed()

        except Exception as exc:
            self._mark_failed(str(exc))
            raise

    # ------------------------------------------------------------------
    # Resume support
    # ------------------------------------------------------------------

    def _resume_index(self) -> int:
        """Determine the first sub-step that still needs to run."""
        if self.state_manager.load_historical_context() is None:
            return 0
        if self.state_manager.load_characters() is None:
            return 1
        if self.state_manager.load_institutions() is None:
            return 2
        if self.state_manager.load_era_tone_guide() is None:
            return 3
        # All individual artifacts exist; only assembly remains
        if self.state_manager.load_world_state() is None:
            return 4
        return len(_SUB_STEPS)

    # ------------------------------------------------------------------
    # Sub-step implementations
    # ------------------------------------------------------------------

    def _build_historical_context(
        self, system_prompt: str, novel_spec: NovelSpec
    ) -> None:
        logger.info("Generating historical context …")
        user_prompt = self.prompts.render_world_building(
            sub_task="historical_context",
            novel_spec=novel_spec,
        )
        result: HistoricalContext = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=HistoricalContext,
            model=self.config.model_world_building,
            temperature=self.config.temperature_world_building,
        )
        self.state_manager.save_historical_context(result)
        logger.info(
            "Historical context saved (%d events, %d major players)",
            len(result.key_events),
            len(result.major_players),
        )

    def _build_characters(
        self, system_prompt: str, novel_spec: NovelSpec
    ) -> None:
        logger.info("Generating character profiles …")
        historical_context = self.state_manager.load_historical_context()
        user_prompt = self.prompts.render_world_building(
            sub_task="characters",
            novel_spec=novel_spec,
            historical_context=historical_context,
        )
        result: CharacterProfileList = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=CharacterProfileList,
            model=self.config.model_world_building,
            temperature=self.config.temperature_world_building,
        )
        self.state_manager.save_characters(result.characters)
        logger.info("Saved %d character profiles", len(result.characters))

    def _build_institutions(
        self, system_prompt: str, novel_spec: NovelSpec
    ) -> None:
        logger.info("Generating institutions …")
        historical_context = self.state_manager.load_historical_context()
        user_prompt = self.prompts.render_world_building(
            sub_task="institutions",
            novel_spec=novel_spec,
            historical_context=historical_context,
        )
        result: InstitutionList = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=InstitutionList,
            model=self.config.model_world_building,
            temperature=self.config.temperature_world_building,
        )
        self.state_manager.save_institutions(result.institutions)
        logger.info("Saved %d institutions", len(result.institutions))

    def _build_era_tone_guide(
        self, system_prompt: str, novel_spec: NovelSpec
    ) -> None:
        logger.info("Generating era tone guide …")
        historical_context = self.state_manager.load_historical_context()
        user_prompt = self.prompts.render_world_building(
            sub_task="era_tone_guide",
            novel_spec=novel_spec,
            historical_context=historical_context,
        )
        result: EraToneGuide = self.llm.generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=EraToneGuide,
            model=self.config.model_world_building,
            temperature=self.config.temperature_world_building,
        )
        self.state_manager.save_era_tone_guide(result)
        logger.info("Era tone guide saved")

    def _assemble_world_state(self) -> None:
        """Load all sub-artifacts and persist the composite WorldState."""
        logger.info("Assembling WorldState …")
        world_state = WorldState(
            historical_context=self.state_manager.load_historical_context(),
            characters=self.state_manager.load_characters() or [],
            institutions=self.state_manager.load_institutions() or [],
            era_tone_guide=self.state_manager.load_era_tone_guide(),
        )
        self.state_manager.save_world_state(world_state)
        logger.info("WorldState assembled and saved")
