"""Structural models — acts, chapters, scenes, and the overall novel blueprint."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Valid value enumerations for pressure-architecture fields
# ---------------------------------------------------------------------------

VALID_ENDING_MODES = (
    "cliffhanger_action",
    "reversal_reveal",
    "arrival_of_threat",
    "moral_breach",
    "relationship_rupture",
    "public_countdown",
    # Phase 5: ending variation modes
    "mid_action",           # scene ends mid-way through an incomplete action
    "mundane_detail",       # scene ends on a concrete non-symbolic detail
    "comic_beat",           # scene ends on a wry or humorous note
    "sensory_non_symbolic", # scene ends on pure sensory impression without thematic freight
    "bureaucratic_pivot",   # scene ends with a procedural/administrative turn
)

VALID_REGISTERS = (
    "solemn",
    "wry",
    "urgent",
    "intimate",
    "ceremonial",
    "combative",
    "reflective",
    "sardonic",
    "grieving",
    "elated",
    "conspiratorial",
    "neutral",
)

VALID_GATE_PROFILES = (
    "external_collision",
    "institutional_pressure",
    "internal_conflict",
)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class Act(BaseModel):
    """A single dramatic act within the novel's macro-structure."""

    act_number: int = Field(..., ge=1, description="1-indexed act number.")
    title: str = Field(..., description="Thematic title for the act.")
    description: str = Field(..., description="Narrative purpose and arc of this act.")
    dramatic_beats: list[str] = Field(
        default_factory=list,
        description="Key dramatic beats that must occur in this act.",
    )
    stakes_level: str = Field(
        ...,
        description="Qualitative stakes descriptor (e.g. 'personal', 'national', 'existential').",
    )
    chapters: list[int] = Field(
        default_factory=list,
        description="Ordered list of chapter indices belonging to this act.",
    )


class DialogueDynamics(BaseModel):
    """What each character wants, hides, and how power shifts during a scene's dialogue."""

    character_a_wants: str = Field(
        ...,
        description="What the first speaking character wants from this conversation — their hidden objective, not what they say.",
    )
    character_b_wants: str = Field(
        ...,
        description="What the second speaking character wants from this conversation.",
    )
    character_a_hides: str = Field(
        ...,
        description="What the first character is concealing or reluctant to reveal.",
    )
    character_b_hides: str = Field(
        ...,
        description="What the second character is concealing or reluctant to reveal.",
    )
    power_shift: str = Field(
        ...,
        description="How power dynamics change during the exchange — who starts with leverage and who gains it.",
    )
    subtext: str = Field(
        ...,
        description="What the conversation is really about underneath the surface topic.",
    )


