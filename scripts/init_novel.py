#!/usr/bin/env python3
"""Initialize a new novel project from a backlog YAML file.

Usage:
    python scripts/init_novel.py backlog/bank-war.yaml
    python scripts/init_novel.py backlog/bank-war.yaml --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Ensure sovereign_ink is importable
sys.path.insert(0, str(REPO_ROOT))


def load_backlog(path: Path) -> dict:
    """Load and validate a backlog YAML file."""
    data = yaml.safe_load(path.read_text())
    required = [
        "title", "slug", "era_start", "era_end", "region", "central_event",
        "tone_intensity", "pov_count", "protagonist_type", "thematic_focus",
        "desired_length", "max_chapters", "synopsis", "description", "status",
    ]
    missing = [k for k in required if k not in data or data[k] is None]
    if missing:
        raise ValueError(f"Backlog file {path} missing required fields: {missing}")
    if data["status"] != "backlog":
        raise ValueError(f"Backlog file {path} has status '{data['status']}', expected 'backlog'")
    return data


def make_project_dir_name(slug: str, max_chapters: int) -> str:
    """Derive project directory name from slug and chapter count."""
    return f"{slug.replace('-', '_')}_{max_chapters}ch"


def build_novel_spec(backlog: dict) -> dict:
    """Build a NovelSpec-compatible dict from backlog data."""
    from sovereign_ink.models import NovelSpec

    spec = NovelSpec(
        title=backlog["title"],
        era_start=backlog["era_start"],
        era_end=backlog["era_end"],
        region=backlog["region"],
        central_event=backlog["central_event"],
        tone_intensity=backlog["tone_intensity"],
        pov_count=backlog["pov_count"],
        protagonist_type=backlog["protagonist_type"],
        thematic_focus=backlog["thematic_focus"],
        desired_length=backlog["desired_length"],
        synopsis=backlog.get("synopsis"),
        additional_notes=backlog.get("additional_notes"),
    )
    return spec.model_dump()


def build_pipeline_state(project_name: str) -> dict:
    """Build initial pipeline state with interactive_setup marked COMPLETED."""
    now = datetime.now().isoformat(sep=" ", timespec="microseconds")
    return {
        "project_name": project_name,
        "created_at": now,
        "last_updated": now,
        "current_stage": "world_building",
        "stages": {
            "interactive_setup": {
                "stage_name": "interactive_setup",
                "status": "completed",
                "started_at": now,
                "completed_at": now,
                "sub_step": None,
                "error_message": None,
            },
            "world_building": {
                "stage_name": "world_building",
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "sub_step": None,
                "error_message": None,
            },
            "structural_planning": {
                "stage_name": "structural_planning",
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "sub_step": None,
                "error_message": None,
            },
            "prose_generation": {
                "stage_name": "prose_generation",
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "sub_step": None,
                "error_message": None,
            },
            "revision_pipeline": {
                "stage_name": "revision_pipeline",
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "sub_step": None,
                "error_message": None,
            },
            "assembly_export": {
                "stage_name": "assembly_export",
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "sub_step": None,
                "error_message": None,
            },
        },
        "total_tokens_used": 0,
        "total_cost_estimate": 0.0,
    }


def build_generation_config(backlog: dict) -> str:
    """Build project-local generation_config.yaml content."""
    lines = [
        f"max_chapters: {backlog['max_chapters']}",
        "",
        "# Quality gates enabled",
        "enable_quality_gates: true",
        "gate_max_chapter_retries: 2",
        "gate_max_ending_retries: 3",
        "gate_max_jeopardy_deficit_scenes: 1",
        "gate_max_exposition_drag_runs: 1",
        "",
        "# Literary quality elevation",
        "enable_narrative_register: true",
        "enable_physical_interruption_contracts: true",
        "enable_petty_moment_contracts: true",
        "enable_ending_variation_gate: true",
        "",
        "# Revision enhancements",
        "enable_targeted_voice_revision: true",
        "enable_length_guardrails: true",
        "enable_chapter_completion_gate: true",
        "enable_smart_repetition_pass: true",
        "semantic_validator_enabled: true",
        "",
        "# Convergence",
        "enable_pressure_contracts: false",
        "stage4_scene_count_tolerance: 1",
        "stage4_max_total_repair_attempts: 8",
        "next_max_convergence_attempts: 8",
        "next_max_identical_failure_streak: 3",
    ]
    return "\n".join(lines) + "\n"


def append_to_root_novels_list(
    project_dir_name: str, slug: str, title: str, description: str, *, dry_run: bool = False,
) -> None:
    """Append a novel entry to the root generation_config.yaml novels list."""
    root_config = REPO_ROOT / "generation_config.yaml"
    # Check if already present
    content = root_config.read_text()
    if f"project_dir: {project_dir_name}" in content:
        logger.info("Novel '%s' already in root config novels list, skipping.", project_dir_name)
        return

    entry = (
        f"  - project_dir: {project_dir_name}\n"
        f"    slug: {slug}\n"
        f'    title: "{title}"\n'
        f'    description: "{description}"\n'
    )

    if dry_run:
        logger.info("[DRY RUN] Would append to root config:\n%s", entry)
        return

    with open(root_config, "a") as f:
        f.write(entry)
    logger.info("Appended novel '%s' to root generation_config.yaml", project_dir_name)


def update_backlog_status(
    backlog_path: Path, status: str, project_dir: str, *, dry_run: bool = False,
) -> None:
    """Update status and project_dir in the backlog YAML file."""
    if dry_run:
        logger.info("[DRY RUN] Would update %s: status=%s, project_dir=%s", backlog_path.name, status, project_dir)
        return

    data = yaml.safe_load(backlog_path.read_text())
    data["status"] = status
    data["project_dir"] = project_dir
    backlog_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True))
    logger.info("Updated %s: status=%s, project_dir=%s", backlog_path.name, status, project_dir)


def init_novel(backlog_path: Path, *, dry_run: bool = False) -> str:
    """Initialize a novel project from a backlog YAML. Returns the project directory name."""
    backlog = load_backlog(backlog_path)
    dir_name = make_project_dir_name(backlog["slug"], backlog["max_chapters"])
    project_dir = REPO_ROOT / dir_name

    logger.info("Initializing novel: %s -> %s", backlog["title"], dir_name)

    if project_dir.exists():
        logger.warning("Project directory %s already exists, checking state...", dir_name)
        spec_path = project_dir / "config" / "novel_spec.json"
        if spec_path.exists():
            logger.info("Novel spec already exists, skipping initialization.")
            update_backlog_status(backlog_path, "in_progress", dir_name, dry_run=dry_run)
            return dir_name

    if dry_run:
        logger.info("[DRY RUN] Would create project directory: %s", project_dir)
        logger.info("[DRY RUN] Would write config/novel_spec.json")
        logger.info("[DRY RUN] Would write state/pipeline_state.json")
        logger.info("[DRY RUN] Would write generation_config.yaml")
        logger.info("[DRY RUN] Would append to root novels list")
        logger.info("[DRY RUN] Would update backlog status to in_progress")
        return dir_name

    # 1. Create project directory structure
    (project_dir / "config").mkdir(parents=True, exist_ok=True)
    (project_dir / "state").mkdir(parents=True, exist_ok=True)
    (project_dir / "drafts").mkdir(parents=True, exist_ok=True)
    (project_dir / "logs").mkdir(parents=True, exist_ok=True)
    logger.info("Created project directory: %s", project_dir)

    # 2. Write novel_spec.json
    spec = build_novel_spec(backlog)
    spec_path = project_dir / "config" / "novel_spec.json"
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s", spec_path.relative_to(REPO_ROOT))

    # 3. Write pipeline_state.json with interactive_setup COMPLETED
    state = build_pipeline_state(dir_name)
    state_path = project_dir / "state" / "pipeline_state.json"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info("Wrote %s (interactive_setup=completed)", state_path.relative_to(REPO_ROOT))

    # 4. Write project-local generation_config.yaml
    config_content = build_generation_config(backlog)
    config_path = project_dir / "generation_config.yaml"
    config_path.write_text(config_content, encoding="utf-8")
    logger.info("Wrote %s", config_path.relative_to(REPO_ROOT))

    # 5. Append to root config novels list
    append_to_root_novels_list(
        dir_name, backlog["slug"], backlog["title"], backlog["description"],
    )

    # 6. Update backlog status
    update_backlog_status(backlog_path, "in_progress", dir_name)

    logger.info("Novel '%s' initialized successfully at %s", backlog["title"], dir_name)
    return dir_name


def main():
    parser = argparse.ArgumentParser(description="Initialize a novel project from a backlog YAML file.")
    parser.add_argument("backlog_file", type=Path, help="Path to backlog YAML file")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be done without making changes")
    args = parser.parse_args()

    backlog_path = args.backlog_file
    if not backlog_path.is_absolute():
        backlog_path = REPO_ROOT / backlog_path

    if not backlog_path.exists():
        logger.error("Backlog file not found: %s", backlog_path)
        sys.exit(1)

    try:
        dir_name = init_novel(backlog_path, dry_run=args.dry_run)
        print(f"\nProject directory: {dir_name}")
    except Exception:
        logger.exception("Failed to initialize novel")
        sys.exit(1)


if __name__ == "__main__":
    main()
