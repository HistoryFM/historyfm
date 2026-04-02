#!/usr/bin/env python3
"""Novel generation daemon — long-running process with scheduled generation.

Generates 1 chapter per run at noon and 8 PM PST, with auto-publish.
On startup, checks if any scheduled runs were missed today and catches up.

Usage:
    # Foreground (for testing):
    python scripts/novel_daemon.py

    # Background:
    nohup .venv/bin/python scripts/novel_daemon.py > logs/daemon_nohup.log 2>&1 &

    # Stop:
    bash scripts/stop_daemon.sh
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, date
from pathlib import Path

import schedule

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs"
PID_FILE = LOG_DIR / "novel_daemon.pid"
STATE_FILE = LOG_DIR / "daemon_state.json"

# Schedule: noon PST and 8 PM PST — 1 chapter each run, 2 per day
SCHEDULED_TIMES = ["12:00", "20:00"]
CHAPTERS_PER_RUN = 1

# Import the daily generation runner
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("novel_daemon")


def _load_state() -> dict:
    """Load daemon state (tracks which runs completed today)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict) -> None:
    """Persist daemon state to disk."""
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _mark_run_completed(run_time: str) -> None:
    """Record that a scheduled run completed for today."""
    state = _load_state()
    today = date.today().isoformat()
    if "completed_runs" not in state:
        state["completed_runs"] = {}
    if today not in state["completed_runs"]:
        state["completed_runs"][today] = []
    if run_time not in state["completed_runs"][today]:
        state["completed_runs"][today].append(run_time)
    state["last_run"] = datetime.now().isoformat()
    # Clean up entries older than 7 days
    cutoff = date.today().isoformat()
    state["completed_runs"] = {
        d: runs for d, runs in state["completed_runs"].items()
        if d >= cutoff or d == today
    }
    _save_state(state)


def _get_missed_runs() -> list[str]:
    """Check which of today's scheduled runs haven't completed yet and are past due."""
    state = _load_state()
    today = date.today().isoformat()
    completed_today = state.get("completed_runs", {}).get(today, [])
    now = datetime.now()
    missed = []
    for t in SCHEDULED_TIMES:
        hour, minute = map(int, t.split(":"))
        scheduled_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now >= scheduled_dt and t not in completed_today:
            missed.append(t)
    return missed


def generation_job(run_time: str = "manual"):
    """Main job — generates chapters and deploys."""
    logger.info("=== Generation job triggered at %s (scheduled for %s) ===",
                datetime.now().isoformat(), run_time)

    try:
        from scripts.daily_generate import run
        summary = run(chapters=CHAPTERS_PER_RUN, deploy=True, dry_run=False)

        logger.info(
            "Job complete: %d generated, %d failed, %d initialized, %d completed",
            summary["chapters_generated"],
            summary["chapters_failed"],
            summary["novels_initialized"],
            summary["novels_completed"],
        )
        _mark_run_completed(run_time)

    except Exception:
        logger.exception("Generation job failed")


def shutdown(signum, _frame):
    """Handle graceful shutdown."""
    logger.info("Received signal %s, shutting down...", signum)
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


def main():
    # Setup logging
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "daemon.log"),
            logging.StreamHandler(),
        ],
    )

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))
    logger.info("Novel daemon started (PID %s)", os.getpid())

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Load .env for ANTHROPIC_API_KEY (sovereign-ink also loads it, but be safe)
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
        logger.info("Loaded .env")
    except ImportError:
        logger.warning("python-dotenv not available, relying on environment variables")

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

    # Catch up on any missed runs from today
    missed = _get_missed_runs()
    if missed:
        logger.info("Missed runs detected for today: %s — catching up", missed)
        for run_time in missed:
            generation_job(run_time=run_time)
    else:
        logger.info("No missed runs to catch up on.")

    # Schedule runs at noon and 8 PM PST
    for t in SCHEDULED_TIMES:
        schedule.every().day.at(t).do(generation_job, run_time=t)
    logger.info(
        "Scheduled generation at %s. Next run: %s",
        ", ".join(SCHEDULED_TIMES),
        schedule.next_run(),
    )

    # Main loop
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)
        logger.info("Daemon stopped.")


if __name__ == "__main__":
    main()
