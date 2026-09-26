"""Regression coverage for issue #615's call-graph/retrieval seam."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.context_graph_contract import build_public_contract
from simplicio_mapper.context_pack import build_context_pack
from simplicio_mapper.context_snapshot import build_context_snapshot
from simplicio_mapper.execution_context import build_execution_context, validate_execution_context
from simplicio_mapper.mapper.emit import write_mapping_artifacts
from simplicio_mapper.mapper.graph import _build_call_graph, _build_symbol_index
from simplicio_mapper.mapper.parse import _build_file_inventory, _now_iso
from simplicio_mapper.query import run_query
from simplicio_mapper.relations import CALL_GRAPH_RELATION_EVIDENCE, canonicalize_relation
from simplicio_mapper.retrieval_index import build_retrieval_index, select_context_targets
from simplicio_mapper.toon import decode_toon, encode_toon


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class Mapper615RelationUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        _write(self.root, "pkg/one.py", "def run():\n    return 1\n")
        _write(self.root, "pkg/two.py", "def run():\n    return 2\n")
        _write(
            self.root,
            "pkg/caller.py",
            "def invoke():\n    return run()\n\ndef missing_call():\n    return missing_name()\n",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _graph(self, *, edge_limit: int | None = None) -> dict:
        files = _build_file_inventory(str(self.root), {}, {}, None)
        generated_at = _now_iso()
        symbols = _build_symbol_index(str(self.root), files, generated_at)
        return _build_call_graph(
            str(self.root), files, symbols, generated_at, edge_limit=edge_limit
        )

    def test_duplicate_names_are_ambiguous_and_have_distinct_relation_ids(self) -> None:
        graph = self._graph()
        calls = [
            edge
            for edge in graph["edges"]
            if edge["type"] == "calls" and edge.get("source_file") == "pkg/caller.py"
        ]
        duplicate_candidates = [
            edge
            for edge in calls
            if str(edge.get("target_symbol") or "").endswith("::run")
        ]
        self.assertEqual(
            {edge["target_file"] for edge in duplicate_candidates},
            {"pkg/one.py", "pkg/two.py"},
        )
        self.assertEqual({edge["evidence_class"] for edge in duplicate_candidates}, {"lexical_ambiguous"})
        self.assertEqual({edge["resolution_status"] for edge in duplicate_candidates}, {"ambiguous"})
        self.assertEqual(len({edge["relation_id"] for edge in duplicate_candidates}), 2)
        self.assertNotIn("semantic_resolved", {edge["evidence_class"] for edge in duplicate_candidates})

    def test_unknown_calls_are_omitted_from_the_graph(self) -> None:
        graph = self._graph()
        unknown_calls = [
            edge
            for edge in graph["edges"]
            if edge.get("type") == "calls"
            and (edge.get("target_file") is None or edge.get("resolution_status") == "unknown")
        ]
        self.assertEqual(unknown_calls, [])
        self.assertIn("missing_name", {item["queried_symbol"] for item in graph.get("unresolved") or []})
        project_map = {"files": [{"path": path} for path in ("pkg/one.py", "pkg/two.py", "pkg/caller.py")]}
        index = build_retrieval_index(project_map, call_graph=graph)
        self.assertEqual(index["call_graph"]["callers"].get(""), None)
        self.assertNotIn("", index["call_graph"]["callees"].get("pkg/caller.py", []))
        snapshot = build_context_snapshot(
            str(self.root),
            project_map=project_map,
            symbol_index={"symbols": []},
            call_graph=graph,
            architecture_inventory={},
        )
        snapshot_unknown_calls = [
            edge
            for edge in snapshot["graph"]["edges"]
            if edge.get("kind") == "calls" and edge.get("resolution_status") == "unknown"
        ]
        self.assertEqual(snapshot_unknown_calls, [])

    def test_edge_limit_reports_observed_and_omitted_coverage(self) -> None:
        graph = self._graph(edge_limit=1)
        coverage = graph["coverage"]
        self.assertTrue(coverage["truncated"])
        self.assertEqual(coverage["edge_limit"], 1)
        self.assertEqual(coverage["emitted_edges"], len(graph["edges"]))
        self.assertGreater(coverage["observed_edges"], coverage["emitted_edges"])
        self.assertEqual(graph["counts"]["edges"], len(graph["edges"]))

    def test_legacy_endpoint_shape_is_rejected_and_marked_degraded(self) -> None:
        self.assertIsNone(canonicalize_relation({"from": "a.py", "to": "b.py"}))
        self.assertIsNone(
            canonicalize_relation(
                {"source_file": "a.py", "target_file": "b.py", "from": "a.py", "to": "b.py"}
            )
        )
        unknown = canonicalize_relation(
            {
                "source_file": "a.py",
                "target_file": None,
                "evidence_class": "heuristic",
                "resolution_status": "resolved",
            }
        )
        self.assertEqual(unknown["resolution_status"], "unknown")
        ambiguous = canonicalize_relation(
            {
                "source_file": "a.py",
                "target_file": "b.py",
                "evidence_class": "lexical_ambiguous",
                "resolution_status": "resolved",
            }
        )
        self.assertEqual(ambiguous["resolution_status"], "ambiguous")
        index = build_retrieval_index(
            {"files": [{"path": "a.py"}, {"path": "b.py"}]},
            call_graph={"edges": [{"from": "a.py", "to": "b.py"}]},
        )
        self.assertEqual(index["call_graph"]["callees"], {})
        self.assertEqual(index["relation_coverage"]["invalid_edges"], 1)
        self.assertEqual(index["relation_coverage"]["status"], "degraded")


class Mapper615DifferentialIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        _write(self.root, "package.json", '{"name":"mapper-615-fixture"}\n')
        _write(self.root, "src/target.py", "def target():\n    return 1\n")
        _write(
            self.root,
            "src/caller.py",
            "from src.target import target\n\ndef invoke():\n    return target()\n",
        )
        _write(
            self.root,
            "tests/test_target.py",
            "from src.target import target\n\ndef test_target():\n    assert target() == 1\n",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_serialized_artifacts(self) -> dict[str, dict]:
        write_mapping_artifacts(str(self.root), output_dir=".simplicio-loop")
        artifact_dir = self.root / ".simplicio-loop"
        names = (
            "project-map",
            "precedent-index",
            "symbol-index",
            "call-graph",
            "architecture-inventory",
        )
        return {
            name: json.loads((artifact_dir / f"{name}.json").read_text(encoding="utf-8"))
            for name in names
        }

    def test_serialized_producer_survives_retrieval_selection_and_queries(self) -> None:
        artifacts = self._build_serialized_artifacts()
        graph = artifacts["call-graph"]
        self.assertEqual(graph["schema"], "simplicio.call-graph/v1")
        self.assertTrue(graph["producer"]["canonical_digest"].startswith("sha256:"))
        canonical_edges = {edge["relation_id"]: edge for edge in graph["edges"]}
        self.assertTrue(canonical_edges)

        index = build_retrieval_index(
            artifacts["project-map"],
            symbol_index=artifacts["symbol-index"],
            call_graph=graph,
            root=str(self.root),
        )
        indexed_edges = {edge["relation_id"]: edge for edge in index["call_graph"]["relations"]}
        self.assertEqual(set(indexed_edges), set(canonical_edges))

        selection = select_context_targets(
            str(self.root),
            artifacts["project-map"],
            target="src/target.py",
            goal="target",
            symbol_index=artifacts["symbol-index"],
            call_graph=graph,
            retrieval_index=index,
        )
        expanded = next(item for item in selection["expanded_spans"] if item["path"] == "src/target.py")
        self.assertTrue(
            {edge["relation_id"] for edge in expanded["context_relations"]}
            & set(canonical_edges)
        )
        self.assertEqual(index["related_tests"]["src/target.py"], ["tests/test_target.py"])
        self.assertEqual(
            index["related_test_evidence"]["src/target.py"][0]["evidence_class"],
            "inferred_by_name",
        )
        measured_map = json.loads(json.dumps(artifacts["project-map"]))
        for entry in measured_map["files"]:
            if entry.get("path") == "tests/test_target.py":
                entry["test_evidence"] = {
                    "evidence_class": "runtime_observed",
                    "method": "pytest-coverage",
                    "measured": True,
                }
        measured_index = build_retrieval_index(
            measured_map,
            symbol_index=artifacts["symbol-index"],
            call_graph=graph,
            root=str(self.root),
        )
        self.assertEqual(
            measured_index["related_test_evidence"]["src/target.py"][0]["evidence_class"],
            "runtime_observed",
        )
        evidence_rows = [
            evidence
            for target in selection["targets"]
            for evidence in target["graph_neighbor_evidence"]
        ]
        self.assertTrue(evidence_rows)
        self.assertTrue(
            any(
                reason.startswith("call_graph_evidence=")
                for target in selection["targets"]
                for reason in target["reason_codes"]
            )
        )
        execution = build_execution_context(
            str(self.root),
            goal="target",
            task_fingerprint="mapper-615",
            acceptance_criteria=["preserve relation identity"],
            project_map=artifacts["project-map"],
            symbol_index=artifacts["symbol-index"],
            call_graph=graph,
            precedent_index=artifacts["precedent-index"],
            selection=selection,
            architecture_inventory=artifacts["architecture-inventory"],
        )
        self.assertEqual(validate_execution_context(execution), [])
        self.assertTrue(
            any(edge.get("relation_id") in canonical_edges for edge in execution["graph_edges"])
        )
        self.assertEqual(execution["graph_coverage"], selection["relation_coverage"])

        callers = run_query(str(self.root), verb="callers", arg="target")
        callees = run_query(str(self.root), verb="callees", arg="invoke")
        impact = run_query(str(self.root), verb="impact", arg="src/target.py")
        self.assertTrue(any(item["relation_id"] in canonical_edges for item in callers["results"]))
        self.assertTrue(any(item["relation_id"] in canonical_edges for item in callees["results"]))
        self.assertTrue(
            any(item["relation_id"] in canonical_edges for item in impact["results"]["relation_evidence"])
        )

    def test_context_pack_toon_and_fast_projection_preserve_relation_identity(self) -> None:
        artifacts = self._build_serialized_artifacts()
        snapshot = build_context_snapshot(
            str(self.root),
            project_map=artifacts["project-map"],
            symbol_index=artifacts["symbol-index"],
            call_graph=artifacts["call-graph"],
            architecture_inventory=artifacts["architecture-inventory"],
        )
        graph = snapshot["graph"]
        call_edges = [edge for edge in graph["edges"] if edge["kind"] in {"calls", "imports"}]
        self.assertTrue(call_edges)
        self.assertTrue(all(edge.get("relation_id") for edge in call_edges))
        self.assertTrue(all(edge.get("evidence_class") in CALL_GRAPH_RELATION_EVIDENCE for edge in call_edges))
        self.assertEqual(decode_toon(encode_toon(graph)), graph)

        pack = build_context_pack(
            str(self.root),
            [{"path": "src/target.py"}],
            project_map=artifacts["project-map"],
            symbol_index=artifacts["symbol-index"],
            call_graph=artifacts["call-graph"],
            architecture_inventory=artifacts["architecture-inventory"],
        )
        target = pack["files"][0]
        self.assertTrue(target["relation_evidence"])
        self.assertEqual(target["test_evidence"][0]["evidence_class"], "inferred_by_name")

        public = build_public_contract(
            graph,
            repository_id=str(snapshot["repository_id"]),
            generation=str(snapshot["snapshot_id"]),
        )
        public_relations = {
            relation["relation_id"]: relation
            for relation in public["relations"]
            if relation.get("relation_id")
        }
        self.assertTrue(public_relations)
        self.assertTrue(all(relation.get("evidence_class") for relation in public_relations.values()))


class Mapper615WorktreeProvenanceTest(unittest.TestCase):
    def test_clean_dirty_and_untracked_runs_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, ".gitignore", ".simplicio-loop/\n")
            _write(root, "src/target.py", "def target():\n    return 1\n")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "mapper@example.invalid"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Mapper Test"], cwd=root, check=True)
            subprocess.run(["git", "add", ".gitignore", "src/target.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

            write_mapping_artifacts(str(root), output_dir=".simplicio-loop")
            clean = json.loads((root / ".simplicio-loop/call-graph.json").read_text(encoding="utf-8"))
            self.assertFalse(clean["producer"]["source_generation"]["dirty"])

            (root / "src/target.py").write_text("def target():\n    return 2\n", encoding="utf-8")
            write_mapping_artifacts(str(root), output_dir=".simplicio-loop")
            dirty = json.loads((root / ".simplicio-loop/call-graph.json").read_text(encoding="utf-8"))
            self.assertTrue(dirty["producer"]["source_generation"]["dirty"])

            _write(root, "src/untracked.py", "value = 3\n")
            write_mapping_artifacts(str(root), output_dir=".simplicio-loop")
            untracked = json.loads((root / ".simplicio-loop/call-graph.json").read_text(encoding="utf-8"))
            self.assertTrue(untracked["producer"]["source_generation"]["dirty"])


if __name__ == "__main__":
    unittest.main()
