"""Focused end-to-end checks for issue #195."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.mapper_canvas_compat import FIXTURE_NAMES, FIXTURES, _normalize, _run_mapper, check


class MapperCanvasCompatibilityTests(unittest.TestCase):
    def test_offline_harness_consumes_all_committed_goldens(self) -> None:
        self.assertEqual(check(), 0)

    def test_real_mapper_ids_survive_different_clone_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            for name in FIXTURE_NAMES:
                source = FIXTURES / name / "source"
                first = Path(temp) / f"a-{name}"
                second = Path(temp) / f"b-{name}"
                shutil.copytree(source, first)
                shutil.copytree(source, second)
                first_bundle = _normalize(_run_mapper(first))
                second_bundle = _normalize(_run_mapper(second))
                self.assertEqual(
                    [node["id"] for node in first_bundle["nodes"]],
                    [node["id"] for node in second_bundle["nodes"]],
                    name,
                )

    def test_metadata_contracts_are_versioned_and_cover_six_fixture_categories(self) -> None:
        matrix = json.loads((FIXTURES.parent / "compatibility-matrix.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["schema"], "simplicio.mapper-canvas-compatibility/v1")
        self.assertEqual({item["name"] for item in matrix["fixtures"]}, set(FIXTURE_NAMES))
        performance = json.loads((FIXTURES.parent / "performance-baseline.json").read_text(encoding="utf-8"))
        self.assertEqual({item["name"] for item in performance["fixtures"]}, set(FIXTURE_NAMES))


if __name__ == "__main__":
    unittest.main()
