"""Compatibility + unit tests for ContextSnapshot/ContextGraph (issue #208, Step 1).

Covers the AC items this slice owns:

* ContextSnapshot/ContextGraph v1 possesses a schema, fixtures, canonical hash
  and compatibility tests (AC 1).
* A clean install can validate a snapshot against the shipped schema (AC 2) —
  exercised both via the package dir and the checkout fallback.
* snapshot_id is content-addressed and deterministic (same inputs -> same id;
  one changed byte -> different id).
* Every graph node/edge carries a reversible source handle + content hash.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import unittest

from simplicio_mapper import __version__
from simplicio_mapper.context_snapshot import (
    CONTEXT_GRAPH_SCHEMA,
    CONTEXT_SNAPSHOT_SCHEMA,
    build_context_graph,
    build_context_snapshot,
    from_package,
    snapshot_id_of,
    source_handle,
)
from simplicio_mapper.contract import validate_payload

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE_LATEST = os.path.join(REPO_ROOT, "contracts", "context-snapshot", "v1", "fixtures", "latest", "context-snapshot.json")
FIXTURE_MINIMUM = os.path.join(REPO_ROOT, "contracts", "context-snapshot", "v1", "fixtures", "minimum", "context-snapshot.json")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _minimal_artifacts():
    project_map = {
        "schema": "simplicio.project-map/v1", "version": 1,
        "product": {"name": "minimum-example", "stack": "python"},
        "files": [{"path": "app.py", "language": "python", "roles": ["source"], "imports": ["os"], "exports": ["main"]}],
    }
    symbol_index = {
        "schema": "simplicio.symbol-index/v1", "version": 1,
        "symbols": [{"name": "main", "kind": "function", "qualified_name": "main", "defined_in": "app.py", "line": 3}],
    }
    call_graph = {
        "schema": "simplicio.call-graph/v1", "version": 1,
        "edges": [{"type": "calls", "source_file": "app.py", "source_symbol": "main", "target_file": "app.py", "target_symbol": "helper", "line": 4, "confidence": 0.5}],
    }
    architecture_inventory = {
        "schema": "simplicio.architecture-inventory/v1", "version": 1,
        "modules": [{"name": "root", "file_count": 1, "layers": ["app"]}],
        "layers": [{"name": "app", "file_count": 1, "modules": ["root"]}],
    }
    return project_map, symbol_index, call_graph, architecture_inventory


class ContextSnapshotTest(unittest.TestCase):
    def test_schema_constants(self):
        self.assertEqual(CONTEXT_SNAPSHOT_SCHEMA, "simplicio.context-snapshot/v1")
        self.assertEqual(CONTEXT_GRAPH_SCHEMA, "simplicio.context-graph/v1")

    def test_snapshot_id_is_content_addressed_and_deterministic(self):
        pm, si, cg, ai = _minimal_artifacts()
        a = build_context_snapshot("/repo", project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai, revision="r1")
        b = build_context_snapshot("/repo", project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai, revision="r1")
        self.assertEqual(a["snapshot_id"], b["snapshot_id"])
        # one changed byte in a source artifact must change the id
        pm2 = json.loads(json.dumps(pm))
        pm2["files"][0]["path"] = "other.py"
        c = build_context_snapshot("/repo", project_map=pm2, symbol_index=si, call_graph=cg, architecture_inventory=ai, revision="r1")
        self.assertNotEqual(c["snapshot_id"], a["snapshot_id"])

    def test_snapshot_id_recomputed_matches_stored(self):
        pm, si, cg, ai = _minimal_artifacts()
        snap = build_context_snapshot("/repo", project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai)
        self.assertEqual(snapshot_id_of(snap), snap["snapshot_id"])

    def test_snapshot_required_fields_present(self):
        pm, si, cg, ai = _minimal_artifacts()
        snap = build_context_snapshot(
            "/repo", project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai,
            revision="r1",
        )
        for key in ("schema", "schema_version", "snapshot_id", "repository_id", "revision",
                    "root_hash", "producer", "source_set", "exclusions", "reason_codes",
                    "graph", "task", "generated_at"):
            self.assertIn(key, snap, f"missing {key}")
        self.assertEqual(snap["schema"], "simplicio.context-snapshot/v1")
        self.assertEqual(snap["schema_version"], "v1")
        self.assertEqual(snap["producer"]["name"], "simplicio-mapper")
        self.assertEqual(snap["producer"]["version"], __version__)

    def test_graph_has_micro_meso_macro_nodes_with_source_handles(self):
        pm, si, cg, ai = _minimal_artifacts()
        graph = build_context_graph(project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai)
        d = graph.to_dict()
        scales = {n["scale"] for n in d["nodes"]}
        self.assertTrue({"micro", "meso", "macro"} <= scales)
        self.assertTrue(d["drilldown"]["reversible"])
        self.assertIn("micro", d["scale_semantics"])
        # every node carries a content hash + reversible source handle
        for node in d["nodes"]:
            self.assertTrue(node["content_hash"])
            self.assertIn("file", node["source"])
        for edge in d["edges"]:
            self.assertTrue(edge["content_hash"])
            self.assertIn("file", edge["source_handle"])

    def test_source_handle_records_line_or_span(self):
        self.assertEqual(source_handle("a.py", line=7), {"file": "a.py", "line": 7})
        self.assertEqual(source_handle("b.py", span=(1, 9)), {"file": "b.py", "span": [1, 9]})
        self.assertEqual(source_handle("c.py"), {"file": "c.py"})

    def test_graph_edges_link_micro_and_meso(self):
        pm, si, cg, ai = _minimal_artifacts()
        graph = build_context_graph(project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai)
        d = graph.to_dict()
        kinds = {e["kind"] for e in d["edges"]}
        self.assertIn("calls", kinds)
        self.assertIn("member_of", kinds)
        self.assertIn("defined_in", kinds)

    def test_snapshot_carries_freshness_fidelity_and_drilldown_metadata(self):
        pm, si, cg, ai = _minimal_artifacts()
        snap = build_context_snapshot("/repo", project_map=pm, symbol_index=si, call_graph=cg, architecture_inventory=ai)
        self.assertIn("freshness", snap)
        self.assertIn("artifact_hashes", snap["freshness"])
        self.assertEqual(snap["fidelity"]["status"], "complete")
        self.assertTrue(snap["drilldown"]["reversible"])
        self.assertEqual(snap["scale_semantics"]["macro"]["kinds"], ["adr", "subsystem"])

    def test_from_package_resolves_shipped_schema(self):
        schema = from_package("simplicio.context-snapshot/v1")
        self.assertEqual(schema["$id"], "simplicio.context-snapshot/v1")
        graph_schema = from_package("simplicio.context-graph/v1")
        self.assertEqual(graph_schema["$id"], "simplicio.context-graph/v1")

    def test_fixtures_validate_against_shipped_schema(self):
        for fixture in (FIXTURE_LATEST, FIXTURE_MINIMUM):
            self.assertTrue(os.path.isfile(fixture), fixture)
            payload = _load(fixture)
            contract_root = os.path.join(REPO_ROOT, "contracts", "context-snapshot", "v1")
            schema_id, errors = validate_payload(payload, contract_root)
            self.assertEqual(errors, [], errors)
            self.assertEqual(schema_id, "simplicio.context-snapshot/v1")
            graph_id, graph_errors = validate_payload(payload["graph"], contract_root)
            self.assertEqual(graph_errors, [], graph_errors)
            self.assertEqual(graph_id, "simplicio.context-graph/v1")

    def test_validate_rejects_missing_required_field(self):
        payload = _load(FIXTURE_MINIMUM)
        del payload["snapshot_id"]
        contract_root = os.path.join(REPO_ROOT, "contracts", "context-snapshot", "v1")
        _schema_id, errors = validate_payload(payload, contract_root)
        self.assertTrue(errors, "expected a missing-required-field error")

    def test_omissions_flagged_when_artifacts_missing(self):
        snap = build_context_snapshot("/repo")
        self.assertTrue(snap["needs_broader_context"])
        self.assertIn("project-map", snap["task"]["omissions"])
        self.assertIn("symbol-index", snap["task"]["omissions"])

    def test_cli_snapshot_validate_end_to_end(self):
        # `snapshot validate` must accept both fixtures and exit 0.
        import subprocess

        proc = subprocess.run(
            [
                "python3", "-m", "simplicio_mapper.cli", "snapshot", "validate",
                FIXTURE_LATEST, FIXTURE_MINIMUM,
            ],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("[ok]", proc.stdout)


if __name__ == "__main__":
    unittest.main()
