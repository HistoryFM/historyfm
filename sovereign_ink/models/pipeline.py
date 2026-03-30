"""Pipeline models — stage tracking, drafts, revisions, and context summaries."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    """Possible states for a pipeline stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class ChapterStateStatus(str, Enum):
    """Contract-first states for per-chapter convergence."""

    DRAFTING = "drafting"
    DETERMINISTIC_VALIDATION = "deterministic_validation"
    SEMANTIC_VALIDATION = "semantic_validation"
    REPAIR = "repair"
    REVALIDATE = "revalidate"
    ACCEPTED = "accepted"


class StageProgress(BaseModel):
    """Progress record for a single pipeline stage."""

    stage_name: str = Field(..., description="Canonical name of the pipeline stage.")
    status: StageStatus = Field(
        default=StageStatus.PENDING,
        description="Current execution status.",
    )
    started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the stage began executing.",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the stage finished (success or failure).",
    )
    sub_step: Optional[str] = Field(
        default=None,
        description="Current sub-step within the stage (e.g. 'chapter_5', 'revision_pass_3').",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if the stage failed.",
    )


class PipelineState(BaseModel):
    """Top-level state of the entire novel-generation pipeline."""

    project_name: str = Field(..., description="Human-readable project name.")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the pipeline was initialised.",
    )
    last_updated: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of the most recent state change.",
    )
    current_stage: str = Field(
        ...,
        description="Name of the currently active pipeline stage.",
    )
    stages: dict[str, StageProgress] = Field(
        default_factory=dict,
        description="Mapping of stage name to its progress record.",
    )
    total_tokens_used: int = Field(
        default=0,
        ge=0,
        description="Cumulative token usage across all LLM calls.",
    )
    total_cost_estimate: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated cumulative cost in USD.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "project_name": "The Guillotine's Shadow",
                    "created_at": "2026-02-16T10:00:00",
                    "last_updated": "2026-02-16T12:30:00",
                    "current_stage": "chapter_generation",
                    "stages": {
                        "world_building": {
                            "stage_name": "world_building",
                            "status": "completed",
                            "started_at": "2026-02-16T10:00:00",
                            "completed_at": "2026-02-16T10:15:00",
                            "sub_step": None,
                            "error_message": None,
                        }
                    },
                    "total_tokens_used": 125000,
                    "total_cost_estimate": 3.75,
                }
            ]
        }
    }


class ChapterState(BaseModel):
    """Persisted acceptance and convergence state for a chapter."""

    chapter_number: int = Field(..., ge=1, description="1-indexed chapter number.")
    state: ChapterStateStatus = Field(
        default=ChapterStateStatus.DRAFTING,
        description="Current state in the contract-first chapter FSM.",
    )
    accepted: bool = Field(
        default=False,
        description="True only when all required acceptance checks have passed.",
    )
    accepted_draft_version: Optional[str] = Field(
        default=None,
        description="Draft version accepted as compliant (usually v3_polish).",
    )
    attempt_count: int = Field(
        default=0,
        ge=0,
        description="Number of convergence attempts performed for the chapter.",
    )
    last_failures: list[str] = Field(
        default_factory=list,
        description="Latest failed requirement identifiers/messages.",
    )
    last_updated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp of latest chapter state update.",
    )
    accepted_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when chapter reached accepted state.",
    )


class ChapterDraft(BaseModel):
    """A generated draft for a single chapter."""

    model_config = {"protected_namespaces": ()}

    chapter_number: int = Field(..., ge=1, description="1-indexed chapter number.")
    title: str = Field(..., description="Chapter title.")
    content: str = Field(..., description="Full markdown prose of the chapter.")
    word_count: int = Field(..., gt=0, description="Word count of the content.")
    pov_character: str = Field(..., description="Point-of-view character for this chapter.")
    generated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the draft was generated.",
    )
    model_used: str = Field(
        ...,
        description="Identifier of the LLM model used (e.g. 'claude-sonnet-4-20250514').",
    )
    tokens_used: int = Field(
        ...,
        ge=0,
        description="Tokens consumed to generate this draft.",
    )


class RevisionResult(BaseModel):
    """Result of a single revision pass on a chapter."""

    chapter_number: int = Field(..., ge=1, description="Chapter that was revised.")
    pass_number: int = Field(..., ge=1, description="1-indexed revision pass number.")
    pass_name: str = Field(
        ...,
        description="Name of the revision pass (e.g. 'continuity_check', 'style_polish').",
    )
    original_content: str = Field(
        ...,
        description="Chapter content before this revision pass.",
    )
    revised_content: str = Field(
        ...,
        description="Chapter content after this revision pass.",
    )
    changes_summary: str = Field(
        ...,
        description="Human-readable summary of changes made.",
    )
    generated_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the revision was completed.",
    )


class ContextSummary(BaseModel):
    """Rolling context summary used to maintain coherence across chapters."""

    chapter_number: int = Field(
        ...,
        ge=1,
        description="Chapter this summary was generated for.",
    )
    summary: str = Field(
        ...,
        description="Prose summary of what happened in the chapter.",
    )
    key_events: list[str] = Field(
        default_factory=list,
        description="Bullet-point list of key events.",
    )
    character_states: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of character name to their state at end of chapter.",
    )
