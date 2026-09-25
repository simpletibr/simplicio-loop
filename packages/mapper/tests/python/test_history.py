"""Unit tests for simplicio_mapper.history (F6 doc history + changelog).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.history import (  # noqa: E402
    DOC_HISTORY_SCHEMA,
    create_snapshot,
    diff_snapshots,
    list_snapshots,
    maybe_snapshot,
)


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class HistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "history-app", "main": "src/main.py"}))
        _write(self.dir, "src/main.py", "def main():\n    return 1\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unchanged_tree_creates_no_new_snapshot(self) -> None:
        first = create_snapshot(str(self.dir))
        self.assertIsNotNone(first)
        second = create_snapshot(str(self.dir))
        self.assertIsNone(second)
        self.assertEqual(len(list_snapshots(str(self.dir))), 1)

    def test_module_addition_is_captured_in_delta(self) -> None:
        create_snapshot(str(self.dir))
        _write(self.dir, "src/extra.py", "def extra():\n    return 2\n")
        _write(self.dir, "lib/helper.py", "def helper():\n    return 3\n")
        second = create_snapshot(str(self.dir))
        self.assertIsNotNone(second)
        self.assertIn("lib", second["delta"]["modules"]["added"])

    def test_diff_between_two_snapshots_matches_incremental_delta(self) -> None:
        first = create_snapshot(str(self.dir))
        _write(self.dir, "lib/helper.py", "def helper():\n    return 3\n")
        second = create_snapshot(str(self.dir))
        payload = diff_snapshots(str(self.dir), ".simplicio", first["id"], second["id"])
        self.assertEqual(payload["schema"], DOC_HISTORY_SCHEMA)
        self.assertEqual(payload["modules"]["added"], second["delta"]["modules"]["added"])

    def test_diff_unknown_id_raises(self) -> None:
        create_snapshot(str(self.dir))
        with self.assertRaises(ValueError):
            diff_snapshots(str(self.dir), ".simplicio", "nope", "also-nope")

    def test_retention_gc_removes_oldest_first(self) -> None:
        ids = []
        for i in range(5):
            _write(self.dir, f"src/gen_{i}.py", f"def gen_{i}():\n    return {i}\n")
            result = create_snapshot(str(self.dir), retention=2)
            if result:
                ids.append(result["id"])
        snapshots = list_snapshots(str(self.dir))
        self.assertLessEqual(len(snapshots), 2)
        self.assertEqual([s["id"] for s in snapshots], ids[-len(snapshots):])

    def test_maybe_snapshot_appends_changelog_once(self) -> None:
        maybe_snapshot(str(self.dir), trigger="map")
        changelog = self.dir / ".simplicio" / "docs" / "architecture-changelog.md"
        self.assertTrue(changelog.exists())
        first_text = changelog.read_text(encoding="utf-8")

        result = maybe_snapshot(str(self.dir), trigger="map")
        self.assertIsNone(result)
        self.assertEqual(changelog.read_text(encoding="utf-8"), first_text)

        _write(self.dir, "src/more.py", "def more():\n    return 1\n")
        maybe_snapshot(str(self.dir), trigger="map")
        second_text = changelog.read_text(encoding="utf-8")
        self.assertTrue(second_text.startswith(first_text))
        self.assertGreater(len(second_text), len(first_text))


if __name__ == "__main__":
    unittest.main()
