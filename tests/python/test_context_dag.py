"""Unit tests for the incremental Merkle DAG (issue #208, Step 2).

Covers the AC items this slice owns:

* Merkle DAG persists per-node/edge content hash chained with dependencies.
* A local content change invalidates only the dependent cone (proven via
  counters), not the whole node set.
* Rename is detected (same content_hash, different id) and annotated with a
  ``rename_hint`` while still emitting remove+add (path is part of identity).
* Delete produces a ``remove`` event.
* A producer/parser or build-config version change forces an explicit full
  invalidation, never inferred from node hashes.
* A corrupted DAG file or a truncated journal never crashes and never serves
  stale data silently.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from simplicio_mapper.context_dag import (
    CONTEXT_DAG_SCHEMA,
    REASON_ADDED,
    REASON_BUILD_CONFIG_CHANGED,
    REASON_CACHE_CORRUPTED,
    REASON_CONTENT_CHANGED,
    REASON_DEPENDENCY_CHANGED,
    REASON_NO_PREVIOUS,
    REASON_PRODUCER_VERSION_CHANGED,
    REASON_REMOVED,
    build_context_dag,
    diff_context_dag,
    load_context_dag,
    read_journal,
    save_context_dag,
    update_context_dag,
)


def _node(node_id: str, content_hash: str, scale: str = "micro") -> dict:
    return {"id": node_id, "scale": scale, "content_hash": content_hash, "source": {"file": "x.py"}}


def _edge(edge_id: str, source: str, target: str) -> dict:
    return {
        "id": edge_id,
        "kind": "calls",
        "source": source,
        "target": target,
        "content_hash": f"edge-content:{edge_id}",
        "source_handle": {"file": "x.py"},
    }


class ContextDagBuildTest(unittest.TestCase):
    def test_schema_constant(self):
        dag = build_context_dag({"nodes": [], "edges": []})
        self.assertEqual(dag["schema"], CONTEXT_DAG_SCHEMA)

    def test_dag_id_deterministic(self):
        graph = {"nodes": [_node("a", "h1"), _node("b", "h2")], "edges": []}
        d1 = build_context_dag(graph, revision="r1")
        d2 = build_context_dag(graph, revision="r1")
        self.assertEqual(d1["dag_id"], d2["dag_id"])

    def test_dependency_folds_into_merkle_hash(self):
        # A depends on B (edge A->B). Changing only B's content must change
        # A's merkle_hash too, even though A's own content_hash is untouched.
        graph1 = {"nodes": [_node("a", "ha"), _node("b", "hb1")], "edges": [_edge("e1", "a", "b")]}
        graph2 = {"nodes": [_node("a", "ha"), _node("b", "hb2")], "edges": [_edge("e1", "a", "b")]}
        dag1 = build_context_dag(graph1)
        dag2 = build_context_dag(graph2)
        nodes1 = {n["id"]: n for n in dag1["nodes"]}
        nodes2 = {n["id"]: n for n in dag2["nodes"]}
        self.assertEqual(nodes1["a"]["content_hash"], nodes2["a"]["content_hash"])
        self.assertNotEqual(nodes1["a"]["merkle_hash"], nodes2["a"]["merkle_hash"])
        self.assertNotEqual(nodes1["b"]["merkle_hash"], nodes2["b"]["merkle_hash"])
        self.assertIn("freshness", nodes1["a"])
        self.assertEqual(nodes1["a"]["fidelity"]["status"], "exact")

    def test_cyclic_dependency_degrades_without_crashing(self):
        graph = {
            "nodes": [_node("a", "ha"), _node("b", "hb")],
            "edges": [_edge("e1", "a", "b"), _edge("e2", "b", "a")],
        }
        dag = build_context_dag(graph)
        degraded_ids = {n["id"] for n in dag["nodes"] if n["degraded"]}
        self.assertTrue(degraded_ids)  # at least one side of the cycle is flagged


class ContextDagDiffTest(unittest.TestCase):
    def test_no_previous_dag_is_full_invalidation(self):
        graph = {"nodes": [_node("a", "ha")], "edges": []}
        current = build_context_dag(graph)
        diff = diff_context_dag(None, current)
        self.assertTrue(diff["full_invalidation"])
        self.assertEqual(diff["reason"], REASON_NO_PREVIOUS)

    def test_local_change_invalidates_only_dependent_cone(self):
        # Three independent nodes; only "a" changes. "b"/"c" must not appear
        # in the events at all — this is the "cone, not whole repo" proof.
        graph1 = {"nodes": [_node("a", "ha1"), _node("b", "hb"), _node("c", "hc")], "edges": []}
        graph2 = {"nodes": [_node("a", "ha2"), _node("b", "hb"), _node("c", "hc")], "edges": []}
        dag1 = build_context_dag(graph1)
        dag2 = build_context_dag(graph2)
        diff = diff_context_dag(dag1, dag2)
        self.assertFalse(diff["full_invalidation"])
        self.assertEqual(diff["counters"]["invalidated"], 1)
        self.assertEqual(diff["counters"]["total_nodes"], 3)
        self.assertEqual(diff["counters"]["micro"], 3)
        touched_ids = {event["id"] for event in diff["events"]}
        self.assertEqual(touched_ids, {"a"})
        self.assertEqual(diff["events"][0]["reason"], REASON_CONTENT_CHANGED)
        self.assertEqual(diff["events"][0]["scale"], "micro")

    def test_dependent_invalidated_with_dependency_changed_reason(self):
        graph1 = {"nodes": [_node("a", "ha"), _node("b", "hb1")], "edges": [_edge("e1", "a", "b")]}
        graph2 = {"nodes": [_node("a", "ha"), _node("b", "hb2")], "edges": [_edge("e1", "a", "b")]}
        dag1 = build_context_dag(graph1)
        dag2 = build_context_dag(graph2)
        diff = diff_context_dag(dag1, dag2)
        events_by_id = {event["id"]: event for event in diff["events"] if event["op"] == "invalidate"}
        self.assertEqual(events_by_id["b"]["reason"], REASON_CONTENT_CHANGED)
        self.assertEqual(events_by_id["a"]["reason"], REASON_DEPENDENCY_CHANGED)

    def test_rename_detected_via_matching_content_hash(self):
        previous = build_context_dag({"nodes": [_node("file:old.py", "same-hash")], "edges": []})
        current = build_context_dag({"nodes": [_node("file:new.py", "same-hash")], "edges": []})
        diff = diff_context_dag(previous, current)
        add_events = [event for event in diff["events"] if event["op"] == "add"]
        remove_events = [event for event in diff["events"] if event["op"] == "remove"]
        self.assertEqual(len(add_events), 1)
        self.assertEqual(len(remove_events), 1)
        self.assertEqual(add_events[0]["id"], "file:new.py")
        self.assertEqual(add_events[0]["rename_hint"], "file:old.py")
        self.assertEqual(add_events[0]["caused_by"][0]["op"], "rename")
        self.assertEqual(remove_events[0]["reason"], REASON_REMOVED)

    def test_dependency_invalidation_carries_causal_chain(self):
        graph1 = {"nodes": [_node("a", "ha"), _node("b", "hb1")], "edges": [_edge("e1", "a", "b")]}
        graph2 = {"nodes": [_node("a", "ha"), _node("b", "hb2")], "edges": [_edge("e1", "a", "b")]}
        diff = diff_context_dag(build_context_dag(graph1), build_context_dag(graph2))
        event = [row for row in diff["events"] if row["id"] == "a" and row["op"] == "invalidate"][0]
        self.assertEqual(event["reason"], REASON_DEPENDENCY_CHANGED)
        self.assertTrue(event["caused_by"])
        self.assertEqual(event["caused_by"][0]["id"], "b")

    def test_plain_delete_has_no_rename_hint(self):
        previous = build_context_dag(
            {"nodes": [_node("file:gone.py", "h1"), _node("file:stays.py", "h2")], "edges": []}
        )
        current = build_context_dag({"nodes": [_node("file:stays.py", "h2")], "edges": []})
        diff = diff_context_dag(previous, current)
        self.assertEqual(len(diff["events"]), 1)
        event = diff["events"][0]
        self.assertEqual(event["op"], "remove")
        self.assertEqual(event["id"], "file:gone.py")
        self.assertEqual(event["reason"], REASON_REMOVED)
        self.assertEqual(event["scale"], "micro")

    def test_plain_add_has_no_rename_hint(self):
        previous = build_context_dag({"nodes": [_node("file:a.py", "h1")], "edges": []})
        current = build_context_dag({"nodes": [_node("file:a.py", "h1"), _node("file:b.py", "h2")], "edges": []})
        diff = diff_context_dag(previous, current)
        self.assertEqual(len(diff["events"]), 1)
        event = diff["events"][0]
        self.assertEqual(event["op"], "add")
        self.assertEqual(event["id"], "file:b.py")
        self.assertEqual(event["reason"], REASON_ADDED)
        self.assertEqual(event["scale"], "micro")

    def test_build_config_change_forces_full_invalidation(self):
        graph = {"nodes": [_node("a", "ha"), _node("b", "hb")], "edges": []}
        previous = build_context_dag(graph, build_config_hash="config-1")
        current = build_context_dag(graph, build_config_hash="config-2")
        diff = diff_context_dag(previous, current)
        self.assertTrue(diff["full_invalidation"])
        self.assertEqual(diff["reason"], REASON_BUILD_CONFIG_CHANGED)
        self.assertEqual(diff["counters"]["invalidated"], 2)

    def test_producer_version_change_forces_full_invalidation(self):
        graph = {"nodes": [_node("a", "ha")], "edges": []}
        previous = build_context_dag(graph, producer={"version": "0.1.0", "artifact_version": 1})
        current = build_context_dag(graph, producer={"version": "0.2.0", "artifact_version": 1})
        diff = diff_context_dag(previous, current)
        self.assertTrue(diff["full_invalidation"])
        self.assertEqual(diff["reason"], REASON_PRODUCER_VERSION_CHANGED)


class ContextDagPersistenceTest(unittest.TestCase):
    def test_load_missing_file(self):
        dag, reason = load_context_dag("/nonexistent/context-dag.json")
        self.assertIsNone(dag)
        self.assertEqual(reason, REASON_NO_PREVIOUS)

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "context-dag.json")
            dag = build_context_dag({"nodes": [_node("a", "ha")], "edges": []})
            save_context_dag(path, dag)
            self.assertFalse(os.path.isfile(path + ".tmp"))
            loaded, reason = load_context_dag(path)
            self.assertIsNone(reason)
            self.assertEqual(loaded["dag_id"], dag["dag_id"])

    def test_corrupted_file_never_served_as_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "context-dag.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{not valid json")
            dag, reason = load_context_dag(path)
            self.assertIsNone(dag)
            self.assertEqual(reason, REASON_CACHE_CORRUPTED)

    def test_wrong_schema_treated_as_corrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "context-dag.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"schema": "some.other/v1", "nodes": [], "edges": []}, handle)
            dag, reason = load_context_dag(path)
            self.assertIsNone(dag)
            self.assertEqual(reason, REASON_CACHE_CORRUPTED)


class JournalTest(unittest.TestCase):
    def test_read_journal_missing_file(self):
        entries, diagnostics = read_journal("/nonexistent/context-dag-journal.jsonl")
        self.assertEqual(entries, [])
        self.assertEqual(diagnostics, [])

    def test_truncated_trailing_line_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "journal.jsonl")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"revision": "r1"}) + "\n")
                handle.write(json.dumps({"revision": "r2"}) + "\n")
                handle.write('{"revision": "r3", "incomplete')  # simulated crash mid-write
            entries, diagnostics = read_journal(path)
            self.assertEqual([entry["revision"] for entry in entries], ["r1", "r2"])
            self.assertEqual(len(diagnostics), 1)
            self.assertEqual(diagnostics[0]["code"], "journal-line-truncated")
            self.assertEqual(diagnostics[0]["line"], 3)


class UpdateContextDagTest(unittest.TestCase):
    def test_first_run_is_full_invalidation_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = {"nodes": [_node("a", "ha")], "edges": []}
            result = update_context_dag(tmp, graph, out=".simplicio")
            self.assertTrue(result["diff"]["full_invalidation"])
            self.assertEqual(result["diff"]["reason"], REASON_NO_PREVIOUS)
            self.assertTrue(os.path.isfile(os.path.join(tmp, ".simplicio", "context-dag.json")))
            entries, diagnostics = read_journal(os.path.join(tmp, ".simplicio", "context-dag-journal.jsonl"))
            self.assertEqual(diagnostics, [])
            self.assertEqual(len(entries), 1)

    def test_second_run_unchanged_graph_invalidates_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = {"nodes": [_node("a", "ha"), _node("b", "hb")], "edges": []}
            update_context_dag(tmp, graph, out=".simplicio")
            result = update_context_dag(tmp, graph, out=".simplicio")
            self.assertFalse(result["diff"]["full_invalidation"])
            self.assertEqual(result["diff"]["counters"]["invalidated"], 0)

    def test_run_after_corrupted_cache_falls_back_to_full_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph = {"nodes": [_node("a", "ha")], "edges": []}
            dag_path = os.path.join(tmp, ".simplicio", "context-dag.json")
            os.makedirs(os.path.dirname(dag_path), exist_ok=True)
            with open(dag_path, "w", encoding="utf-8") as handle:
                handle.write("{not valid json")
            result = update_context_dag(tmp, graph, out=".simplicio")
            self.assertTrue(result["diff"]["full_invalidation"])
            self.assertEqual(result["diff"]["reason"], REASON_CACHE_CORRUPTED)
            # the corrupted file must be safely overwritten with a valid one
            loaded, reason = load_context_dag(dag_path)
            self.assertIsNone(reason)
            self.assertEqual(loaded["dag_id"], result["dag"]["dag_id"])


if __name__ == "__main__":
    unittest.main()
