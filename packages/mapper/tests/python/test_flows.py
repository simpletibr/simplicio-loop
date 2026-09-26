"""Unit tests for simplicio_mapper.flows (F2 flow-inventory).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.flows import (  # noqa: E402
    FLOW_INVENTORY_SCHEMA,
    _flow_diagram_svgs,
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

    def test_markdown_render_includes_call_sequence_and_svg_links(self) -> None:
        app_dir = self._fixture_app()
        artifacts = build_artifacts(str(app_dir))
        inventory = build_flow_inventory(str(app_dir), artifacts)
        markdown = render_flow_inventory_markdown(inventory)
        self.assertIn("sequenceDiagram", markdown)
        self.assertIn("Call Sequence", markdown)
        self.assertIn("-steps.svg", markdown)
        self.assertIn("-sequence.svg", markdown)

    def test_flow_diagram_svgs_are_well_formed_and_keyed_per_flow(self) -> None:
        app_dir = self._fixture_app()
        artifacts = build_artifacts(str(app_dir))
        inventory = build_flow_inventory(str(app_dir), artifacts)
        extras = _flow_diagram_svgs(inventory)
        self.assertTrue(extras)
        for rel_path, svg in extras.items():
            self.assertTrue(rel_path.startswith("diagrams/flows/"))
            self.assertTrue(rel_path.endswith(("-steps.svg", "-sequence.svg")))
            ET.fromstring(svg)

    def test_flow_diagram_svgs_survive_slug_collisions(self) -> None:
        # "cli:flowchart" and "cli/flowchart" both slugify to "cli-flowchart"
        # -- without an index suffix the second flow's SVGs silently
        # overwrite the first's in the extras dict.
        inventory = {
            "flows": [
                {"id": "cli:flowchart", "steps": [{"path": "a.py"}, {"path": "b.py"}]},
                {"id": "cli/flowchart", "steps": [{"path": "c.py"}, {"path": "d.py"}]},
            ]
        }
        extras = _flow_diagram_svgs(inventory)
        self.assertEqual(len(extras), 4)  # 2 flows x (steps + sequence), none overwritten
        steps_svgs = {path: svg for path, svg in extras.items() if path.endswith("-steps.svg")}
        self.assertEqual(len(steps_svgs), 2)
        self.assertNotEqual(*steps_svgs.values())

    def test_flows_command_writes_json_and_doc(self) -> None:
        app_dir = self._fixture_app()
        out = StringIO()
        with redirect_stdout(out):
            code = main(["flows", str(app_dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], FLOW_INVENTORY_SCHEMA)
        inventory_path = app_dir / ".simplicio-loop" / "flow-inventory.json"
        doc_path = app_dir / ".simplicio-loop" / "docs" / "flows.md"
        self.assertTrue(inventory_path.exists())
        self.assertTrue(doc_path.exists())
        diagrams_dir = app_dir / ".simplicio-loop" / "docs" / "diagrams" / "flows"
        self.assertTrue(diagrams_dir.exists())
        self.assertTrue(list(diagrams_dir.glob("*.svg")))


if __name__ == "__main__":
    unittest.main()
