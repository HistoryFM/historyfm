"""Synchronous LLM client wrapping the Anthropic Messages API.

Provides plain-text generation, structured (JSON→Pydantic) generation,
and streaming generation — all with exponential-backoff retry, cost
tracking, and structured logging.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Type

import anthropic
import httpx
import sentry_sdk
from pydantic import BaseModel

from sovereign_ink.utils.config import GenerationConfig, get_api_key
from sovereign_ink.utils.token_counter import estimate_cost

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Structured result returned by every LLM call."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_estimate: float
    stop_reason: str


@dataclass
class _CumulativeUsage:
    """Internal tracker for cumulative token usage and cost."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    total_calls: int = 0


class LLMClient:
    """Synchronous Anthropic API client with retry logic and cost tracking.

    Parameters
    ----------
    config:
        The :class:`GenerationConfig` controlling models, temperatures, and
        retry behaviour.
    """

    def __init__(self, config: GenerationConfig) -> None:
        self.config = config
        self._client = anthropic.Anthropic(
            api_key=get_api_key(),
            timeout=httpx.Timeout(connect=10.0, read=1800.0, write=600.0, pool=600.0),
        )
        self._usage = _CumulativeUsage()
        logger.info("LLMClient initialised (default max_tokens=%d)", config.max_tokens_per_call)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def cumulative_input_tokens(self) -> int:
        return self._usage.total_input_tokens

    @property
    def cumulative_output_tokens(self) -> int:
        return self._usage.total_output_tokens

    @property
    def cumulative_cost(self) -> float:
        return round(self._usage.total_cost, 6)

    @property
    def cumulative_calls(self) -> int:
        return self._usage.total_calls

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a single messages-API request with automatic retry.

        Parameters
        ----------
        system_prompt:
            System-level instructions.
        user_prompt:
            The user turn content.
        model:
            Override model; defaults to ``config.model_prose_generation``.
        temperature:
            Override temperature; defaults to ``config.temperature_prose``.
        max_tokens:
            Override max tokens; defaults to ``config.max_tokens_per_call``.

        Returns
        -------
        LLMResponse
        """
        model = model or self.config.model_prose_generation
        temperature = temperature if temperature is not None else self.config.temperature_prose
        max_tokens = max_tokens or self.config.max_tokens_per_call

        logger.debug(
            "LLM request — model=%s temp=%.2f max_tokens=%d",
            model,
            temperature,
            max_tokens,
        )

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                start = time.perf_counter()
                response = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                latency_ms = (time.perf_counter() - start) * 1000.0

                content = self._extract_text(response)
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost = estimate_cost(input_tokens, output_tokens, model, self.config)
                stop_reason = response.stop_reason or "unknown"

                self._record_usage(input_tokens, output_tokens, cost)

                logger.info(
                    "LLM response — model=%s in=%d out=%d latency=%.0fms cost=$%.4f stop=%s",
                    model,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cost,
                    stop_reason,
                    extra={
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "latency_ms": round(latency_ms, 1),
                        "cost": cost,
                    },
                )

                return LLMResponse(
                    content=content,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=round(latency_ms, 1),
                    cost_estimate=cost,
                    stop_reason=stop_reason,
                )

            except anthropic.RateLimitError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Rate limited (attempt %d/%d) — retrying in %.1fs",
                    attempt,
                    self.config.max_retries,
                    delay,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "rate_limit"})
                time.sleep(delay)

            except anthropic.APIStatusError as exc:
                last_exc = exc
                # Content-filter / moderation refusals are non-retryable
                if exc.status_code == 400:
                    logger.error("API refusal (400): %s", exc.message)
                    sentry_sdk.capture_exception(exc)
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "API error %d (attempt %d/%d) — retrying in %.1fs: %s",
                    exc.status_code,
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc.message,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": f"api_status_{exc.status_code}"})
                time.sleep(delay)

            except anthropic.APIConnectionError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Connection error (attempt %d/%d) — retrying in %.1fs: %s",
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "connection_error"})
                time.sleep(delay)

            except httpx.TimeoutException as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Timeout (attempt %d/%d) — retrying in %.1fs: %s",
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "timeout"})
                time.sleep(delay)

        sentry_sdk.set_context("llm_retry_exhaustion", {
            "model": model,
            "max_retries": self.config.max_retries,
            "last_error": str(last_exc),
        })
        logger.error("All %d retries exhausted", self.config.max_retries)
        raise RuntimeError(
            f"LLM call failed after {self.config.max_retries} retries"
        ) from last_exc

    # ------------------------------------------------------------------
    # Structured (JSON → Pydantic) generation
    # ------------------------------------------------------------------

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: Type[BaseModel],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> BaseModel:
        """Generate a response and parse it into a Pydantic model.

        The model is instructed to return valid JSON matching the schema of
        *response_model*.  If parsing fails, the call is retried up to 2
        additional times with a clarification prompt.

        Parameters
        ----------
        system_prompt:
            System-level instructions.
        user_prompt:
            The user turn content.
        response_model:
            The Pydantic class to deserialise into.
        model:
            Override model.
        temperature:
            Override temperature.
        max_tokens:
            Override max tokens for structured output (defaults to config value).

        Returns
        -------
        BaseModel
            An instance of *response_model*.
        """
        schema_json = json.dumps(response_model.model_json_schema(), indent=2)
        json_instruction = (
            "\n\nYou MUST respond with ONLY valid JSON (no markdown fences, no "
            "commentary) conforming to this JSON schema:\n"
            f"```\n{schema_json}\n```"
        )

        full_system = system_prompt + json_instruction
        max_parse_attempts = 3
        last_content = ""

        for parse_attempt in range(1, max_parse_attempts + 1):
            if parse_attempt == 1:
                prompt = user_prompt
            else:
                prompt = (
                    f"Your previous response was not valid JSON. "
                    f"Parse error: {parse_error}\n\n"
                    f"Please respond ONLY with valid JSON matching the schema. "
                    f"No extra text, no markdown fences.\n\n"
                    f"CRITICAL: Inside JSON string values, you MUST escape any "
                    f"double quotes with a backslash (e.g., \\\"hello\\\"). "
                    f"Do not use literal newlines inside string values; use "
                    f"\\n instead. Keep string values concise.\n\n"
                    f"Original request:\n{user_prompt}"
                )

            llm_response = self.generate(
                system_prompt=full_system,
                user_prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            last_content = llm_response.content.strip()

            # Strip markdown code fences if the model included them
            if last_content.startswith("```"):
                lines = last_content.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                last_content = "\n".join(lines).strip()

            # Attempt to repair truncated JSON (missing closing brackets)
            last_content = self._repair_json(last_content)

            try:
                parsed = response_model.model_validate_json(last_content)
                logger.debug(
                    "Structured parse succeeded on attempt %d", parse_attempt
                )
                return parsed
            except Exception as exc:
                parse_error = str(exc)
                logger.warning(
                    "JSON parse failed (attempt %d/%d): %s",
                    parse_attempt,
                    max_parse_attempts,
                    parse_error,
                    extra={"retry_attempt": parse_attempt},
                )

        sentry_sdk.set_context("structured_parse_failure", {
            "model": model or self.config.model_prose_generation,
            "response_model": response_model.__name__,
            "response_text_snippet": last_content[:500] if last_content else "",
        })
        raise ValueError(
            f"Failed to parse LLM output into {response_model.__name__} after "
            f"{max_parse_attempts} attempts. Last response:\n{last_content}"
        )

    @staticmethod
    def _repair_json(text: str) -> str:
        """Attempt to repair truncated or slightly malformed JSON.

        Handles:
        - Trailing commas before closing brackets
        - Missing closing brackets/braces at end of truncated output
        - Unclosed strings at end of truncated output
        - Unquoted annotations like "word" as verb -> "word (as verb)"
        - Unescaped double quotes inside JSON string values
        """
        import re

        text = text.strip()
        if not text:
            return text

        # Normalize unicode smart quotes to ASCII equivalents
        text = text.replace('\u201c', '"').replace('\u201d', '"')
        text = text.replace('\u2018', "'").replace('\u2019', "'")

        # Fix common pattern: "value" as annotation, or "value" in context,
        # which is invalid JSON — fold the annotation into the string
        text = re.sub(
            r'"([^"]+)"\s+(as|in|for|meaning|i\.e\.|e\.g\.)\s+([^",\]\}]+)',
            r'"\1 (\2 \3)"',
            text,
        )

        # Try parsing first — if it works, return immediately
        try:
            import json
            json.loads(text)
            return text
        except (json.JSONDecodeError, Exception):
            pass

        # Fix unescaped quotes and control characters inside JSON string values
        # using error-position-guided iterative repair
        text = LLMClient._fix_string_quotes(text)

        # If JSON appears complete, clean up and return
        if (text.startswith("{") and text.endswith("}")) or \
           (text.startswith("[") and text.endswith("]")):
            text = re.sub(r',\s*([\]}])', r'\1', text)
            return text

        # JSON is truncated — attempt repair
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False
        last_clean_pos = 0

        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                open_braces += 1
            elif ch == '}':
                open_braces -= 1
            elif ch == '[':
                open_brackets += 1
            elif ch == ']':
                open_brackets -= 1

            if not in_string:
                last_clean_pos = i

        if in_string:
            text = text[:last_clean_pos + 1]

        text = re.sub(r',\s*$', '', text)

        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')

        text += ']' * max(0, open_brackets)
        text += '}' * max(0, open_braces)

        text = re.sub(r',\s*([\]}])', r'\1', text)

        return text

    @staticmethod
    def _fix_string_quotes(text: str) -> str:
        """Fix unescaped characters inside JSON string values using
        json.JSONDecodeError position as a guide.

        Iteratively attempts to parse the JSON.  On each failure the
        error position tells us exactly where the parser choked.  We
        look at both the error position and the nearest preceding
        unescaped quote to determine which character to fix.

        Common failure pattern: ``"turn": "She said "hello" loudly"``
        The parser consumes ``"She said "`` as a complete string, then
        sees ``hello`` where it expects ``,`` or ``}``.  The fix is to
        escape the quote *before* the error position (the one that
        prematurely closed the string).
        """
        import json

        max_fixes = 50  # safety bound
        for _ in range(max_fixes):
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError as exc:
                pos = exc.pos
                if pos is None or pos >= len(text):
                    break

                ch = text[pos] if pos < len(text) else ''

                # Case 1: Error char is a literal newline/tab inside a string
                if ch == '\n':
                    text = text[:pos] + '\\n' + text[pos + 1:]
                    continue
                if ch == '\r':
                    text = text[:pos] + '\\r' + text[pos + 1:]
                    continue
                if ch == '\t':
                    text = text[:pos] + '\\t' + text[pos + 1:]
                    continue

                # Case 2: The parser expected a delimiter but got a normal
                # character.  This means the *previous* unescaped quote
                # prematurely closed a string.  Find it and escape it.
                #
                # Scan backward from pos to find the last unescaped quote.
                fixed = False
                scan = pos - 1
                while scan >= 0:
                    if text[scan] == '"' and (scan == 0 or text[scan - 1] != '\\'):
                        # Found the problematic quote — escape it
                        text = text[:scan] + '\\"' + text[scan + 1:]
                        fixed = True
                        break
                    scan -= 1

                if not fixed:
                    break  # can't find a quote to fix

        return text

    # ------------------------------------------------------------------
    # Streaming generation
    # ------------------------------------------------------------------

    def generate_streaming(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """Stream a response, invoking *on_chunk* for each text delta.

        Parameters
        ----------
        system_prompt:
            System-level instructions.
        user_prompt:
            The user turn content.
        model:
            Override model.
        temperature:
            Override temperature.
        max_tokens:
            Override max tokens.
        on_chunk:
            Optional callback receiving each streamed text fragment.

        Returns
        -------
        LLMResponse
            The accumulated full response.
        """
        model = model or self.config.model_prose_generation
        temperature = temperature if temperature is not None else self.config.temperature_prose
        max_tokens = max_tokens or self.config.max_tokens_per_call

        logger.debug(
            "LLM streaming request — model=%s temp=%.2f max_tokens=%d",
            model,
            temperature,
            max_tokens,
        )

        last_exc: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                start = time.perf_counter()
                accumulated_text: list[str] = []
                input_tokens = 0
                output_tokens = 0
                stop_reason = "unknown"

                with self._client.messages.stream(
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                ) as stream:
                    for text in stream.text_stream:
                        accumulated_text.append(text)
                        if on_chunk is not None:
                            on_chunk(text)

                    # Retrieve the final message for usage metadata
                    final_message = stream.get_final_message()
                    input_tokens = final_message.usage.input_tokens
                    output_tokens = final_message.usage.output_tokens
                    stop_reason = final_message.stop_reason or "unknown"

                latency_ms = (time.perf_counter() - start) * 1000.0
                content = "".join(accumulated_text)
                cost = estimate_cost(input_tokens, output_tokens, model, self.config)

                self._record_usage(input_tokens, output_tokens, cost)

                logger.info(
                    "LLM stream complete — model=%s in=%d out=%d latency=%.0fms cost=$%.4f",
                    model,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cost,
                    extra={
                        "model": model,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "latency_ms": round(latency_ms, 1),
                        "cost": cost,
                    },
                )

                return LLMResponse(
                    content=content,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=round(latency_ms, 1),
                    cost_estimate=cost,
                    stop_reason=stop_reason,
                )

            except anthropic.RateLimitError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Rate limited during stream (attempt %d/%d) — retrying in %.1fs",
                    attempt,
                    self.config.max_retries,
                    delay,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "rate_limit"})
                time.sleep(delay)

            except anthropic.APIStatusError as exc:
                last_exc = exc
                if exc.status_code == 400:
                    logger.error("API refusal (400) during stream: %s", exc.message)
                    sentry_sdk.capture_exception(exc)
                    raise
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "API error %d during stream (attempt %d/%d) — retrying in %.1fs",
                    exc.status_code,
                    attempt,
                    self.config.max_retries,
                    delay,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": f"api_status_{exc.status_code}"})
                time.sleep(delay)

            except anthropic.APIConnectionError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Connection error during stream (attempt %d/%d) — retrying in %.1fs",
                    attempt,
                    self.config.max_retries,
                    delay,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "connection_error"})
                time.sleep(delay)

            except httpx.TimeoutException as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Timeout during stream (attempt %d/%d) — retrying in %.1fs: %s",
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "timeout"})
                time.sleep(delay)

            except httpx.RemoteProtocolError as exc:
                last_exc = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Remote protocol error during stream (attempt %d/%d) — retrying in %.1fs: %s",
                    attempt,
                    self.config.max_retries,
                    delay,
                    exc,
                    extra={"retry_attempt": attempt},
                )
                sentry_sdk.capture_exception(exc)
                sentry_sdk.metrics.count("llm.retries", 1, attributes={"model": model, "error_type": "remote_protocol_error"})
                time.sleep(delay)

        sentry_sdk.set_context("llm_retry_exhaustion", {
            "model": model,
            "max_retries": self.config.max_retries,
            "last_error": str(last_exc),
        })
        logger.error("All %d retries exhausted for streaming call", self.config.max_retries)
        raise RuntimeError(
            f"LLM streaming call failed after {self.config.max_retries} retries"
        ) from last_exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _backoff_delay(self, attempt: int) -> float:
        """Compute exponential-backoff delay for the given attempt number."""
        return self.config.retry_base_delay * (2 ** (attempt - 1))

    def _record_usage(
        self, input_tokens: int, output_tokens: int, cost: float
    ) -> None:
        """Update cumulative usage counters."""
        self._usage.total_input_tokens += input_tokens
        self._usage.total_output_tokens += output_tokens
        self._usage.total_cost += cost
        self._usage.total_calls += 1

    @staticmethod
    def _extract_text(response: anthropic.types.Message) -> str:
        """Extract concatenated text from an Anthropic Message response."""
        parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "".join(parts)
