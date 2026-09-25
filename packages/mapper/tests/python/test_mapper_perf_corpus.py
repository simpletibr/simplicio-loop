from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.mapper_perf_corpus import CORPUS_SIZES, content_digest, materialize


class MapperPerfCorpusTest(unittest.TestCase):
    def test_manifest_sizes_are_frozen(self) -> None:
        self.assertEqual(CORPUS_SIZES, {"tiny": 54, "small": 440, "medium": 1814, "xlarge": 7800})

    def test_materialization_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            materialize(first, "tiny")
            materialize(second, "tiny")
            self.assertEqual(content_digest(Path(first)), content_digest(Path(second)))


if __name__ == "__main__":
    unittest.main()
