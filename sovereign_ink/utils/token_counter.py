"""Token counting and cost estimation utilities.

Uses tiktoken's ``cl100k_base`` encoding as a close approximation for Claude
token counts.
"""

from __future__ import annotations

import logging

import tiktoken

from sovereign_ink.utils.config import GenerationConfig

logger = logging.getLogger(__name__)

# Lazily initialised module-level encoder
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Return a cached ``cl100k_base`` encoder instance."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Return the approximate token count for *text*.

    Parameters
    ----------
    text:
        Arbitrary string to tokenise.

    Returns
    -------
    int
        Number of tokens.
    """
    if not text:
        return 0
    return len(_get_encoder().encode(text))


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    config: GenerationConfig,
) -> float:
    """Estimate USD cost for a single API call.

    Parameters
    ----------
    input_tokens:
        Tokens sent to the model.
    output_tokens:
        Tokens received from the model.
    model:
        Model identifier (must appear in the config cost tables).
    config:
        Active generation configuration.

    Returns
    -------
    float
        Estimated cost in USD.
    """
    input_rate = config.cost_per_1k_input_tokens.get(model, 0.0)
    output_rate = config.cost_per_1k_output_tokens.get(model, 0.0)

    if input_rate == 0.0 and output_rate == 0.0:
        logger.warning(
            "No cost data for model '%s' — cost estimate will be $0.00", model
        )

    cost = (input_tokens / 1000.0) * input_rate + (output_tokens / 1000.0) * output_rate
    return round(cost, 6)


def calculate_token_budget(
    model: str,
    system_prompt_tokens: int,
    world_context_tokens: int,
    continuity_tokens: int,
    chapter_plan_tokens: int,
    prior_summaries_tokens: int,
    config: GenerationConfig | None = None,
) -> int:
    """Calculate remaining tokens available for generation.

    Subtracts all fixed-context token costs from the model's maximum context
    window to determine how many tokens can be used for the actual generated
    output.

    Parameters
    ----------
    model:
        Model identifier (currently unused for per-model limits but kept for
        forward-compatibility).
    system_prompt_tokens:
        Tokens consumed by the system prompt.
    world_context_tokens:
        Tokens for the world-building / lore context.
    continuity_tokens:
        Tokens for the continuity / prior-chapter context.
    chapter_plan_tokens:
        Tokens for the chapter outline / beat sheet.
    prior_summaries_tokens:
        Tokens for summaries of earlier chapters.
    config:
        Optional config; defaults to a fresh :class:`GenerationConfig`.

    Returns
    -------
    int
        Remaining tokens available for generation (clamped to ≥ 0).
    """
    if config is None:
        config = GenerationConfig()

    used = (
        system_prompt_tokens
        + world_context_tokens
        + continuity_tokens
        + chapter_plan_tokens
        + prior_summaries_tokens
    )
    remaining = config.max_context_tokens - used
    budget = max(0, min(remaining, config.max_tokens_per_call))

    logger.debug(
        "Token budget: %d used of %d context → %d available (capped at %d)",
        used,
        config.max_context_tokens,
        remaining,
        budget,
    )
    return budget