class Scene(BaseModel):
    """A single scene within a chapter."""

    scene_number: int = Field(..., ge=1, description="1-indexed scene number within the chapter.")
    pov: str = Field(..., description="Point-of-view character for this scene.")
    setting: str = Field(..., description="Physical location of the scene.")
    goal: str = Field(..., description="What the POV character is trying to accomplish.")
    opposition: str = Field(..., description="The obstacle or opposing force in this scene.")
    immediate_risk: str = Field(
        default="",
        description=(
            "Immediate jeopardy inside the scene. What can be lost right now if the "
            "POV character fails before the scene midpoint."
        ),
    )
    irreversible_cost_if_fail: str = Field(
        default="",
        description=(
            "Irreversible damage if the scene objective fails (reputation, leverage, "
            "relationship, safety, legal exposure, etc.)."
        ),
    )
    power_shift_target: str = Field(
        default="",
        description=(
            "Who should end the scene with more leverage than they began with."
        ),
    )
    turn: str = Field(
        ...,
        description="The pivotal moment that shifts the scene's direction.",
    )
    consequences: str = Field(
        ...,
        description="What changes as a result of this scene.",
    )
    emotional_beat: str = Field(
        ...,
        description="The dominant emotional note the scene should strike.",
    )
    continuity_notes: str = Field(
        default="",
        description="Notes for the continuity checker (props, timeline, character knowledge).",
    )
    complexity_score: int = Field(
        ...,
        ge=1,
        le=10,
        description="Estimated writing complexity (1 = straightforward, 10 = very demanding).",
    )
    register: str = Field(  # noqa: Pydantic shadow warning is harmless here
        default="neutral",
        description=(
            "Tonal register for this scene. One of: solemn, wry, urgent, "
            "intimate, ceremonial, combative, reflective, sardonic, grieving, "
            "elated, conspiratorial, neutral. Controls prose tone variation "
            "across the chapter."
        ),
    )
    dialogue_dynamics: DialogueDynamics | None = Field(
        default=None,
        description=(
            "For scenes with significant dialogue: what each character wants, "
            "what they hide, how power shifts, and the subtext beneath the surface. "
            "Forces dialogue to be written as power negotiation, not information delivery."
        ),
    )
    supporting_cast_pressure: str = Field(
        default="",
        description=(
            "How a non-POV character agenda pressures, complicates, or redirects this scene."
        ),
    )

    # --- Pressure contract fields (Phase 1) ---

    gate_profile: str = Field(
        default="external_collision",
        description=(
            "Scene pressure type: external_collision (adversary physically "
            "present), institutional_pressure (career/political/legal risk "
            "from an identifiable actor), or internal_conflict (moral/"
            "philosophical opposition with relaxed on-page collision "
            "requirements). Controls which gate checks apply."
        ),
    )
    opponent_present_on_page: bool = Field(
        default=True,
        description=(
            "Whether an opposing actor is physically present in the scene. "
            "Must be True for external_collision; may be False for "
            "internal_conflict scenes."
        ),
    )
    opponent_actor: str = Field(
        default="",
        description=(
            "The specific entity (person, delegation, document-as-proxy) "
            "providing opposition in this scene."
        ),
    )
    opponent_move: str = Field(
        default="",
        description=(
            "The concrete adversarial action the opponent takes on-page — "
            "a refusal, demand, accusation, threat, procedural block, "
            "document delivery, or physical obstruction. Must be "
            "observable, not abstract."
        ),
    )
    pov_countermove: str = Field(
        default="",
        description=(
            "The concrete response the POV character takes against the "
            "opponent's move — a counter-demand, lie, redirect, refusal, "
            "or tactical concession. Must be an action verb, not a thought."
        ),
    )
    failure_event_if_no_action: str = Field(
        default="",
        description=(
            "What observable consequence occurs within this scene if the "
            "POV character fails to act. Must be concrete and immediate, "
            "not a future conditional."
        ),
    )
    deadline_or_clock: str = Field(
        default="",
        description=(
            "Time pressure operating in this scene — a vote at dawn, a "
            "ship sailing at tide, a courier departing within the hour. "
            "Empty string if no explicit clock."
        ),
    )
    required_end_hook: str = Field(
        default="",
        description=(
            "For the terminal scene of a chapter: the specific unresolved "
            "external pressure that must remain open at scene end to "
            "propel the reader into the next chapter. Empty for non-terminal "
            "scenes."
        ),
    )

    # --- Craft contract fields (Phase 4) ---

    dominant_sense: str = Field(
        default="",
        description=(
            "Which non-visual sense anchors this scene (smell, taste, touch, "
            "sound, temperature). Forces sensory grounding beyond the visual "
            "default. Empty string means no specific sense is mandated."
        ),
    )
    externalization_gesture: str = Field(
        default="",
        description=(
            "The specific physical action that reveals the POV character's "
            "emotional state without narrator explanation. Must be an observable "
            "behavior (e.g., 'folds and refolds the letter', 'sets the glass "
            "down without drinking'). Empty string means no gesture is mandated."
        ),
    )
    physical_interruption: str = Field(
        default="",
        description=(
            "A moment where the body intrudes on thought — hunger, discomfort, "
            "an irrelevant noise that breaks concentration, a hand cramp, an itch, "
            "a need to relieve oneself. Must NOT be symbolic and must NOT be "
            "rationalized as thematically meaningful. Pure irreducible texture of "
            "being alive in this era. Examples: 'hand cramp forces him to set down "
            "the quill mid-sentence', 'stomach growls loudly during the treaty "
            "reading'. Empty string means no interruption is mandated."
        ),
    )


