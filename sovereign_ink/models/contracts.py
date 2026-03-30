"""Contract compliance models for chapter acceptance."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationEvidence(BaseModel):
    """Evidence span supporting a semantic validation decision."""

    quote: str = Field(default="", description="Quoted prose span.")
    start_char: int = Field(default=-1, description="Start char offset in chapter.")
    end_char: int = Field(default=-1, description="End char offset in chapter.")
    reason: str = Field(default="", description="Why this span satisfies/fails requirement.")
    validator: str = Field(default="", description="Validator name.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class RequirementResult(BaseModel):
    """Per requirement pass/fail with supporting evidence."""

    requirement: str
    passed: bool
    reason: str = ""
    evidence: list[ValidationEvidence] = Field(default_factory=list)


class SceneContractResult(BaseModel):
    """Compliance outcome for one scene contract."""

    scene_number: int
    passed: bool
    retries: int = 0
    failures: list[str] = Field(default_factory=list)
    requirements: list[RequirementResult] = Field(default_factory=list)


class DeterministicValidationResult(BaseModel):
    """Deterministic validator aggregate result."""

    passed: bool
    structural_passed: bool
    scene_contracts_passed: bool
    chapter_contracts_passed: bool
    failures: list[str] = Field(default_factory=list)
    scene_results: list[SceneContractResult] = Field(default_factory=list)
    chapter_requirements: list[RequirementResult] = Field(default_factory=list)


class SemanticValidationResult(BaseModel):
    """Semantic validator result with mandatory evidence spans."""

    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requirement_results: list[RequirementResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    raw_validator: str = "semantic_validator"


class AdversarialValidationResult(BaseModel):
    """Adversarial verifier result used for disagreement resolution."""

    triggered: bool = False
    passed: bool = True
    reason: str = ""
    requirement_results: list[RequirementResult] = Field(default_factory=list)


class ComplianceReport(BaseModel):
    """Machine-readable chapter compliance artifact."""

    chapter_number: int
    status: str = "failed"
    acceptance_passed: bool = False
    bypass_flags_used: list[str] = Field(default_factory=list)
    deterministic: DeterministicValidationResult
    semantic: SemanticValidationResult
    adversarial: AdversarialValidationResult = Field(
        default_factory=AdversarialValidationResult
    )
    retries: dict[str, int] = Field(default_factory=dict)
    model_routing: dict[str, str] = Field(default_factory=dict)


class SemanticValidatorResponse(BaseModel):
    """Structured response schema for semantic contract validator."""

    passed: bool
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    requirement_results: list[RequirementResult] = Field(default_factory=list)


class AdversarialValidatorResponse(BaseModel):
    """Structured response schema for adversarial verifier."""

    passed: bool
    reason: str = ""
    requirement_results: list[RequirementResult] = Field(default_factory=list)

