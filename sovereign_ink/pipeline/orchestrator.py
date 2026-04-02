"""Pipeline orchestrator — drives all six stages sequentially."""

from __future__ import annotations

import logging
import signal
from datetime import datetime
from pathlib import Path

import sentry_sdk

from sovereign_ink.llm import LLMClient
from sovereign_ink.models import PipelineState, StageProgress, StageStatus
from sovereign_ink.prompts import PromptRenderer
from sovereign_ink.state import StateManager
from sovereign_ink.utils.config import GenerationConfig, load_config

from sovereign_ink.pipeline.stages.stage1_setup import InteractiveSetupStage
from sovereign_ink.pipeline.stages.stage2_world_building import WorldBuildingStage
from sovereign_ink.pipeline.stages.stage3_structural_planning import (
    StructuralPlanningStage,
)
from sovereign_ink.pipeline.errors import ContractEnforcementError

logger = logging.getLogger(__name__)

STAGE_ORDER = [
    "interactive_setup",
    "world_building",
    "structural_planning",
    "prose_generation",
    "revision_pipeline",
    "assembly_export",
]

# Stages 4–6 are not yet implemented; we map only the available ones and will
# lazily import the rest when they exist.
_STAGE_CLASS_MAP: dict[str, type] = {
    "interactive_setup": InteractiveSetupStage,
    "world_building": WorldBuildingStage,
    "structural_planning": StructuralPlanningStage,
}


