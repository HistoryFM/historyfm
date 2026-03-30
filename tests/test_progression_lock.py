"""Tests for acceptance-driven chapter progression lock."""

import tempfile
import unittest
from pathlib import Path

from sovereign_ink.state.manager import StateManager


class TestProgressionLock(unittest.TestCase):
    def test_next_unaccepted_uses_chapter_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = StateManager(Path(tmp))
            manager.save_chapter_state(
                1,
                {
                    "chapter_number": 1,
                    "state": "accepted",
                    "accepted": True,
                    "accepted_draft_version": "v3_polish",
                    "attempt_count": 1,
                    "last_failures": [],
                },
            )
            manager.save_chapter_draft(1, "polished text", "v3_polish")
            manager.save_compliance_report(
                1,
                {
                    "chapter_number": 1,
                    "acceptance_passed": True,
                    "status": "passed",
                },
            )
            manager.save_chapter_state(
                2,
                {
                    "chapter_number": 2,
                    "state": "repair",
                    "accepted": False,
                    "accepted_draft_version": None,
                    "attempt_count": 3,
                    "last_failures": ["scene contract mismatch"],
                },
            )
            self.assertEqual(manager.get_next_unaccepted_chapter(3), 2)
            manager.release_lock()

    def test_next_unaccepted_falls_back_to_compliance_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = StateManager(Path(tmp))
            manager.save_chapter_draft(1, "polished text", "v3_polish")
            manager.save_chapter_state(
                1,
                {
                    "chapter_number": 1,
                    "state": "accepted",
                    "accepted": True,
                    "accepted_draft_version": "v3_polish",
                    "attempt_count": 1,
                    "last_failures": [],
                },
            )
            manager.save_compliance_report(
                1,
                {
                    "chapter_number": 1,
                    "acceptance_passed": True,
                    "status": "passed",
                },
            )
            self.assertIsNone(manager.get_next_unaccepted_chapter(1))
            manager.release_lock()

    def test_is_chapter_fully_accepted_requires_v3_state_and_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = StateManager(Path(tmp))
            manager.save_chapter_state(
                1,
                {
                    "chapter_number": 1,
                    "state": "accepted",
                    "accepted": True,
                    "accepted_draft_version": "v3_polish",
                    "attempt_count": 1,
                    "last_failures": [],
                },
            )
            self.assertFalse(manager.is_chapter_fully_accepted(1))
            manager.save_chapter_draft(1, "polished text", "v3_polish")
            self.assertTrue(manager.is_chapter_fully_accepted(1))
            manager.release_lock()


if __name__ == "__main__":
    unittest.main()