# ---------------------------------------------------------------------------
# Core structural models
# ---------------------------------------------------------------------------

class ActStructure(BaseModel):
    """The macro act-level structure of the novel."""

    num_acts: int = Field(
        ...,
        ge=3,
        le=4,
        description="Number of acts (3 or 4).",
    )
    acts: list[Act] = Field(
        default_factory=list,
        description="Ordered list of acts.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "num_acts": 3,
                    "acts": [
                        {
                            "act_number": 1,
                            "title": "The Spark",
                            "description": "Introduce the world on the brink; establish POV characters and their stakes.",
                            "dramatic_beats": [
                                "Inciting incident at the Estates-General",
                                "First betrayal",
                            ],
                            "stakes_level": "personal",
                            "chapters": [1, 2, 3, 4],
                        }
                    ],
                }
            ]
        }
    }


class ChapterOutline(BaseModel):
    """High-level outline for a single chapter."""

    chapter_number: int = Field(..., ge=1, description="1-indexed chapter number.")
    title: str = Field(..., description="Chapter title.")
    pov_character: str = Field(..., description="Point-of-view character for this chapter.")
    setting: str = Field(..., description="Primary physical setting.")
    time_period: str = Field(
        ...,
        description="In-story date or date-range for the chapter.",
    )
    political_context: str = Field(
        ...,
        description="Political situation at the start of this chapter.",
    )
    chapter_goal: str = Field(
        ...,
        description="What this chapter must accomplish narratively.",
    )
    conflict: str = Field(
        ...,
        description="Central conflict or tension driving the chapter.",
    )
    turn: str = Field(
        ...,
        description="The key turning point or revelation.",
    )
    consequences: str = Field(
        ...,
        description="State changes resulting from the chapter's events.",
    )
    hard_reveal: str = Field(
        default="",
        description=(
            "A concrete reveal that materially reinterprets prior assumptions."
        ),
    )
    soft_reversal: str = Field(
        default="",
        description=(
            "A subtler reversal that changes expected momentum or alignment."
        ),
    )
    on_page_opposing_move: str = Field(
        default="",
        description=(
            "Specific opposing action that happens on-page, not just reported."
        ),
    )
    ending_mode: str = Field(
        default="",
        description=(
            "Ending taxonomy target: cliffhanger_action, reversal_reveal, "
            "arrival_of_threat, moral_breach, relationship_rupture, public_countdown, "
            "mid_action, mundane_detail, comic_beat, sensory_non_symbolic, or "
            "bureaucratic_pivot."
        ),
    )
    petty_moment: str = Field(
        default="",
        description=(
            "A moment of vanity, jealousy, or triviality that the narrative must NOT "
            "rationalize, contextualize as strategic, or redeem. The character is petty "
            "and the narrative does not explain it away. Examples: 'Livingston is quietly "
            "pleased his French is better than Monroe's and dwells on it longer than the "
            "situation warrants', 'Jefferson resents that Hamilton's portrait is better lit "
            "in the hallway and notes this without irony'. Empty string means no petty "
            "moment is mandated for this chapter."
        ),
    )
    estimated_word_count: int = Field(
        ...,
        gt=0,
        description="Target word count for this chapter.",
    )
    act_number: int = Field(
        ...,
        ge=1,
        description="Which act this chapter belongs to.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "chapter_number": 1,
                    "title": "The Estates-General",
                    "pov_character": "Lucien Deveraux",
                    "setting": "Versailles, Salle des Menus Plaisirs",
                    "time_period": "5 May 1789",
                    "political_context": "The three estates convene; Third Estate chafes under procedural restrictions.",
                    "chapter_goal": "Establish Lucien's idealism and introduce core political tension.",
                    "conflict": "Lucien clashes with an aristocratic delegate blocking Third Estate demands.",
                    "turn": "Lucien discovers his mentor is secretly negotiating with the Crown.",
                    "consequences": "Lucien's trust in the moderate faction is shaken.",
                    "estimated_word_count": 4500,
                    "act_number": 1,
                }
            ]
        }
    }