class PipelineOrchestrator:
    """Drives the six-stage novel generation pipeline."""

    def __init__(self, project_dir: Path, novel_spec=None):
        self.project_dir = Path(project_dir)
        self.config = self._load_merged_config()
        self.state_manager = StateManager(self.project_dir)
        self.llm = LLMClient(self.config)
        self.prompts = PromptRenderer()
        self._novel_spec = novel_spec
        self._interrupted = False

        # Load or create pipeline state
        saved = self.state_manager.load_pipeline_state()
        if saved:
            self.pipeline_state = PipelineState(**saved)
        else:
            project_name = (
                novel_spec.title
                if novel_spec and novel_spec.title
                else self.project_dir.name
            )
            self.pipeline_state = PipelineState(
                project_name=project_name,
                current_stage=STAGE_ORDER[0],
                stages={
                    name: StageProgress(stage_name=name, status=StageStatus.PENDING)
                    for name in STAGE_ORDER
                },
            )
            self.state_manager.save_pipeline_state(self.pipeline_state)

        # Setup SIGINT handler for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_interrupt)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_merged_config(self) -> GenerationConfig:
        """Load config from workspace root, then merge project-local overrides."""
        import yaml

        config = load_config(self.project_dir.parent)
        local_path = self.project_dir / "generation_config.yaml"
        if local_path.exists():
            with open(local_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            if isinstance(raw, dict):
                merged = config.model_dump()
                merged.update(raw)
                config = GenerationConfig(**merged)
                logger.info(
                    "Merged project-local config overrides from %s",
                    local_path,
                )
        return config

    def _handle_interrupt(self, signum, frame):
        logger.warning(
            "Interrupt received — saving state and shutting down gracefully"
        )
        self._interrupted = True
        self._save_state()
        raise KeyboardInterrupt("Pipeline interrupted by user")

    def _save_state(self):
        self.pipeline_state.total_tokens_used = (
            self.llm.cumulative_input_tokens + self.llm.cumulative_output_tokens
        )
        self.pipeline_state.total_cost_estimate = self.llm.cumulative_cost
        self.pipeline_state.last_updated = datetime.now()
        self.state_manager.save_pipeline_state(self.pipeline_state)

    def _resolve_stage_class(self, stage_name: str) -> type:
        """Return the stage class for *stage_name*, importing lazily if needed."""
        if stage_name in _STAGE_CLASS_MAP:
            return _STAGE_CLASS_MAP[stage_name]

        # Lazy imports for stages not yet implemented at module level
        if stage_name == "prose_generation":
            from sovereign_ink.pipeline.stages.stage4_prose_generation import (
                ProseGenerationStage,
            )

            return ProseGenerationStage
        if stage_name == "revision_pipeline":
            from sovereign_ink.pipeline.stages.stage5_revision import (
                RevisionPipelineStage,
            )

            return RevisionPipelineStage
        if stage_name == "assembly_export":
            from sovereign_ink.pipeline.stages.stage6_assembly import (
                AssemblyExportStage,
            )

            return AssemblyExportStage

        raise ValueError(f"Unknown stage: {stage_name}")

    def _create_stage(self, stage_name: str):
        """Create a stage instance by name."""
        cls = self._resolve_stage_class(stage_name)
        stage = cls(
            state_manager=self.state_manager,
            llm_client=self.llm,
            prompt_renderer=self.prompts,
            config=self.config,
            pipeline_state=self.pipeline_state,
        )
        # Pass novel_spec to setup stage if available
        if stage_name == "interactive_setup" and self._novel_spec:
            stage.novel_spec = self._novel_spec
        return stage

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self, start_from: str | None = None, stop_after: str | None = None):
        """Run the pipeline from the beginning or resume from a stage.

        Parameters
        ----------
        start_from:
            If provided, skip all stages before this one.  Otherwise the
            orchestrator resumes from the first non-completed stage.
        stop_after:
            If provided, stop after completing this stage instead of
            running through all remaining stages.
        """
        logger.info(
            "Starting pipeline for project: %s",
            self.pipeline_state.project_name,
        )

        # Determine starting point
        if start_from:
            if start_from not in STAGE_ORDER:
                raise ValueError(
                    f"Unknown stage '{start_from}'. "
                    f"Valid stages: {', '.join(STAGE_ORDER)}"
                )
            start_idx = STAGE_ORDER.index(start_from)
        else:
            # Find first non-completed stage
            start_idx = 0
            for i, name in enumerate(STAGE_ORDER):
                progress = self.pipeline_state.stages.get(name)
                if progress and progress.status == StageStatus.COMPLETED:
                    start_idx = i + 1
                else:
                    break

        # Determine stopping point
        if stop_after:
            if stop_after not in STAGE_ORDER:
                raise ValueError(
                    f"Unknown stage '{stop_after}'. "
                    f"Valid stages: {', '.join(STAGE_ORDER)}"
                )
            stop_idx = STAGE_ORDER.index(stop_after)
        else:
            stop_idx = len(STAGE_ORDER) - 1

        for i in range(start_idx, stop_idx + 1):
            if self._interrupted:
                break

            stage_name = STAGE_ORDER[i]
            stage = self._create_stage(stage_name)

            # Skip completed stages
            if stage.is_completed():
                logger.info("Skipping completed stage: %s", stage_name)
                continue

            # Check prerequisites
            if not stage.check_prerequisites():
                logger.error("Prerequisites not met for stage: %s", stage_name)
                raise RuntimeError(
                    f"Prerequisites not met for stage: {stage_name}"
                )

            if stage_name in {"revision_pipeline", "assembly_export"}:
                structure = self.state_manager.load_novel_structure()
                if structure is not None:
                    unaccepted = self.state_manager.get_next_unaccepted_chapter(
                        len(structure.chapter_outlines)
                    )
                    if unaccepted is not None:
                        raise RuntimeError(
                            "Cannot advance pipeline while chapter "
                            f"{unaccepted} is not accepted."
                        )

            logger.info("=== Starting stage: %s ===", stage_name)
            sentry_sdk.set_tag("stage_name", stage_name)
            sentry_sdk.set_context("pipeline", {
                "project_name": self.pipeline_state.project_name,
                "current_stage": stage_name,
                "total_tokens": self.pipeline_state.total_tokens_used,
                "total_cost": self.pipeline_state.total_cost_estimate,
            })
            sentry_sdk.logger.info(
                "Pipeline stage {stage} started",
                stage=stage_name,
                project=self.pipeline_state.project_name,
            )
            try:
                with sentry_sdk.start_span(op="stage", name=f"stage.{stage_name}") as span:
                    span.set_data("project", self.pipeline_state.project_name)
                    stage.run()
                logger.info("=== Completed stage: %s ===", stage_name)
                sentry_sdk.logger.info(
                    "Pipeline stage {stage} completed",
                    stage=stage_name,
                    project=self.pipeline_state.project_name,
                    total_cost=round(self.llm.cumulative_cost, 4),
                )
            except KeyboardInterrupt:
                logger.warning(
                    "Pipeline interrupted during stage: %s", stage_name
                )
                raise
            except ContractEnforcementError as e:
                sentry_sdk.set_tag("chapter_number", str(e.chapter_number))
                sentry_sdk.set_tag("error_code", e.error_code)
                sentry_sdk.capture_exception(e)
                logger.error(
                    "Contract enforcement failure in stage %s (chapter=%s, code=%s): %s",
                    stage_name,
                    e.chapter_number,
                    e.error_code,
                    str(e),
                )
                raise
            except Exception as e:
                logger.error("Stage %s failed: %s", stage_name, str(e))
                raise

        self._save_state()
        logger.info(
            "Pipeline complete! Total cost: $%.4f", self.llm.cumulative_cost
        )

    def get_status(self) -> dict:
        """Return a summary of pipeline status."""
        return {
            "project_name": self.pipeline_state.project_name,
            "current_stage": self.pipeline_state.current_stage,
            "stages": {
                name: {
                    "status": progress.status.value,
                    "sub_step": progress.sub_step,
                    "started_at": (
                        str(progress.started_at) if progress.started_at else None
                    ),
                    "completed_at": (
                        str(progress.completed_at)
                        if progress.completed_at
                        else None
                    ),
                }
                for name, progress in self.pipeline_state.stages.items()
            },
            "total_tokens": self.pipeline_state.total_tokens_used,
            "total_cost": f"${self.pipeline_state.total_cost_estimate:.4f}",
        }

    def cleanup(self):
        """Release resources."""
        self.state_manager.release_lock()
