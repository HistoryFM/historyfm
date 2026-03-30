"""NovelSpec model — captures user input from the interactive setup wizard."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class NovelSpec(BaseModel):
    """Top-level specification provided by the user to seed the novel pipeline."""

    title: Optional[str] = Field(
        default=None,
        description="Working title for the novel. May be generated later if omitted.",
    )
    era_start: int = Field(
        ...,
        ge=1700,
        le=1900,
        description="Start year of the historical era (1700–1900).",
    )
    era_end: int = Field(
        ...,
        ge=1700,
        le=1900,
        description="End year of the historical era (1700–1900).",
    )
    region: str = Field(
        ...,
        min_length=1,
        description="Geographic region or country (e.g. 'France', 'United States').",
    )
    central_event: str = Field(
        ...,
        min_length=1,
        description="The pivotal historical event the novel revolves around.",
    )
    tone_intensity: Literal["dramatic", "highly_dramatic", "restrained_dramatic"] = (
        Field(
            ...,
            description="Desired dramatic register for the narrative voice.",
        )
    )
    pov_count: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Number of point-of-view characters (1–4).",
    )
    protagonist_type: Literal["historical_figure", "fictional_character", "both"] = (
        Field(
            ...,
            description="Whether the protagonist(s) are historical, fictional, or a mix.",
        )
    )
    thematic_focus: list[str] = Field(
        ...,
        min_length=1,
        description="Core thematic tensions explored in the novel.",
    )
    desired_length: Literal["novella_50k", "novel_120k"] = Field(
        ...,
        description="Target word-count tier.",
    )
    synopsis: Optional[str] = Field(
        default=None,
        description="User-approved narrative synopsis that seeds world building and structural planning.",
    )
    additional_notes: Optional[str] = Field(
        default=None,
        description="Free-form notes or constraints from the user.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "title": "The Guillotine's Shadow",
                    "era_start": 1789,
                    "era_end": 1799,
                    "region": "France",
                    "central_event": "The French Revolution and the Terror",
                    "tone_intensity": "highly_dramatic",
                    "pov_count": 3,
                    "protagonist_type": "both",
                    "thematic_focus": [
                        "loyalty vs ambition",
                        "idealism vs pragmatism",
                    ],
                    "desired_length": "novel_120k",
                    "additional_notes": "Focus on the Girondins vs Jacobins struggle.",
                }
            ]
        }
    }
