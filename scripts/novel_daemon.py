#!/usr/bin/env python3
"""Novel generation daemon — long-running process with daily scheduling.

Runs daily_generate.py on a schedule. If killed (machine sleep, etc.),
Sentry cron monitoring (to be added later) will detect missed check-ins.

Usage:
    # Foreground (for testing):
    python scripts/novel_daemon.py

    # Background:
    nohup .venv/bin/python scripts/novel_daemon.py > logs/daemon_nohup.log 2>&1 &

    # Stop:
    bash scripts/stop_daemon.sh
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = REPO_ROOT / "logs"
PID_FILE = LOG_DIR / "novel_daemon.pid"

# Import the daily generation runner
sys.path.insert(0, str(REPO_ROOT))

logger = logging.getLogger("novel_daemon")


def daily_generation_job():
    """Main scheduled job — generates 2 chapters across active novels."""
    logger.info("=== Scheduled job triggered at %s ===", datetime.now().isoformat())

    try:
        from scripts.daily_generate import run
        summary = run(chapters=2, deploy=False, dry_run=False)

        logger.info(
            "Job complete: %d generated, %d failed, %d initialized, %d completed",
            summary["chapters_generated"],
            summary["chapters_failed"],
            summary["novels_initialized"],
            summary["novels_completed"],
        )

    except Exception:
        logger.exception("Daily generation job failed")


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

    # Schedule daily at 3:00 AM
    schedule.every().day.at("03:00").do(daily_generation_job)
    logger.info("Scheduled daily generation at 03:00. Next run: %s", schedule.next_run())

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
