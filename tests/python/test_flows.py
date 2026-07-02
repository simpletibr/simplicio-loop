"""Unit tests for simplicio_mapper.flows (F2 flow-inventory).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.flows import (  # noqa: E402
    FLOW_INVENTORY_SCHEMA,
    build_flow_inventory,
    render_flow_inventory_markdown,
)
from simplicio_mapper.mapper import build_artifacts  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class FlowInventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fixture_app(self) -> Path:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "flow-app", "main": "src/main.py"}))
        _write(
            app_dir,
            "src/main.py",
            "from src.writer import persist\n"
            "def main():\n"
            "    persist()\n",
        )
        _write(
            app_dir,
            "src/writer.py",
            "def persist():\n"
            "    with open('out.json', 'w') as handle:\n"
            "        handle.write('{}')\n",
        )
        return app_dir

    def test_build_flow_inventory_detects_fs_write_effect(self) -> None:
        app_dir = self._fixture_app()
        artifacts = build_artifacts(str(app_dir))
        inventory = build_flow_inventory(str(app_dir), artifacts)

        self.assertEqual(inventory["schema"], FLOW_INVENTORY_SCHEMA)
        self.assertGreaterEqual(len(inventory["flows"]), 1)
        main_flow = next(f for f in inventory["flows"] if f["entry"]["path"] == "src/main.py")
        effect_types = {effect["type"] for effect in main_flow["effects"]}
        self.assertIn("fs-write", effect_types)
        self.assertEqual(main_flow["confidence"], "observed")
        for effect in main_flow["effects"]:
            self.assertIn("path", effect["evidence"])
            self.assertIn("line", effect["evidence"])

    def test_coverage_reports_entrypoints_without_flow(self) -> None:
        app_dir = self.dir / "empty-app"
        _write(app_dir, "package.json", json.dumps({"name": "empty-app"}))
        _write(app_dir, "README.md", "# empty\n")
        artifacts = build_artifacts(str(app_dir))
        inventory = build_flow_inventory(str(app_dir), artifacts)
        self.assertEqual(inventory["coverage"]["entrypoints_total"], 0)
        self.assertEqual(inventory["flows"], [])

    def test_determinism_same_tree_same_payload(self) -> None:
        app_dir = self._fixture_app()
        artifacts = build_artifacts(str(app_dir))
        first = build_flow_inventory(str(app_dir), artifacts)
        second = build_flow_inventory(str(app_dir), artifacts)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_markdown_render_includes_mermaid_and_effects_table(self) -> None:
        app_dir = self._fixture_app()
        artifacts = build_artifacts(str(app_dir))
        inventory = build_flow_inventory(str(app_dir), artifacts)
        markdown = render_flow_inventory_markdown(inventory)
        self.assertIn("```mermaid", markdown)
        self.assertIn("flowchart LR", markdown)
        self.assertIn("Effects", markdown)

    def test_flows_command_writes_json_and_doc(self) -> None:
        app_dir = self._fixture_app()
        out = StringIO()
        with redirect_stdout(out):
            code = main(["flows", str(app_dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], FLOW_INVENTORY_SCHEMA)
        inventory_path = app_dir / ".simplicio" / "flow-inventory.json"
        doc_path = app_dir / ".simplicio" / "docs" / "flows.md"
        self.assertTrue(inventory_path.exists())
        self.assertTrue(doc_path.exists())


if __name__ == "__main__":
    unittest.main()
