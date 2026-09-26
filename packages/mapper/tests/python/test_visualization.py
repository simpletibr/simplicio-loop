import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.contract import find_contract_root, load_schema, validate_instance
from simplicio_mapper.mapper import build_artifacts
from simplicio_mapper.visualization import VISUALIZATION_SCHEMA, build_visualization_bundle


class VisualizationBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def main():\n    return helper()\n\ndef helper():\n    return 1\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\nname = 'fixture-app'\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_bundle_is_versioned_schema_valid_and_has_real_graph(self) -> None:
        artifacts = build_artifacts(str(self.root), meta={"stack": "python"})
        bundle = build_visualization_bundle(str(self.root), artifacts, generated_at="2026-01-01T00:00:00Z")
        self.assertEqual(bundle["schema"], VISUALIZATION_SCHEMA)
        errors = validate_instance(bundle, load_schema(VISUALIZATION_SCHEMA, find_contract_root()))
        self.assertEqual(errors, [])
        self.assertEqual(bundle["generated_at"], "2026-01-01T00:00:00Z")
        self.assertEqual(bundle["provenance"]["clone_type"], "plain-folder")
        self.assertTrue(any(node["kind"] == "file" for node in bundle["nodes"]))
        self.assertTrue(any(edge["type"] == "calls" for edge in bundle["edges"]))
        self.assertTrue(all("source_location" in edge for edge in bundle["edges"]))

    def test_ids_ignore_generation_time_and_remote_secrets_are_removed(self) -> None:
        artifacts = build_artifacts(str(self.root), meta={"stack": "python"})
        first = build_visualization_bundle(str(self.root), artifacts, generated_at="a")
        second = build_visualization_bundle(str(self.root), artifacts, generated_at="b")
        self.assertEqual([node["id"] for node in first["nodes"]], [node["id"] for node in second["nodes"]])
        self.assertNotIn("user", json.dumps(first["provenance"]))

    def test_committed_golden_fixture_validates(self) -> None:
        fixture = Path(__file__).parents[2] / "simplicio_mapper" / "contracts" / "visualization" / "v1" / "fixtures" / "python-minimal" / "visualization-bundle.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        errors = validate_instance(payload, load_schema(VISUALIZATION_SCHEMA, find_contract_root()))
        self.assertEqual(errors, [])
