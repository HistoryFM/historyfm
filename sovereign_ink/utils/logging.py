"""Structured logging setup for Sovereign Ink.

Configures both console output (via Rich) and JSON-lines file logging.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any


class _JSONLinesFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Carry over extra structured fields attached by callers
        for key in ("model", "input_tokens", "output_tokens", "latency_ms",
                     "cost", "stage", "chapter", "retry_attempt"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        return json.dumps(log_entry, default=str)


def setup_logging(log_dir: Path, verbose: bool = False) -> None:
    """Configure the root logger with Rich console and JSONL file handlers.

    Parameters
    ----------
    log_dir:
        Directory where ``sovereign_ink.jsonl`` will be written.
    verbose:
        If *True*, set the root level to DEBUG (includes full LLM
        prompts/responses).  Otherwise default to INFO.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Avoid adding duplicate handlers on repeated calls
    if root_logger.handlers:
        return

    # --- Console handler (Rich) -------------------------------------------
    try:
        from rich.logging import RichHandler

        console_handler = RichHandler(
            level=logging.DEBUG if verbose else logging.INFO,
            rich_tracebacks=True,
            show_path=False,
            markup=True,
        )
    except ImportError:  # pragma: no cover – fallback if rich unavailable
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    root_logger.addHandler(console_handler)

    # --- File handler (JSON-lines) ----------------------------------------
    log_file = log_dir / "sovereign_ink.jsonl"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_JSONLinesFormatter())
    root_logger.addHandler(file_handler)

    logging.getLogger("sovereign_ink").info(
        "Logging initialised — file: %s | verbose: %s", log_file, verbose
    )
