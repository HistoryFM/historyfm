"""Sovereign Ink — main entry point."""

import sys
from pathlib import Path

# Ensure the project root's .env is loaded before anything else
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from sovereign_ink.cli.commands import cli


def main():
    """Entry point for the sovereign-ink CLI."""
    cli()


if __name__ == "__main__":
    main()
