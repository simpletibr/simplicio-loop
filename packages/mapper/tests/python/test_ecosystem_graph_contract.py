"""Contract and integrity tests for simplicio.ecosystem-graph/v1."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.ecosystem_contract import (  # noqa: E402
    load_schema,
    validate_file,
    validate_payload,
)

CONTRACT_ROOT = ROOT / "simplicio_mapper" / "contracts" / "ecosystem" / "v1"
FIXTURE_ROOT = CONTRACT_ROOT / "fixtures" / "asolaria-ecosystem"
GRAPH_FILE = FIXTURE_ROOT / "ecosystem-graph.json"
CANVAS_FILE = FIXTURE_ROOT / "canvas-flow.json"
STANDALONE = ROOT / "scripts" / "validate_ecosystem_contracts.py"


class EcosystemGraphContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))

    def validate_tampered(self, mutator) -> list[str]:
        tampered = json.loads(json.dumps(self.graph))
        mutator(tampered)
        _, errors = validate_payload(tampered, str(CONTRACT_ROOT))
        return errors

    def test_schema_loads_and_fixture_validates(self) -> None:
        schema = load_schema("simplicio.ecosystem-graph/v1", str(CONTRACT_ROOT))
        self.assertEqual(schema["title"], "simplicio.ecosystem-graph/v1")
        schema_id, errors = validate_file(str(GRAPH_FILE), str(CONTRACT_ROOT))
        self.assertEqual(schema_id, "simplicio.ecosystem-graph/v1")
        self.assertEqual(errors, [])

    def test_repository_ids_and_edge_ids_are_unique(self) -> None:
        repo_ids = [repo["id"] for repo in self.graph["repositories"]]
        edge_ids = [edge["id"] for edge in self.graph["edges"]]
        self.assertEqual(len(repo_ids), len(set(repo_ids)))
        self.assertEqual(len(edge_ids), len(set(edge_ids)))

    def test_edges_reference_known_repositories_and_have_evidence(self) -> None:
        repo_ids = {repo["id"] for repo in self.graph["repositories"]}
        for edge in self.graph["edges"]:
            with self.subTest(edge=edge["id"]):
                self.assertIn(edge["from"], repo_ids)
                self.assertIn(edge["to"], repo_ids)
                self.assertTrue(edge["evidence"])
                self.assertTrue(all(item["url"].startswith("https://") for item in edge["evidence"]))

    def test_available_repository_revisions_are_immutable_sha_ids(self) -> None:
        for repo in self.graph["repositories"]:
            if repo["access"] != "available":
                continue
            with self.subTest(repository=repo["name"]):
                self.assertRegex(repo["revision"], re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"))
                self.assertTrue(repo["url"].startswith("https://"))

    def test_research_references_keep_explicit_boundaries(self) -> None:
        references = {item["id"]: item for item in self.graph["references"]}
        self.assertEqual(set(references), {"encrypted-cloning", "matter-wave", "global-workspace"})
        for item in references.values():
            self.assertTrue(item["boundary"])
            self.assertTrue(item["url"].startswith("https://"))

    def test_unknown_status_is_rejected_by_schema(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["repositories"][0].__setitem__("status", "everything-is-live")
        )
        self.assertTrue(any("status" in error and "enum" in error for error in errors))

    def test_duplicate_repository_id_is_rejected_semantically(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["repositories"][1].__setitem__(
                "id", graph["repositories"][0]["id"]
            )
        )
        self.assertTrue(any("duplicate repository id" in error for error in errors))

    def test_duplicate_edge_id_is_rejected_semantically(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["edges"][1].__setitem__("id", graph["edges"][0]["id"])
        )
        self.assertTrue(any("duplicate edge id" in error for error in errors))

    def test_dangling_edge_endpoint_is_rejected_semantically(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["edges"][0].__setitem__("to", "missing-repository")
        )
        self.assertTrue(any("unknown repository id" in error for error in errors))

    def test_available_repository_requires_full_immutable_revision(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["repositories"][0].__setitem__("revision", "main")
        )
        self.assertTrue(any("immutable revision" in error for error in errors))

    def test_evidence_urls_require_https(self) -> None:
        errors = self.validate_tampered(
            lambda graph: graph["edges"][0]["evidence"][0].__setitem__(
                "url", "http://example.invalid/evidence"
            )
        )
        self.assertTrue(any("evidence URL must use https" in error for error in errors))

    def test_reference_ids_are_unique_and_boundaries_nonempty(self) -> None:
        duplicate_errors = self.validate_tampered(
            lambda graph: graph["references"][1].__setitem__(
                "id", graph["references"][0]["id"]
            )
        )
        boundary_errors = self.validate_tampered(
            lambda graph: graph["references"][0].__setitem__("boundary", "")
        )
        self.assertTrue(any("duplicate reference id" in error for error in duplicate_errors))
        self.assertTrue(any("boundary must not be empty" in error for error in boundary_errors))


class CanvasCompatibilityProjectionTest(unittest.TestCase):
    def test_canvas_flow_edges_resolve_to_declared_node_paths(self) -> None:
        flow = json.loads(CANVAS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(flow["format"], "simplicio-mapper-flow")
        paths = {node["path"] for node in flow["nodes"]}
        self.assertGreaterEqual(len(paths), 20)
        for edge in flow["edges"]:
            with self.subTest(edge=f"{edge['from']}->{edge['to']}"):
                self.assertIn(edge["from"], paths)
                self.assertIn(edge["to"], paths)
                self.assertTrue(edge.get("type"))
                self.assertTrue(edge.get("label"))

    def test_projection_is_explicitly_metadata_only(self) -> None:
        flow = json.loads(CANVAS_FILE.read_text(encoding="utf-8"))
        self.assertIn("metadata only", flow["source"])
        serialized = json.dumps(flow).lower()
        self.assertNotIn("private_key", serialized)
        self.assertNotIn("authorization", serialized)
        self.assertNotIn("password", serialized)

    def test_standalone_validator_accepts_authoritative_graph(self) -> None:
        result = subprocess.run(
            [sys.executable, str(STANDALONE), str(GRAPH_FILE)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("simplicio.ecosystem-graph/v1", result.stdout)

    def test_standalone_validator_rejects_semantic_tamper(self) -> None:
        tampered = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
        tampered["edges"][0]["to"] = "missing-repository"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(STANDALONE), str(path)],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown repository id", result.stdout)


if __name__ == "__main__":
    unittest.main()
