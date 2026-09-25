from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.structural_graph import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    NodeKind,
    SqliteGraphStore,
    StructuralGraph,
    graph_from_dict,
)


class StructuralGraphTests(unittest.TestCase):
    def make_graph(self) -> StructuralGraph:
        graph = StructuralGraph("repo@example", "generation-1")
        source = graph.add_node(GraphNode.create("repo@example", NodeKind.FILE, "app.py", path="app.py", generation_id="generation-1"))
        target = graph.add_node(
            GraphNode.create(
                "repo@example", NodeKind.FUNCTION, "app.main", path="app.py", start_line=1, end_line=3, generation_id="generation-1"
            )
        )
        graph.add_edge(GraphEdge(source.node_id, target.node_id, EdgeKind.DEFINES, evidence=("app.py:1",)))
        return graph

    def test_digest_and_order_are_stable(self) -> None:
        first = self.make_graph()
        second = self.make_graph()
        self.assertEqual(first.digest(), second.digest())
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_json_publication_is_round_trippable(self) -> None:
        graph = self.make_graph()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".simplicio" / "graph.json"
            graph.publish_json(path)
            self.assertEqual(graph_from_dict(json.loads(path.read_text())).digest(), graph.digest())

    def test_sqlite_publication_is_transactional_and_generation_bound(self) -> None:
        graph = self.make_graph()
        with tempfile.TemporaryDirectory() as directory:
            store = SqliteGraphStore(Path(directory) / "graph.sqlite3")
            self.assertEqual(store.publish(graph), graph.digest())
            loaded = store.load()
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.digest(), graph.digest())
            file_node = loaded.find(kind=NodeKind.FILE)[0]
            self.assertEqual(len(loaded.neighbors(file_node.node_id, edge_kind=EdgeKind.DEFINES)), 1)

    def test_missing_edge_endpoint_fails_closed(self) -> None:
        graph = StructuralGraph("repo", "generation")
        with self.assertRaises(KeyError):
            graph.add_edge(GraphEdge("missing", "also-missing", EdgeKind.CALLS))


if __name__ == "__main__":
    unittest.main()
