from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmarks.compare_fast import apply_deterministic_change, direct_target


class CompareFastAlterationTest(unittest.TestCase):
    def test_fixture_change_is_deterministic_and_compileable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "service.py"
            source.write_text(
                "def task_7(value):\n    return value\n", encoding="utf-8"
            )
            self.assertEqual(source, direct_target(root, "task_7"))
            apply_deterministic_change(source)
            self.assertIn("return value + 1", source.read_text(encoding="utf-8"))
