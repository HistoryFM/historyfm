#!/usr/bin/env python3
"""Daily novel generation script.

Generates up to N chapters (default 2) across active novels from the backlog.
Prioritizes finishing in-progress novels before starting new ones.

Usage:
    python scripts/daily_generate.py
    python scripts/daily_generate.py --dry-run
    python scripts/daily_generate.py --chapters 1
    python scripts/daily_generate.py --deploy
    python scripts/daily_generate.py --force
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env so ANTHROPIC_API_KEY is available to subprocesses.
# override=True because the env may have an empty ANTHROPIC_API_KEY already set.
load_dotenv(REPO_ROOT / ".env", override=True)

import sentry_sdk

if not sentry_sdk.is_initialized():
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

BACKLOG_DIR = REPO_ROOT / "backlog"
LOG_DIR = REPO_ROOT / "logs"
LOCK_FILE = LOG_DIR / "daily_generate.lock"
DEFAULT_CHAPTERS_PER_RUN = 2
CHAPTER_TIMEOUT_SECONDS = 3600  # 1 hour per chapter

logger = logging.getLogger("daily_generate")


# ---------------------------------------------------------------------------
# Backlog helpers
# ---------------------------------------------------------------------------

def load_all_backlog() -> list[dict]:
    """Load all backlog YAML files, sorted: in_progress first, then backlog."""
    entries = []
    for path in sorted(BACKLOG_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        data["_path"] = path
        entries.append(data)

    # Sort: in_progress first, then backlog, then complete
    priority = {"in_progress": 0, "backlog": 1, "complete": 2}
    entries.sort(key=lambda e: priority.get(e.get("status", "complete"), 9))
    return entries


def get_completed_chapters(project_dir: Path) -> int:
    """Count accepted (v3_polish) chapters in a project."""
    polish_dir = project_dir / "drafts" / "v3_polish"
    if not polish_dir.exists():
        return 0
    return len(list(polish_dir.glob("chapter_*.md")))


def is_novel_complete(entry: dict) -> bool:
    """Check if a novel has all chapters generated."""
    if entry.get("status") == "complete":
        return True
    project_dir_name = entry.get("project_dir")
    if not project_dir_name:
        return False
    project_dir = REPO_ROOT / project_dir_name
    completed = get_completed_chapters(project_dir)
    return completed >= entry.get("max_chapters", 999)


def mark_complete(entry: dict) -> None:
    """Update a backlog entry status to complete."""
    backlog_path = entry["_path"]
    data = yaml.safe_load(backlog_path.read_text())
    data["status"] = "complete"
    backlog_path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    )
    logger.info("Marked novel '%s' as complete.", entry["title"])


# ---------------------------------------------------------------------------
# Work selection
# ---------------------------------------------------------------------------

def select_work(backlog: list[dict], num_slots: int, *, force: bool = False) -> list[dict]:
    """Select novels to generate chapters for.

    Returns a list of backlog entries (may contain duplicates if one novel gets
    multiple slots). Length <= num_slots.
    """
    work: list[dict] = []

    # Phase 1: Allocate slots to in_progress novels
    for entry in backlog:
        if len(work) >= num_slots:
            break
        if entry.get("status") == "in_progress":
            pass
        elif entry.get("status") == "complete" and force:
            pass
        else:
            continue
        if not force and is_novel_complete(entry):
            continue

        project_dir_name = entry.get("project_dir")
        if not project_dir_name:
            continue
        project_dir = REPO_ROOT / project_dir_name
        completed = get_completed_chapters(project_dir)
        remaining = entry["max_chapters"] - completed

        if force and remaining <= 0:
            # Force mode: give 1 slot even though max_chapters is reached
            slots_for_novel = min(1, num_slots - len(work))
        else:
            # Give this novel as many slots as it needs (up to remaining budget)
            slots_for_novel = min(remaining, num_slots - len(work))
        work.extend([entry] * slots_for_novel)

    # Phase 2: If slots remain, pick the next backlog novel
    if len(work) < num_slots:
        for entry in backlog:
            if entry.get("status") != "backlog":
                continue
            slots_remaining = num_slots - len(work)
            work.extend([entry] * slots_remaining)
            break

    return work[:num_slots]


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def init_novel_from_backlog(entry: dict, *, dry_run: bool = False) -> str:
    """Initialize a novel project from backlog. Returns project dir name."""
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.init_novel import init_novel

    backlog_path = entry["_path"]
    return init_novel(backlog_path, dry_run=dry_run)


def generate_chapter(project_dir: Path, *, dry_run: bool = False) -> bool:
    """Generate one chapter via sovereign-ink next. Returns True on success."""
    if dry_run:
        completed = get_completed_chapters(project_dir)
        logger.info("[DRY RUN] Would generate chapter %d in %s", completed + 1, project_dir.name)
        return True

    logger.info("Generating chapter in %s...", project_dir.name)
    try:
        env = os.environ.copy()
        traceparent = sentry_sdk.get_traceparent()
        baggage = sentry_sdk.get_baggage()
        if traceparent:
            env["SENTRY_TRACE"] = traceparent
        if baggage:
            env["SENTRY_BAGGAGE"] = baggage

        result = subprocess.run(
            [sys.executable, "-m", "sovereign_ink", "next", "-p", str(project_dir)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=CHAPTER_TIMEOUT_SECONDS,
            env=env,
        )
        # Log stdout/stderr
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                logger.info("[sovereign-ink] %s", line)
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                logger.warning("[sovereign-ink stderr] %s", line)

        if result.returncode != 0:
            logger.error(
                "sovereign-ink next failed (exit %d) for %s",
                result.returncode, project_dir.name,
            )
            return False

        logger.info("Chapter generation succeeded for %s", project_dir.name)
        return True

    except subprocess.TimeoutExpired as exc:
        sentry_sdk.set_context("subprocess_timeout", {
            "project_dir": project_dir.name,
            "timeout_seconds": CHAPTER_TIMEOUT_SECONDS,
        })
        sentry_sdk.capture_exception(exc)
        logger.error("Chapter generation timed out after %ds for %s", CHAPTER_TIMEOUT_SECONDS, project_dir.name)
        return False
    except Exception:
        logger.exception("Unexpected error generating chapter for %s", project_dir.name)
        return False


def run_deploy(*, dry_run: bool = False) -> None:
    """Run the deploy pipeline (publish + sync + git push)."""
    if dry_run:
        logger.info("[DRY RUN] Would run scripts/deploy.sh")
        return

    logger.info("Running deploy pipeline...")
    deploy_script = REPO_ROOT / "scripts" / "deploy.sh"
    result = subprocess.run(
        ["bash", str(deploy_script)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error("Deploy failed: %s", result.stderr)
    else:
        logger.info("Deploy succeeded.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(*, chapters: int = DEFAULT_CHAPTERS_PER_RUN, deploy: bool = False, dry_run: bool = False, force: bool = False) -> dict:
    """Execute daily generation. Returns a summary dict."""
    # Use start_span if there's already an active transaction (e.g. daemon calling us),
    # otherwise create a root transaction for standalone runs.
    active_span = sentry_sdk.get_current_span()
    if active_span is not None:
        _txn = sentry_sdk.start_span(op="pipeline", name="daily-generate.run")
    else:
        _txn = sentry_sdk.start_transaction(op="pipeline", name="daily-generate.run")
    _txn.set_tag("chapters_requested", str(chapters))
    _txn.set_tag("force", str(force))
    _txn.set_tag("deploy", str(deploy))
    _txn.set_tag("dry_run", str(dry_run))
    _txn.__enter__()

    try:
        summary = {
            "date": datetime.now().isoformat(),
            "chapters_requested": chapters,
            "chapters_generated": 0,
            "chapters_failed": 0,
            "novels_initialized": 0,
            "novels_completed": 0,
            "details": [],
        }

        backlog = load_all_backlog()
        logger.info("Loaded %d backlog entries.", len(backlog))

        in_progress_count = sum(1 for e in backlog if e.get("status") == "in_progress")
        pending_count = sum(1 for e in backlog if e.get("status") == "backlog")
        sentry_sdk.metrics.gauge("backlog.pending_novels", pending_count, attributes={"status": "backlog"})
        sentry_sdk.metrics.gauge("backlog.in_progress_novels", in_progress_count, attributes={"status": "in_progress"})

        work = select_work(backlog, chapters, force=force)
        if not work:
            logger.info("No work to do — all novels complete or backlog empty.")
            _txn.set_tag("chapters_generated", "0")
            _txn.set_tag("chapters_failed", "0")
            _txn.__exit__(None, None, None)
            return summary

        logger.info(
            "Selected %d chapter slot(s): %s",
            len(work),
            ", ".join(e["title"] for e in work),
        )

        for i, entry in enumerate(work):
            with sentry_sdk.start_span(op="chapter.generate", name=f"generate.{entry['title']}.slot_{i+1}") as slot_span:
                slot_span.set_tag("novel", entry["title"])
                slot_span.set_tag("slot", str(i + 1))
                logger.info("--- Slot %d/%d: %s ---", i + 1, len(work), entry["title"])

                # Initialize if needed
                if entry.get("status") == "backlog":
                    logger.info("Novel '%s' needs initialization.", entry["title"])
                    try:
                        dir_name = init_novel_from_backlog(entry, dry_run=dry_run)
                        entry["project_dir"] = dir_name
                        entry["status"] = "in_progress"
                        summary["novels_initialized"] += 1
                    except Exception:
                        logger.exception("Failed to initialize novel '%s', skipping.", entry["title"])
                        summary["chapters_failed"] += 1
                        summary["details"].append({
                            "novel": entry["title"], "action": "init_failed",
                        })
                        continue

                project_dir = REPO_ROOT / entry["project_dir"]
                completed_before = get_completed_chapters(project_dir)

                success = generate_chapter(project_dir, dry_run=dry_run)

                if success:
                    summary["chapters_generated"] += 1
                    completed_after = completed_before + 1 if not dry_run else completed_before
                    summary["details"].append({
                        "novel": entry["title"],
                        "project_dir": entry["project_dir"],
                        "chapter": completed_after,
                        "max_chapters": entry["max_chapters"],
                        "action": "generated",
                    })

                    # Check if novel is now complete
                    if not dry_run and not force and completed_after >= entry["max_chapters"]:
                        mark_complete(entry)
                        summary["novels_completed"] += 1
                else:
                    summary["chapters_failed"] += 1
                    summary["details"].append({
                        "novel": entry["title"],
                        "project_dir": entry.get("project_dir"),
                        "action": "failed",
                    })

        # Deploy if requested
        if deploy:
            run_deploy(dry_run=dry_run)

        _txn.set_tag("chapters_generated", str(summary["chapters_generated"]))
        _txn.set_tag("chapters_failed", str(summary["chapters_failed"]))
        _txn.__exit__(None, None, None)
        return summary

    except Exception as exc:
        _txn.__exit__(type(exc), exc, exc.__traceback__)
        raise


def main():
    parser = argparse.ArgumentParser(description="Daily novel generation script.")
    parser.add_argument("--chapters", type=int, default=DEFAULT_CHAPTERS_PER_RUN,
                        help=f"Number of chapters to generate (default: {DEFAULT_CHAPTERS_PER_RUN})")
    parser.add_argument("--deploy", action="store_true",
                        help="Run deploy pipeline after generation")
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would be done without making changes")
    parser.add_argument("--force", action="store_true",
                        help="Force generation even for novels marked complete or past max_chapters")
    args = parser.parse_args()

    # Setup logging
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"daily_{date_str}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    logger.info("=== Daily generation starting (chapters=%d, deploy=%s, dry_run=%s, force=%s) ===",
                args.chapters, args.deploy, args.dry_run, args.force)

    # Acquire file lock (non-blocking)
    lock_fd = None
    if not args.dry_run:
        try:
            lock_fd = open(LOCK_FILE, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd.write(str(os.getpid()))
            lock_fd.flush()
        except BlockingIOError:
            logger.error("Another daily_generate process is already running (lock held). Exiting.")
            sys.exit(1)

    try:
        summary = run(
            chapters=args.chapters,
            deploy=args.deploy,
            dry_run=args.dry_run,
            force=args.force,
        )

        logger.info("=== Daily generation complete ===")
        logger.info(
            "Summary: %d generated, %d failed, %d novels initialized, %d novels completed",
            summary["chapters_generated"],
            summary["chapters_failed"],
            summary["novels_initialized"],
            summary["novels_completed"],
        )
        for detail in summary["details"]:
            logger.info("  %s", detail)

    except Exception:
        logger.exception("Daily generation crashed")
        sys.exit(1)

    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


if __name__ == "__main__":
    main()
