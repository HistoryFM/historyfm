"""Configuration loader for Sovereign Ink.

Reads settings from environment variables (via .env) and an optional
``generation_config.yaml`` file in the project root.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class GenerationConfig(BaseModel):
    """All tuneable parameters for novel generation."""

    model_config = {"protected_namespaces": ()}

    # --- Model assignments per task type ----------------------------------
    model_world_building: str = "claude-sonnet-4-6"
    model_structural_planning: str = "claude-sonnet-4-6"
    model_prose_generation: str = "claude-sonnet-4-6"
    model_revision_structural: str = "claude-sonnet-4-6"
    model_revision_structural_opus: str = "claude-opus-4-6"
    model_revision_creative: str = "claude-sonnet-4-6"
    model_revision_polish: str = "claude-sonnet-4-6"
    model_utility: str = "claude-haiku-4-5-20251001"

    # --- Generation parameters --------------------------------------------
    temperature_world_building: float = 0.7
    temperature_prose: float = 0.85
    temperature_revision: float = 0.6
    max_tokens_per_call: int = 8192
    max_retries: int = 3
    retry_base_delay: float = 2.0

    # --- Chapter targets --------------------------------------------------
    target_words_per_chapter: int = 3000
    min_words_per_chapter: int = 2000
    max_words_per_chapter: int = 4500

    # --- Revision ---------------------------------------------------------
    num_revision_passes: int = 3
    revision_window_size: int = 3  # chapters per window
    enable_selective_opus_structural_revision: bool = False
    immediate_jeopardy_opus_threshold_per_10k_words: float = 2.5

    # --- Chapter limits ----------------------------------------------------
    max_chapters: int | None = None  # generate only first N chapters (None = all)

    # --- Quality checkpoint -----------------------------------------------
    enable_quality_checkpoint: bool = True
    checkpoint_after_chapters: list[int] = Field(default_factory=lambda: [2])

    # --- Quality gates (pre-save acceptance) --------------------------------
    enable_quality_gates: bool = True
    gate_strict_structure_validation: bool = True
    gate_max_chapter_retries: int = 2
    gate_max_ending_retries: int = 2
    gate_max_jeopardy_deficit_scenes: int = 1
    gate_max_exposition_drag_runs: int = 1
    # Craft gates (Sonnet-only — never trigger Opus)
    gate_rhythm_cv_threshold: float = 0.45
    gate_short_sentence_ratio_threshold: float = 0.10
    gate_max_psychologizing_per_1k_words: float = 5.0
    # Opus escalation tier — only gates in this list may trigger Opus
    opus_eligible_gates: list[str] = Field(
        default_factory=lambda: ["offstage_opposition", "immediate_jeopardy"]
    )

    # --- Contract-first enforcement ----------------------------------------
    contract_enforcement_mode: str = "strict"  # safe | strict
    contract_fail_closed: bool = True
    max_contract_retries: int = 2
    stage4_max_total_repair_attempts: int = 12
    stage4_scene_count_tolerance: int = 0
    # Chapter-level convergence protections for `sovereign-ink next`.
    next_max_convergence_attempts: int = 12
    next_max_identical_failure_streak: int = 3
    semantic_validator_enabled: bool = True
    semantic_validator_model: str = "claude-sonnet-4-6"
    semantic_confidence_threshold: float = 0.70
    adversarial_verifier_enabled: bool = True
    adversarial_verifier_model: str = "claude-sonnet-4-6"
    adversarial_trigger: str = "both"  # disagreement | low_confidence | both

    # --- Voice pass regression control ------------------------------------
    # When > 0, retry the voice pass from its input if it introduces regressions,
    # with the regression report injected as a mandatory-fix directive.
    voice_pass_max_regression_retry: int = 1

    # When True, the voice pass uses a two-phase diagnose/patch approach:
    # a diagnosis call identifies weak paragraphs, then each paragraph is
    # rewritten individually.  This drastically limits regression surface area
    # compared to a full-chapter rewrite.  Off by default for canary testing.
    enable_targeted_voice_revision: bool = False
    # Structural/polish retries when critical metrics regress.
    pass_regression_max_retry: int = 1
    pass_regression_delta_threshold: int = 0
    pass_regression_critical_metrics: list[str] = Field(
        default_factory=lambda: [
            "repetition_patterns",
            "sensory_deficit_scenes",
            "immediate_jeopardy_deficit_scenes",
        ]
    )

    # --- Smart repetition pass (Stage 5 post-polish targeted loop) --------
    enable_smart_repetition_pass: bool = False
    smart_repetition_max_paragraphs: int = 6
    smart_repetition_max_critic_findings: int = 10
    smart_repetition_retry_limit: int = 2
    smart_repetition_judge_min_confidence: float = 0.75
    smart_repetition_require_effective_reduction: bool = True
    smart_repetition_tiebreak_mode: str = "conservative_keep_original"
    smart_repetition_anchor_window_paragraphs: int = 1
    smart_repetition_model_critic: str = "claude-sonnet-4-6"
    smart_repetition_model_editor: str = "claude-sonnet-4-6"
    smart_repetition_model_judge: str = "claude-sonnet-4-6"

    # --- Pressure contracts (Stage 3 scene-level enforcement) ---------------
    enable_pressure_contracts: bool = True
    strict_pressure_contract_validation: bool = False
    gate_max_scene_retries: int = 2
    gate_opus_scene_escalation: bool = True
    generate_scene_by_scene_default: bool = True

    # --- Phase 5: Literary quality elevation features (all off by default) ---

    # Improvement 1: Voice differentiation per POV
    # When enabled, narrative_register is injected in chapter prompts and
    # checked via run_scene_contract_checks() during Stage 4 scene validation.
    enable_narrative_register: bool = False

    # Improvement 2: Physical interruption contracts
    # When enabled, physical_interruption field is enforced in scene contract
    # checks and rationalization is detected via detect_symbolic_rationalization().
    enable_physical_interruption_contracts: bool = False

    # Improvement 3: Petty moment contracts
    # When enabled, petty_moment field is enforced via run_chapter_contract_checks()
    # and rationalization is detected via detect_pettiness_rationalization().
    enable_petty_moment_contracts: bool = False

    # Improvement 4: Scene ending variation gate
    # Cross-chapter gate that compares consecutive chapter endings for tonal
    # similarity and rejects the "dark room / sealed letter" default shape.
    enable_ending_variation_gate: bool = False
    gate_max_consecutive_similar_endings: int = 2
    gate_ending_similarity_threshold: float = 0.50

    # --- Phase 9: Chapter completion gate ------------------------------------
    # Deterministic gate that detects truncated/incomplete chapter endings.
    # Off by default for backward compatibility.
    enable_chapter_completion_gate: bool = False
    gate_max_completion_retries: int = 2

    # --- Phase 9: Exposition drag in critical retry -------------------------
    # When True, exposition_drag_runs regressions trigger a pass-level retry
    # alongside the other critical metrics in _critical_regressions().
    critical_retry_include_exposition_drag: bool = False

    # --- Phase 9: Long-chapter dedup-first surgery --------------------------
    # When True, long chapters (> dedup_first_soft_cap_words) run a targeted
    # dedup pass before the final polish pass to fix repetition hot spots.
    enable_long_chapter_dedup_first: bool = False
    dedup_first_soft_cap_words: int = 5000

    # --- Phase 8: Length guardrails ----------------------------------------
    # Guardrails are off by default for backward compatibility.
    enable_length_guardrails: bool = False
    # Stage 4 post-generation soft/hard caps as multipliers of max_words_per_chapter.
    length_soft_cap_ratio: float = 1.10
    length_hard_cap_ratio: float = 1.25
    # Stage 5 post-revision soft/hard caps as multipliers of max_words_per_chapter.
    revision_soft_cap_ratio: float = 1.15
    revision_hard_cap_ratio: float = 1.30
    length_guard_max_retries: int = 2

    # --- Context management -----------------------------------------------
    max_context_tokens: int = 180_000
    summary_target_words: int = 250

    # --- Cost tracking (USD per 1 000 tokens) -----------------------------
    cost_per_1k_input_tokens: dict[str, float] = Field(
        default_factory=lambda: {
            "claude-sonnet-4-6": 0.003,
            "claude-sonnet-4-20250514": 0.003,
            "claude-opus-4-6": 0.015,
            "claude-haiku-4-5-20251001": 0.001,
        }
    )
    cost_per_1k_output_tokens: dict[str, float] = Field(
        default_factory=lambda: {
            "claude-sonnet-4-6": 0.015,
            "claude-sonnet-4-20250514": 0.015,
            "claude-opus-4-6": 0.075,
            "claude-haiku-4-5-20251001": 0.005,
        }
    )


def load_config(project_dir: Path) -> GenerationConfig:
    """Load configuration from an optional YAML file in *project_dir*.

    If ``generation_config.yaml`` exists, its keys are merged into the
    defaults defined by :class:`GenerationConfig`.  Environment variables
    (from ``.env``) are loaded first so the API key is available.

    Parameters
    ----------
    project_dir:
        Root directory of the Sovereign Ink project.

    Returns
    -------
    GenerationConfig
        Fully resolved configuration.
    """
    # Ensure .env is loaded (idempotent)
    env_path = project_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.debug("Loaded .env from %s", env_path)

    config_path = project_dir / "generation_config.yaml"
    overrides: dict[str, Any] = {}

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if isinstance(raw, dict):
            overrides = raw
            logger.info("Loaded generation config overrides from %s", config_path)
        else:
            logger.warning(
                "generation_config.yaml exists but does not contain a mapping — "
                "using defaults"
            )
    else:
        logger.info(
            "No generation_config.yaml found at %s — using defaults", config_path
        )

    config = GenerationConfig(**overrides)
    logger.debug("Resolved GenerationConfig: %s", config.model_dump_json(indent=2))
    return config


def get_api_key() -> str:
    """Return the Anthropic API key from the environment.

    Raises
    ------
    ValueError
        If ``ANTHROPIC_API_KEY`` is not set.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to your .env file or export it as an environment variable."
        )
    return key
