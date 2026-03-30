"""Utilities to backfill compliance artifacts for legacy runs."""

from __future__ import annotations

import json
from pathlib import Path


def backfill_compliance_reports(project_dir: Path) -> int:
    """Create minimal compliance reports from legacy gate artifacts.

    Returns number of compliance files created.
    """
    quality_dir = Path(project_dir) / "state" / "quality_reports"
    if not quality_dir.exists():
        return 0

    created = 0
    gate_files = sorted(quality_dir.glob("chapter_[0-9][0-9]_gates.json"))
    for gate_file in gate_files:
        chapter_tag = gate_file.stem.replace("_gates", "")
        compliance_file = quality_dir / f"{chapter_tag}_compliance.json"
        if compliance_file.exists():
            continue

        chapter_num = int(chapter_tag.split("_")[1])
        with open(gate_file, "r", encoding="utf-8") as fh:
            gate_data = json.load(fh)
        scene_file = quality_dir / f"{chapter_tag}_scene_contracts.json"
        completion_file = quality_dir / f"{chapter_tag}_completion_gate.json"
        scene_data = {}
        completion_data = {}
        if scene_file.exists():
            with open(scene_file, "r", encoding="utf-8") as fh:
                scene_data = json.load(fh)
        if completion_file.exists():
            with open(completion_file, "r", encoding="utf-8") as fh:
                completion_data = json.load(fh)

        all_gates_passed = bool(gate_data.get("all_passed", False))
        scene_passed = bool(scene_data.get("all_passed", True))
        completion_failed = bool(completion_data.get("completion_gate_failed", False))
        report = {
            "chapter_number": chapter_num,
            "status": "unknown_legacy",
            "acceptance_passed": False,
            "bypass_flags_used": ["migrated_legacy_artifact"],
            "deterministic": {
                "passed": all_gates_passed and scene_passed and not completion_failed,
                "structural_passed": True,
                "scene_contracts_passed": scene_passed,
                "chapter_contracts_passed": True,
                "failures": [],
                "scene_results": [],
                "chapter_requirements": [],
            },
            "semantic": {
                "passed": False,
                "confidence": 0.0,
                "requirement_results": [],
                "failures": ["legacy_run_without_semantic_validation"],
                "raw_validator": "migration_backfill",
            },
            "adversarial": {"triggered": False, "passed": True, "reason": "", "requirement_results": []},
            "retries": {"chapter_gate_retries": int(gate_data.get("retry_count", 0))},
            "model_routing": {},
        }
        with open(compliance_file, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=True)
            fh.write("\n")
        created += 1
    return created