class SceneBreakdown(BaseModel):
    """Scene-level breakdown for a chapter."""

    chapter_number: int = Field(..., ge=1, description="Chapter this breakdown belongs to.")
    scenes: list[Scene] = Field(
        default_factory=list,
        description="Ordered list of scenes in the chapter.",
    )

    @model_validator(mode="after")
    def _check_scene_integrity(self) -> "SceneBreakdown":
        if not self.scenes:
            return self
        for i, scene in enumerate(self.scenes):
            if scene.scene_number != i + 1:
                scene.scene_number = i + 1
        return self


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

class NovelStructure(BaseModel):
    """Complete structural blueprint for the novel."""

    act_structure: ActStructure
    chapter_outlines: list[ChapterOutline] = Field(
        default_factory=list,
        description="Ordered chapter outlines.",
    )
    scene_breakdowns: list[SceneBreakdown] = Field(
        default_factory=list,
        description="Scene breakdowns keyed by chapter number.",
    )


# ---------------------------------------------------------------------------
# Pressure-architecture validation
# ---------------------------------------------------------------------------

_ABSTRACT_OPPOSITION_MARKERS = (
    "his own", "her own", "their own", "the argument itself",
    "his convictions", "her convictions", "his principles",
    "the letter itself", "the despatch itself", "the document itself",
)


