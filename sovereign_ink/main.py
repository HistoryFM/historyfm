"""Sovereign Ink — main entry point."""

import sys
from pathlib import Path

# Ensure the project root's .env is loaded before anything else
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import os
import sentry_sdk

sentry_sdk.init(
    dsn=os.environ.get("SENTRY_DSN"),
    environment=os.environ.get("SENTRY_ENVIRONMENT", "development"),
    release=os.environ.get("SENTRY_RELEASE"),
    send_default_pii=True,
    traces_sample_rate=1.0,
    profile_session_sample_rate=1.0,
    profile_lifecycle="trace",
    enable_logs=True,
    shutdown_timeout=5,
)

from sovereign_ink.cli.commands import cli


def main():
    """Entry point for the sovereign-ink CLI."""
    cli()


if __name__ == "__main__":
    main()
