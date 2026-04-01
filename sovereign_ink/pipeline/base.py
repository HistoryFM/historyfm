"""Base class for pipeline stages."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime

import sentry_sdk

from sovereign_ink.llm import LLMClient
from sovereign_ink.models import PipelineState, StageProgress, StageStatus
from sovereign_ink.prompts import PromptRenderer
from sovereign_ink.state import StateManager
from sovereign_ink.utils.config import GenerationConfig

logger = logging.getLogger(__name__)


class PipelineStage(ABC):
    """Abstract base for a single pipeline stage."""

    STAGE_NAME: str = ""

    def __init__(
        self,
        state_manager: StateManager,
        llm_client: LLMClient,
        prompt_renderer: PromptRenderer,
        config: GenerationConfig,
        pipeline_state: PipelineState,
    ):
        self.state_manager = state_manager
        self.llm = llm_client
        self.prompts = prompt_renderer
        self.config = config
        self.pipeline_state = pipeline_state

    def can_resume(self) -> bool:
        """Check if this stage has been partially completed and can resume."""
        progress = self.pipeline_state.stages.get(self.STAGE_NAME)
        if progress is None:
            return False
        return progress.status in (StageStatus.IN_PROGRESS, StageStatus.FAILED)

    def is_completed(self) -> bool:
        progress = self.pipeline_state.stages.get(self.STAGE_NAME)
        return progress is not None and progress.status == StageStatus.COMPLETED

    def _mark_started(self):
        """Mark this stage as started in pipeline state."""
        self.pipeline_state.stages[self.STAGE_NAME] = StageProgress(
            stage_name=self.STAGE_NAME,
            status=StageStatus.IN_PROGRESS,
            started_at=datetime.now(),
        )
        self.pipeline_state.current_stage = self.STAGE_NAME
        self.pipeline_state.last_updated = datetime.now()
        sentry_sdk.set_tag("stage_name", self.STAGE_NAME)
        self._save_pipeline_state()

    def _mark_completed(self):
        progress = self.pipeline_state.stages[self.STAGE_NAME]
        progress.status = StageStatus.COMPLETED
        progress.completed_at = datetime.now()
        self.pipeline_state.last_updated = datetime.now()
        self._save_pipeline_state()

    def _mark_failed(self, error: str):
        progress = self.pipeline_state.stages[self.STAGE_NAME]
        progress.status = StageStatus.FAILED
        progress.error_message = error
        progress.completed_at = datetime.now()
        self.pipeline_state.last_updated = datetime.now()
        sentry_sdk.set_tag("stage_name", self.STAGE_NAME)
        sentry_sdk.set_context("stage_failure", {
            "stage_name": self.STAGE_NAME,
            "error_message": error,
            "sub_step": progress.sub_step,
        })
        self._save_pipeline_state()

    def _update_sub_step(self, sub_step: str):
        self.pipeline_state.stages[self.STAGE_NAME].sub_step = sub_step
        self.pipeline_state.last_updated = datetime.now()
        self._save_pipeline_state()

    def _save_pipeline_state(self):
        self.pipeline_state.total_tokens_used = (
            self.llm.cumulative_input_tokens + self.llm.cumulative_output_tokens
        )
        self.pipeline_state.total_cost_estimate = self.llm.cumulative_cost
        self.state_manager.save_pipeline_state(self.pipeline_state)

    @abstractmethod
    def run(self) -> None:
        """Execute the stage."""
        ...

    @abstractmethod
    def check_prerequisites(self) -> bool:
        """Verify that all required predecessor artifacts exist."""
        ...
