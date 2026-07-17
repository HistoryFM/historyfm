"""Regression tests for AGENT-BACKEND-J.

Anthropic reports server overload as a dedicated HTTP 529, but when it happens
*mid-stream* it arrives as an SSE ``error`` event on an otherwise-200 response.
The SDK then raises a generic ``APIStatusError`` with ``status_code == 200`` and
a body of ``{"type": "error", "error": {"type": "overloaded_error", ...}}``.

Before the fix, the circuit breaker only counted ``status_code >= 500``, so a
sustained mid-stream overload never engaged it, and every transient retry was
sent to Sentry as a captured exception (noise). These tests lock in the fixed
behaviour: overloaded errors trip the breaker, and the exception is captured
once at exhaustion rather than once per retry.
"""

from __future__ import annotations

import httpx
import pytest

from sovereign_ink.llm.client import LLMClient
from sovereign_ink.utils.config import GenerationConfig

import anthropic


def _overloaded_error(status_code: int = 200) -> anthropic.APIStatusError:
    """Build an APIStatusError shaped like a mid-stream Anthropic overload."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")
    response = httpx.Response(status_code, request=request)
    body = {
        "type": "error",
        "error": {"details": None, "type": "overloaded_error", "message": "Overloaded"},
    }
    return anthropic.APIStatusError("Overloaded", response=response, body=body)


def test_is_overloaded_detects_mid_stream_200_body():
    """A 200-status APIStatusError carrying overloaded_error is an overload."""
    assert LLMClient._is_overloaded(_overloaded_error(status_code=200)) is True


def test_is_overloaded_detects_529():
    assert LLMClient._is_overloaded(_overloaded_error(status_code=529)) is True


def test_is_overloaded_ignores_unrelated_status_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/messages")
    response = httpx.Response(200, request=request)
    exc = anthropic.APIStatusError(
        "Bad gateway body",
        response=response,
        body={"type": "error", "error": {"type": "api_error", "message": "nope"}},
    )
    assert LLMClient._is_overloaded(exc) is False


def _make_client(monkeypatch) -> LLMClient:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    config = GenerationConfig(max_retries=3, retry_base_delay=0.0)
    return LLMClient(config)


def test_mid_stream_overload_trips_circuit_breaker(monkeypatch):
    """A mid-stream overload on every attempt must increment the breaker counter
    and be captured exactly once (at exhaustion), not once per retry."""
    client = _make_client(monkeypatch)

    # Never actually sleep during backoff / cooldown.
    monkeypatch.setattr("sovereign_ink.llm.client.time.sleep", lambda *_a, **_k: None)

    captures: list[BaseException] = []
    monkeypatch.setattr(
        "sovereign_ink.llm.client.sentry_sdk.capture_exception",
        lambda exc, *a, **k: captures.append(exc),
    )
    monkeypatch.setattr(
        "sovereign_ink.llm.client.sentry_sdk.metrics.count",
        lambda *a, **k: None,
    )

    def _raise_overloaded(*_args, **_kwargs):
        raise _overloaded_error(status_code=200)

    # `messages.stream(...)` is called before the `with`, so raising there is
    # caught by the retry loop exactly like the real mid-stream failure.
    monkeypatch.setattr(client._client.messages, "stream", _raise_overloaded)

    with pytest.raises(RuntimeError, match="streaming call failed"):
        client.generate_streaming(system_prompt="sys", user_prompt="hi")

    # Breaker counted every overloaded attempt (was 0 before the fix).
    assert client._consecutive_500s == client.config.max_retries
    # Captured once, at exhaustion — not once per transient retry.
    assert len(captures) == 1
