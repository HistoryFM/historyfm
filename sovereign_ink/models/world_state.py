"""World-state models — historical context, characters, institutions, and tone."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class HistoricalEvent(BaseModel):
    """A single notable event within the historical period."""

    date: str = Field(..., description="Date or date-range string (e.g. '14 July 1789').")
    event: str = Field(..., description="Short name or headline of the event.")
    significance: str = Field(..., description="Why this event matters to the narrative.")


class Relationship(BaseModel):
    """Directed relationship between two characters."""

    character_name: str = Field(..., description="Name of the other character.")
    nature: str = Field(..., description="Nature of the relationship (e.g. 'mentor', 'rival').")
    tension: str = Field(..., description="Source of tension or conflict in the relationship.")


class TitleTenure(BaseModel):
    """A single office or title held by a historical figure during a specific period."""

    title: str = Field(..., description="The office or title (e.g. 'Secretary of State').")
    held_from: str = Field(..., alias="from", description="Year they assumed this title.")
    held_to: str = Field(..., alias="to", description="Year they left this title (or 'present').")

    model_config = {"populate_by_name": True}


class MajorPlayer(BaseModel):
    """A historically significant figure in the narrative world."""

    name: str = Field(..., description="Full name of the historical figure.")
    role: str = Field(..., description="Their functional role (e.g. 'monarch', 'general').")
    position: str | None = Field(
        default=None,
        description="Legacy field — flat position string. Prefer 'titles' for new data.",
    )
    titles: list[TitleTenure] = Field(
        default_factory=list,
        description="Date-ranged titles/offices held by this figure.",
    )

    def title_at(self, year: int) -> str | None:
        """Return the title this figure held at *year*, or None."""
        for t in self.titles:
            try:
                from_y = int(t.held_from)
                to_y = 9999 if t.held_to.lower() == "present" else int(t.held_to)
                if from_y <= year <= to_y:
                    return t.title
            except (ValueError, AttributeError):
                continue
        return None

    def best_title(self, year: int | None = None) -> str:
        """Return the best available title string.

        If *year* is given and structured ``titles`` exist, return the
        date-specific title.  Otherwise fall back to the legacy
        ``position`` string or the generic ``role``.
        """
        if year is not None and self.titles:
            specific = self.title_at(year)
            if specific:
                return specific
        if self.position:
            return self.position
        return self.role


# ---------------------------------------------------------------------------
# Core world-building models
# ---------------------------------------------------------------------------

class HistoricalContext(BaseModel):
    """Broad historical backdrop for the novel."""

    era_description: str = Field(
        ...,
        description="Prose overview of the era and its defining characteristics.",
    )
    key_events: list[HistoricalEvent] = Field(
        default_factory=list,
        description="Ordered list of important events during the period.",
    )
    major_players: list[MajorPlayer] = Field(
        default_factory=list,
        description="Key historical figures active in the era.",
    )
    institutional_landscape: str = Field(
        ...,
        description="Overview of governing bodies, social structures, and power dynamics.",
    )
    macro_outcomes: list[str] = Field(
        default_factory=list,
        description="High-level outcomes the era is known for (used as guardrails).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "era_description": "Revolutionary France, 1789–1799 ...",
                    "key_events": [
                        {
                            "date": "14 July 1789",
                            "event": "Storming of the Bastille",
                            "significance": "Symbolic start of the Revolution.",
                        }
                    ],
                    "major_players": [
                        {
                            "name": "Maximilien Robespierre",
                            "role": "Political leader",
                            "titles": [
                                {
                                    "title": "Head of the Committee of Public Safety",
                                    "from": "1793",
                                    "to": "1794",
                                }
                            ],
                        }
                    ],
                    "institutional_landscape": "Monarchy collapsing; National Assembly ascendant ...",
                    "macro_outcomes": [
                        "Fall of the Ancien Régime",
                        "Rise and fall of the Terror",
                    ],
                }
            ]
        }
    }


class CharacterProfile(BaseModel):
    """Full psychological and narrative profile for a single character."""

    name: str = Field(..., description="Character's full name.")
    is_historical: bool = Field(
        ...,
        description="True if the character is a real historical figure.",
    )
    role: str = Field(
        ...,
        description="Narrative role (e.g. 'protagonist', 'antagonist', 'supporting').",
    )
    political_objective: str = Field(
        ...,
        description="What the character is trying to achieve politically.",
    )
    personal_fear: str = Field(
        ...,
        description="The character's deepest personal fear.",
    )
    hidden_motivation: str = Field(
        ...,
        description="True motivation the character conceals from others.",
    )
    emotional_blind_spot: str = Field(
        default="",
        description="Emotion or need the character persistently misreads in themselves.",
    )
    involuntary_tell: str = Field(
        default="",
        description="Behavior that leaks emotion despite the character's self-control.",
    )
    private_need_they_wont_name: str = Field(
        default="",
        description="Core private need the character refuses to articulate directly.",
    )
    moral_conflict: str = Field(
        ...,
        description="Central ethical dilemma the character faces.",
    )
    relationships: list[Relationship] = Field(
        default_factory=list,
        description="Relationships with other characters in the cast.",
    )
    emotional_arc: dict[str, str] = Field(
        ...,
        description="Mapping with keys 'start_state' and 'end_state' describing the character's emotional journey.",
    )
    voice_patterns: dict[str, str] = Field(
        ...,
        description="Mapping with keys 'speech_style', 'class_markers', and 'verbal_tics'.",
    )
    speech_fracture_profile: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Dialogue fracture tendencies with keys such as 'interruption_style', "
            "'evasive_fragments', and 'unfinished_thought_patterns'."
        ),
    )
    narrative_register: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "How the prose narrative voice shifts when this character is POV. "
            "Keys: 'sentence_rhythm' (e.g. 'long periodic with late subordination'), "
            "'diction_family' (e.g. 'architectural, botanical, Latinate'), "
            "'consciousness_style' (e.g. 'expansive, associative, naturalist'), "
            "'signature_lens' (the profession/obsession that shapes metaphor choice). "
            "Used to differentiate narrative voice per POV character beyond dialogue."
        ),
    )
    backstory_summary: str = Field(
        ...,
        description="Concise backstory leading up to the novel's opening.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Lucien Deveraux",
                    "is_historical": False,
                    "role": "protagonist",
                    "political_objective": "Secure a seat on the Committee of General Security.",
                    "personal_fear": "Being exposed as a moderate sympathiser.",
                    "hidden_motivation": "Protecting his imprisoned brother.",
                    "moral_conflict": "Must condemn allies to maintain cover.",
                    "relationships": [
                        {
                            "character_name": "Maximilien Robespierre",
                            "nature": "subordinate / reluctant admirer",
                            "tension": "Robespierre suspects Lucien's loyalty.",
                        }
                    ],
                    "emotional_arc": {
                        "start_state": "Idealistic and hopeful",
                        "end_state": "Disillusioned but resolute",
                    },
                    "voice_patterns": {
                        "speech_style": "Formal, Latinate phrasing with occasional passion.",
                        "class_markers": "Educated bourgeois diction.",
                        "verbal_tics": "Begins sentences with 'In truth…'",
                    },
                    "backstory_summary": "Son of a provincial lawyer who rose through the Jacobin ranks …",
                }
            ]
        }
    }


class Institution(BaseModel):
    """A political, military, or social institution active in the narrative world."""

    name: str = Field(..., description="Institution name.")
    type: str = Field(
        ...,
        description="Category (e.g. 'monarchy', 'parliament', 'military', 'church').",
    )
    power_level: str = Field(
        ...,
        description="Qualitative power assessment (e.g. 'dominant', 'waning', 'nascent').",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Structural or political constraints limiting the institution.",
    )
    factional_pressures: list[str] = Field(
        default_factory=list,
        description="Internal factions or external forces exerting pressure.",
    )
    public_legitimacy: str = Field(
        ...,
        description="How the public perceives the institution's right to govern or act.",
    )
    plausible_actions: list[str] = Field(
        default_factory=list,
        description="Actions the institution could realistically take in this era.",
    )
    implausible_actions: list[str] = Field(
        default_factory=list,
        description="Actions that would be historically implausible or anachronistic.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "Committee of Public Safety",
                    "type": "executive body",
                    "power_level": "dominant",
                    "constraints": [
                        "Requires Convention approval for major decrees",
                        "Dependent on sans-culotte street support",
                    ],
                    "factional_pressures": [
                        "Hébertists pushing for dechristianisation",
                        "Dantonists calling for clemency",
                    ],
                    "public_legitimacy": "High among urban radicals; resented in provinces.",
                    "plausible_actions": [
                        "Order arrests of suspected counter-revolutionaries",
                        "Requisition grain from provinces",
                    ],
                    "implausible_actions": [
                        "Abolish private property wholesale",
                        "Invade Britain with existing naval capacity",
                    ],
                }
            ]
        }
    }


class EraToneGuide(BaseModel):
    """Stylistic constraints to keep prose historically authentic."""

    language_register: str = Field(
        ...,
        description="Overall register (e.g. 'formal 18th-century literary English').",
    )
    vocabulary_constraints: list[str] = Field(
        default_factory=list,
        description="Rules for vocabulary usage to maintain period authenticity.",
    )
    forbidden_terms: list[str] = Field(
        default_factory=list,
        description="Modern words or phrases that must not appear in the prose.",
    )
    dialogue_style_guide: str = Field(
        ...,
        description="Guidance on how characters should speak.",
    )
    narrative_voice_calibration: str = Field(
        ...,
        description="Description of the desired third-person narrative voice.",
    )
    example_dialogue_snippets: list[str] = Field(
        default_factory=list,
        description="Short example exchanges that illustrate the target dialogue style.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "language_register": "Formal late-18th-century literary English.",
                    "vocabulary_constraints": [
                        "Prefer Latinate vocabulary for educated characters.",
                        "Use period-appropriate units (leagues, livres).",
                    ],
                    "forbidden_terms": [
                        "okay",
                        "guys",
                        "basically",
                        "agenda",
                        "impact (as verb)",
                    ],
                    "dialogue_style_guide": "Dialogue should reflect class: aristocrats use elaborate courtesy; sans-culottes favour blunt directness.",
                    "narrative_voice_calibration": "Close third-person, elevated but not purple; modelled on Hilary Mantel.",
                    "example_dialogue_snippets": [
                        '"Citizen, you would do well to reconsider your allegiances before the Committee reconsiders them for you."',
                    ],
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

class WorldState(BaseModel):
    """Complete world-building artefact aggregating all research outputs."""

    historical_context: HistoricalContext
    characters: list[CharacterProfile] = Field(
        default_factory=list,
        description="Full cast of characters with profiles.",
    )
    institutions: list[Institution] = Field(
        default_factory=list,
        description="Political and social institutions in the narrative world.",
    )
    era_tone_guide: EraToneGuide
