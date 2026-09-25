from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.evidence_graph import ArchitecturalDecision, EvidenceStore, RuntimeEvidence, evidence_id
from simplicio_mapper.structural_graph import EdgeKind, GraphEdge
from simplicio_mapper.structural_parser import build_structural_graph


class EvidenceGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.graph, _ = build_structural_graph({"app.py": "def main():\n    pass\n"}.items(), repo_identity="repo", generation_id="g1")
        self.module = self.graph.find(name="app.py")[0]
        self.main = self.graph.find(name="main")[0]
        self.graph.add_edge(GraphEdge(self.module.node_id, self.main.node_id, EdgeKind.DEFINES))

    def test_adr_and_runtime_trace_are_transactional_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(str(Path(directory) / "graph.sqlite3"))
            store.put_adr(ArchitecturalDecision("adr-1", "Keep graph canonical", "accepted", "2026-08-23", "context", "decision", "consequences", (self.main.node_id,), "ADR.md", "hash", "g1"), graph=self.graph)
            trace = RuntimeEvidence(evidence_id("runtime-1", self.module.node_id, self.main.node_id, EdgeKind.DEFINES, "digest"), "g1", "runtime-1", "http", self.module.node_id, self.main.node_id, EdgeKind.DEFINES, "2026-08-23T00:00:00Z", "2026-08-23T01:00:00Z", 2, "digest", {"request_body": "secret", "region": "br"})
            store.ingest_trace(trace, graph=self.graph)
            store.ingest_trace(trace, graph=self.graph)
            self.assertEqual(len(store.list_adrs("g1")), 1)
            observations = store.list_runtime_evidence("g1")
            self.assertEqual(len(observations), 1)
            self.assertNotIn("request_body", observations[0].attributes)

    def test_stale_generation_and_unknown_nodes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(str(Path(directory) / "graph.sqlite3"))
            adr = ArchitecturalDecision("adr-2", "stale", "accepted", "2026-08-23", "", "", "", (self.main.node_id,), "ADR.md", "hash", "old")
            with self.assertRaises(ValueError):
                store.put_adr(adr, graph=self.graph)
            trace = RuntimeEvidence("evidence", "g1", "runtime", "http", "missing", self.main.node_id, EdgeKind.CALLS, "", "", 1, "d", {})
            with self.assertRaises(ValueError):
                store.ingest_trace(trace, graph=self.graph)

    def test_static_and_observed_provenance_remain_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EvidenceStore(str(Path(directory) / "graph.sqlite3"))
            result = store.reconcile_edge(self.module.node_id, self.main.node_id, EdgeKind.DEFINES, graph=self.graph)
            self.assertEqual(result["provenance"], ["static-inferred"])


if __name__ == "__main__":
    unittest.main()
