"""Tests for legacy compliance backfill utility."""

import json
import tempfile
import unittest
from pathlib import Path

from sovereign_ink.utils.compliance_migration import backfill_compliance_reports


class TestComplianceMigration(unittest.TestCase):
    def test_backfill_creates_compliance_from_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            qdir = root / "state" / "quality_reports"
            qdir.mkdir(parents=True, exist_ok=True)
            gates = {
                "chapter_number": 1,
                "retry_count": 1,
                "gates": {"immediate_jeopardy": {"passed": True}},
                "all_passed": True,
            }
            (qdir / "chapter_01_gates.json").write_text(
                json.dumps(gates), encoding="utf-8"
            )
            created = backfill_compliance_reports(root)
            self.assertEqual(created, 1)
            compliance_path = qdir / "chapter_01_compliance.json"
            self.assertTrue(compliance_path.exists())
            data = json.loads(compliance_path.read_text(encoding="utf-8"))
            self.assertEqual(data["chapter_number"], 1)
            self.assertIn("migrated_legacy_artifact", data["bypass_flags_used"])


if __name__ == "__main__":
    unittest.main()

