"""Hypothesis state stays out of the mapper source tree.

The suite runs with ``packages/mapper`` as its working directory, and Hypothesis's default home is
``<cwd>/.hypothesis``: its example database and its constant and unicode caches would land inside the
source tree on every run. ``conftest.py`` moves that home (and the example database) to a cache
directory outside it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from hypothesis import settings
from hypothesis.configuration import storage_directory
from hypothesis.database import DirectoryBasedExampleDatabase

MAPPER_ROOT = Path(__file__).resolve().parents[2]


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


class HypothesisStorageLocationTest(unittest.TestCase):
    def test_example_database_is_outside_the_source_tree(self) -> None:
        database = settings.default.database
        self.assertIsInstance(database, DirectoryBasedExampleDatabase)
        location = Path(database.path)
        self.assertFalse(_inside(location, MAPPER_ROOT), f"example database inside the mapper tree: {location}")
        self.assertFalse(_inside(location, Path.cwd()), f"example database inside the working tree: {location}")

    def test_hypothesis_caches_are_outside_the_working_tree(self) -> None:
        for name in ("constants", "unicode_data"):
            location = storage_directory(name, intent_to_write=False).path
            self.assertFalse(_inside(location, MAPPER_ROOT), f"{name} cache inside the mapper tree: {location}")
            self.assertFalse(_inside(location, Path.cwd()), f"{name} cache inside the working tree: {location}")


if __name__ == "__main__":
    unittest.main()
