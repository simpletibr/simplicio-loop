"""Direct unit tests for simplicio_mapper.mapper.emit (issue #159 split).

Exercises the serialization layer in isolation -- imports straight from
``simplicio_mapper.mapper.emit``.

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

from simplicio_mapper.mapper.emit import (  # noqa: E402
    _slugify,
    _write_json_stable,
    _write_text_stable,
    build_artifacts,
    write_mapping_artifacts,
)


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class SlugifyTest(unittest.TestCase):
    def test_slugify_lowercases_and_dashes(self) -> None:
        self.assertEqual(_slugify("Hello World!"), "hello-world")

    def test_slugify_prefixes_dotfiles_with_dot_marker(self) -> None:
        # A leading "." is stripped by the dash-collapsing regex, so
        # dotfiles get an explicit "dot-" marker instead of vanishing.
        self.assertEqual(_slugify(".gitignore"), "dot-gitignore")


class WriteStableTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_json_stable_roundtrips(self) -> None:
        target = self.dir / "out" / "data.json"
        _write_json_stable(str(target), {"a": 1, "b": [1, 2, 3]})
        self.assertEqual(json.loads(target.read_text()), {"a": 1, "b": [1, 2, 3]})

    def test_write_text_stable_roundtrips(self) -> None:
        target = self.dir / "out" / "note.md"
        _write_text_stable(str(target), "# hello\n")
        self.assertEqual(target.read_text(), "# hello\n")


class BuildArtifactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/index.js", "module.exports = () => 'hi';\n")
        _write(self.dir, "package.json", '{"name": "fixture"}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_artifacts_returns_all_five_artifact_dicts(self) -> None:
        artifacts = build_artifacts(str(self.dir), meta={"stack": "javascript"})
        self.assertEqual(
            set(artifacts.keys()),
            {
                "project_map",
                "precedent_index",
                "architecture_inventory",
                "symbol_index",
                "call_graph",
                # Execution receipt for the sync/async pipeline dispatch
                # decision (calibration/benchmark observability); always
                # present alongside the five artifact dicts.
                "execution_plan",
            },
        )
        self.assertEqual(artifacts["project_map"]["schema"], "simplicio.project-map/v1")
        self.assertIn("agent_tree", artifacts["project_map"])

    def test_write_mapping_artifacts_writes_json_files_to_disk(self) -> None:
        write_mapping_artifacts(str(self.dir))
        out = self.dir / ".simplicio"
        for name in ("project-map.json", "precedent-index.json", "architecture-inventory.json"):
            self.assertTrue((out / name).exists(), f"missing {name}")


if __name__ == "__main__":
    unittest.main()
