"""Sovereign Ink data models — re-exports for convenient access.

Usage:
    from sovereign_ink.models import NovelSpec, WorldState, PipelineState
"""

from sovereign_ink.models.continuity import (
    CharacterKnowledge,
    ContinuityLedger,
    OpenThread,
    PoliticalCapital,
    RelationshipState,
    SubplotThread,
    TimelineEntry,
)
from sovereign_ink.models.contracts import (
    AdversarialValidationResult,
    AdversarialValidatorResponse,
    ComplianceReport,
    DeterministicValidationResult,
    RequirementResult,
    SceneContractResult,
    SemanticValidationResult,
    SemanticValidatorResponse,
    ValidationEvidence,
)
from sovereign_ink.models.novel_spec import NovelSpec
from sovereign_ink.models.pipeline import (
    ChapterState,
    ChapterStateStatus,
    ChapterDraft,
    ContextSummary,
    PipelineState,
    RevisionResult,
    StageProgress,
    StageStatus,
)
from sovereign_ink.models.structure import (
    Act,
    ActStructure,
    ChapterOutline,
    DialogueDynamics,
    NovelStructure,
    Scene,
    SceneBreakdown,
    VALID_ENDING_MODES,
    VALID_GATE_PROFILES,
    VALID_REGISTERS,
    validate_pressure_architecture,
)
from sovereign_ink.models.world_state import (
    CharacterProfile,
    EraToneGuide,
    HistoricalContext,
    HistoricalEvent,
    Institution,
    MajorPlayer,
    Relationship,
    TitleTenure,
    WorldState,
)

__all__ = [
    # novel_spec
    "NovelSpec",
    # world_state
    "HistoricalContext",
    "HistoricalEvent",
    "MajorPlayer",
    "TitleTenure",
    "Relationship",
    "CharacterProfile",
    "Institution",
    "EraToneGuide",
    "WorldState",
    # structure
    "Act",
    "ActStructure",
    "ChapterOutline",
    "DialogueDynamics",
    "Scene",
    "SceneBreakdown",
    "NovelStructure",
    "VALID_ENDING_MODES",
    "VALID_GATE_PROFILES",
    "VALID_REGISTERS",
    "validate_pressure_architecture",
    "ValidationEvidence",
    "RequirementResult",
    "SceneContractResult",
    "DeterministicValidationResult",
    "SemanticValidationResult",
    "AdversarialValidationResult",
    "ComplianceReport",
    "SemanticValidatorResponse",
    "AdversarialValidatorResponse",
    # continuity
    "TimelineEntry",
    "CharacterKnowledge",
    "PoliticalCapital",
    "RelationshipState",
    "OpenThread",
    "SubplotThread",
    "ContinuityLedger",
    # pipeline
    "StageStatus",
    "StageProgress",
    "PipelineState",
    "ChapterStateStatus",
    "ChapterState",
    "ChapterDraft",
    "RevisionResult",
    "ContextSummary",
]
