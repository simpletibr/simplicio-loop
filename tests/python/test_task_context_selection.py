from __future__ import annotations

import builtins
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.task_context import select_context_targets


class TaskContextSelectionIOTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src/cache").mkdir(parents=True)
        (self.root / "docs").mkdir()
        (self.root / "src/cache/token_cache.py").write_text(
            "class TokenCache:\n    def evict(self):\n        return None\n",
            encoding="utf-8",
        )
        (self.root / "docs/release-notes.md").write_text(
            "release notes only\n",
            encoding="utf-8",
        )
        self.project_map = {
            "files": [
                {
                    "path": "src/cache/token_cache.py",
                    "roles": ["domain"],
                    "language": "python",
                    "exports": ["TokenCache"],
                    "importance": 0.6,
                },
                {
                    "path": "docs/release-notes.md",
                    "roles": ["docs"],
                    "language": "markdown",
                    "importance": 0.9,
                },
            ],
        }
        self.symbol_index = {
            "symbols": [
                {
                    "defined_in": "src/cache/token_cache.py",
                    "name": "TokenCache",
                    "kind": "class",
                    "line": 1,
                }
            ]
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_selector_does_not_open_irrelevant_candidate_files(self) -> None:
        opened: list[str] = []
        real_open = builtins.open

        def recording_open(file, *args, **kwargs):
            path = str(file)
            if path.endswith(".py") or path.endswith(".md"):
                opened.append(path.replace("\\", "/"))
            return real_open(file, *args, **kwargs)

        try:
            builtins.open = recording_open
            selection = select_context_targets(
                str(self.root),
                self.project_map,
                goal="Fix TokenCache eviction",
                limit=1,
                symbol_index=self.symbol_index,
            )
        finally:
            builtins.open = real_open

        self.assertEqual([row["path"] for row in selection["targets"]], ["src/cache/token_cache.py"])
        self.assertTrue(any(path.endswith("/src/cache/token_cache.py") for path in opened))
        self.assertFalse(any(path.endswith("/docs/release-notes.md") for path in opened))


if __name__ == "__main__":
    unittest.main()
