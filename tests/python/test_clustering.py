import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.clustering import CLUSTERING_SCHEMA, build_clustering_metrics
from simplicio_mapper.contract import find_contract_root, load_schema, validate_instance, validate_payload
from simplicio_mapper.mapper import build_artifacts
from simplicio_mapper.visualization import build_visualization_bundle


class ClusteringMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "backend").mkdir()
        (self.root / "frontend").mkdir()
        (self.root / "backend" / "service.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (self.root / "backend" / "test_service.py").write_text("from backend.service import run\ndef test_run():\n    run()\n", encoding="utf-8")
        (self.root / "frontend" / "app.ts").write_text("export function render() { return 1; }\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_metrics_are_deterministic_overlapping_and_versioned(self) -> None:
        artifacts = build_artifacts(str(self.root), meta={"stack": "mixed"})
        first = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00Z")
        second = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00Z")
        clustering = first["clustering"]
        self.assertEqual(first, second)
        self.assertEqual(clustering["schema"], CLUSTERING_SCHEMA)
        self.assertEqual(validate_payload(clustering, find_contract_root(str(self.root)))[1], [])
        kinds = {cluster["kind"] for cluster in clustering["clusters"]}
        self.assertTrue({"workspace", "directory", "package", "namespace", "domain", "layer"} <= kinds)
        self.assertTrue(any(cluster["overlapping"] for cluster in clustering["clusters"]))
        self.assertTrue(all("member_count" in cluster and "language_mix" in cluster for cluster in clustering["clusters"]))
        self.assertIn("clustering", first["provenance"])
        self.assertEqual(first["provenance"]["clustering"]["config"], clustering["config"])
        self.assertTrue(all("coordinates" not in hint for hint in clustering["layout_hints"]))

    def test_thresholds_and_hints_are_configurable(self) -> None:
        artifacts = build_artifacts(str(self.root), meta={"stack": "mixed"})
        payload = build_clustering_metrics(
            str(self.root),
            artifacts,
            {"min_cluster_size": 2, "community_min_size": 3, "layout_hints": {"enabled": False}},
            generated_at="1970-01-01T00:00:00Z",
        )
        self.assertTrue(all(cluster["member_count"] >= 2 for cluster in payload["clusters"]))
        self.assertEqual(payload["layout_hints"], [])
        self.assertEqual(payload["provenance"]["config"]["community_min_size"], 3)

    def test_committed_fixture_and_schema_validate(self) -> None:
        contract_root = find_contract_root()
        schema = load_schema(CLUSTERING_SCHEMA, contract_root)
        fixture = Path(__file__).parents[2] / "contracts" / "clustering" / "v1" / "fixtures" / "small-deterministic" / "clustering.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(validate_instance(payload, schema), [])


if __name__ == "__main__":
    unittest.main()
