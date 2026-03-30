"""Continuity-tracking models — timeline, knowledge, political capital, relationships, threads."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class TimelineEntry(BaseModel):
    """A single event pinned to the in-story timeline."""

    chapter: int = Field(..., ge=1, description="Chapter in which the event occurs.")
    date_in_story: str = Field(
        ...,
        description="In-story date or date-range (e.g. '14 July 1789').",
    )
    event: str = Field(..., description="Brief description of the event.")


class CharacterKnowledge(BaseModel):
    """Tracks what a character knows and doesn't know at a given point."""

    character_name: str = Field(..., description="Name of the character.")
    knows: list[str] = Field(
        default_factory=list,
        description="Facts or secrets the character is aware of.",
    )
    does_not_know: list[str] = Field(
        default_factory=list,
        description="Facts or secrets the character is unaware of.",
    )


class PoliticalCapital(BaseModel):
    """Snapshot of a character's political standing."""

    character_name: str = Field(..., description="Name of the character.")
    capital_level: str = Field(
        ...,
        description="Qualitative level (e.g. 'rising', 'peak', 'declining', 'collapsed').",
    )
    reason: str = Field(
        ...,
        description="Explanation for the current capital level.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "character_name": "Lucien Deveraux",
                    "capital_level": "rising",
                    "reason": "Successfully denounced a royalist conspiracy, earning Jacobin favour.",
                }
            ]
        }
    }


class RelationshipState(BaseModel):
    """Point-in-time state of the relationship between two characters."""

    character_a: str = Field(..., description="First character.")
    character_b: str = Field(..., description="Second character.")
    state: str = Field(
        ...,
        description="Current relationship state (e.g. 'allied', 'hostile', 'suspicious', 'dependent').",
    )
    last_change_chapter: int = Field(
        ...,
        ge=1,
        description="Chapter in which this relationship last changed.",
    )


class OpenThread(BaseModel):
    """A narrative thread that may be open, resolved, or abandoned."""

    thread_id: str = Field(..., description="Unique identifier for the thread.")
    description: str = Field(..., description="What the thread is about.")
    introduced_chapter: int = Field(
        ...,
        ge=1,
        description="Chapter in which the thread was introduced.",
    )
    resolved_chapter: Optional[int] = Field(
        default=None,
        ge=1,
        description="Chapter in which the thread was resolved, if applicable.",
    )
    status: Literal["open", "resolved", "abandoned"] = Field(
        default="open",
        description="Current disposition of the thread.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "thread_id": "stolen_letters",
                    "description": "Compromising letters stolen from Lucien's study; their contents could expose his brother.",
                    "introduced_chapter": 3,
                    "resolved_chapter": None,
                    "status": "open",
                }
            ]
        }
    }


class SubplotThread(BaseModel):
    """Entertainment-focused subplot thread status tracker."""

    thread_id: str = Field(..., description="Unique subplot identifier.")
    description: str = Field(..., description="What this subplot thread is about.")
    driving_character: str = Field(
        ...,
        description="Primary non-POV or supporting character driving this thread.",
    )
    status: Literal["latent", "active", "exploding"] = Field(
        default="latent",
        description="Escalation level for subplot pressure.",
    )
    last_advanced_chapter: int = Field(
        ...,
        ge=1,
        description="Most recent chapter where this subplot changed state.",
    )


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

class ContinuityLedger(BaseModel):
    """Master ledger tracking all continuity-sensitive state across the novel."""

    timeline: list[TimelineEntry] = Field(
        default_factory=list,
        description="Chronological list of in-story events.",
    )
    character_knowledge: list[CharacterKnowledge] = Field(
        default_factory=list,
        description="Knowledge state for each character.",
    )
    political_capital: list[PoliticalCapital] = Field(
        default_factory=list,
        description="Political capital snapshots for tracked characters.",
    )
    relationships: list[RelationshipState] = Field(
        default_factory=list,
        description="Current state of inter-character relationships.",
    )
    open_threads: list[OpenThread] = Field(
        default_factory=list,
        description="Active, resolved, and abandoned narrative threads.",
    )
    subplot_threads: list[SubplotThread] = Field(
        default_factory=list,
        description="Supporting-cast subplot pressure tracker.",
    )
    institutional_posture: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of institution name to its current posture or stance.",
    )