def validate_pressure_architecture(
    structure: NovelStructure,
    *,
    enforce_contracts: bool = False,
    min_words_per_chapter: int = 2000,
    max_words_per_chapter: int = 4500,
    max_scenes_per_chapter: int = 6,
) -> list[str]:
    """Validate that all pressure-architecture fields are properly specified.

    When *enforce_contracts* is True, the stricter pressure-contract fields
    (opponent_move, pov_countermove, failure_event_if_no_action, etc.) are
    also validated, and abstract-only opposition is rejected for
    non-internal_conflict scenes.

    Returns a list of warning strings.  Empty list means the structure passes.
    """
    warnings: list[str] = []

    for co in structure.chapter_outlines:
        ch = co.chapter_number
        if not (co.on_page_opposing_move or "").strip():
            warnings.append(
                f"Chapter {ch}: on_page_opposing_move is empty — "
                "every chapter must declare a concrete adversarial action"
            )
        if not (co.ending_mode or "").strip():
            warnings.append(f"Chapter {ch}: ending_mode is empty")
        elif co.ending_mode.strip() not in VALID_ENDING_MODES:
            warnings.append(
                f"Chapter {ch}: ending_mode '{co.ending_mode}' is not a "
                f"recognised taxonomy value ({', '.join(VALID_ENDING_MODES)})"
            )
        # Word count bounds check
        if co.estimated_word_count > max_words_per_chapter:
            warnings.append(
                f"Chapter {ch}: estimated_word_count {co.estimated_word_count} "
                f"exceeds maximum {max_words_per_chapter} — chapter will be "
                "expensive to revise and prone to repetition"
            )
        if co.estimated_word_count < min_words_per_chapter:
            warnings.append(
                f"Chapter {ch}: estimated_word_count {co.estimated_word_count} "
                f"is below minimum {min_words_per_chapter}"
            )

    scene_chapters = {sb.chapter_number for sb in structure.scene_breakdowns}
    for co in structure.chapter_outlines:
        if co.chapter_number not in scene_chapters:
            warnings.append(
                f"Chapter {co.chapter_number}: missing scene breakdown"
            )

    for sb in structure.scene_breakdowns:
        ch = sb.chapter_number
        if len(sb.scenes) < 2:
            warnings.append(
                f"Chapter {ch}: only {len(sb.scenes)} scene(s), minimum is 2"
            )
        if len(sb.scenes) > max_scenes_per_chapter:
            warnings.append(
                f"Chapter {ch}: {len(sb.scenes)} scenes exceeds recommended "
                f"maximum of {max_scenes_per_chapter} — too many scenes inflate "
                "word count and revision cost"
            )
        if len(sb.scenes) > 8:
            warnings.append(
                f"Chapter {ch}: {len(sb.scenes)} scenes exceeds hard maximum of 8"
            )

        for scene in sb.scenes:
            s = scene.scene_number
            if not (scene.immediate_risk or "").strip():
                warnings.append(
                    f"Chapter {ch}, scene {s}: immediate_risk is empty — "
                    "must specify what can be lost right now"
                )
            if not (scene.irreversible_cost_if_fail or "").strip():
                warnings.append(
                    f"Chapter {ch}, scene {s}: irreversible_cost_if_fail is "
                    "empty — must specify permanent consequence"
                )
            if not (scene.power_shift_target or "").strip():
                warnings.append(
                    f"Chapter {ch}, scene {s}: power_shift_target is empty"
                )
            if scene.register and scene.register not in VALID_REGISTERS:
                warnings.append(
                    f"Chapter {ch}, scene {s}: register '{scene.register}' "
                    f"not in valid set"
                )

            if not enforce_contracts:
                continue

            # --- Pressure-contract enforcement ---

            profile = (scene.gate_profile or "external_collision").strip()
            if profile and profile not in VALID_GATE_PROFILES:
                warnings.append(
                    f"Chapter {ch}, scene {s}: gate_profile "
                    f"'{profile}' not in {VALID_GATE_PROFILES}"
                )

            is_internal = profile == "internal_conflict"

            if not is_internal:
                if not (scene.opponent_actor or "").strip():
                    warnings.append(
                        f"Chapter {ch}, scene {s}: opponent_actor is empty — "
                        "non-internal scenes must name a specific opposing entity"
                    )
                if not (scene.opponent_move or "").strip():
                    warnings.append(
                        f"Chapter {ch}, scene {s}: opponent_move is empty — "
                        "must specify a concrete adversarial action"
                    )
                if not (scene.pov_countermove or "").strip():
                    warnings.append(
                        f"Chapter {ch}, scene {s}: pov_countermove is empty — "
                        "must specify a concrete POV response"
                    )

                # Reject purely abstract opposition for collision/pressure scenes
                opposition_text = (scene.opposition or "").strip().lower()
                if opposition_text and all(
                    marker in opposition_text
                    for marker in [opposition_text]
                    if any(
                        opposition_text.startswith(m)
                        for m in _ABSTRACT_OPPOSITION_MARKERS
                    )
                ):
                    warnings.append(
                        f"Chapter {ch}, scene {s}: opposition appears purely "
                        f"abstract ('{opposition_text[:60]}…') — "
                        "external_collision / institutional_pressure scenes "
                        "need a concrete adversary"
                    )

            if not (scene.failure_event_if_no_action or "").strip():
                warnings.append(
                    f"Chapter {ch}, scene {s}: failure_event_if_no_action is "
                    "empty — must describe an observable in-scene consequence"
                )

            # Terminal-scene end-hook enforcement
            is_terminal = scene.scene_number == len(sb.scenes)
            if is_terminal and not (scene.required_end_hook or "").strip():
                warnings.append(
                    f"Chapter {ch}, scene {s} (terminal): required_end_hook "
                    "is empty — final scene must specify unresolved pressure"
                )

    return warnings
