from __future__ import annotations

import unittest

from simplicio_mapper.hybrid_retrieval import HybridRetriever
from simplicio_mapper.structural_parser import build_structural_graph


class HybridRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        graph, _ = build_structural_graph(
            [("search.py", "def search_user():\n    return True\n"), ("billing.py", "def bill_user():\n    return search_user()\n")],
            repo_identity="repo",
            generation_id="generation-1",
        )
        cls.graph = graph
        cls.retriever = HybridRetriever(graph)
        functions = graph.find(kind=graph.nodes[1].kind)
        cls.documents = {node.node_id: f"{node.qualified_name} {node.path} user search billing" for node in functions}

    def test_lexical_graph_fallback_works_without_vectors(self) -> None:
        response = self.retriever.retrieve("search user", self.documents, token_budget=100)
        self.assertFalse(response.vector_available)
        self.assertTrue(response.candidates)
        self.assertLessEqual(response.estimated_tokens, 100)

    def test_vector_signal_is_reported_when_available(self) -> None:
        node_id = next(iter(self.documents))
        response = self.retriever.retrieve("anything", self.documents, vector_scores={node_id: 1.0}, token_budget=100)
        self.assertTrue(response.vector_available)
        self.assertIn("vector", response.candidates[0].reason_codes)

    def test_budget_and_near_duplicate_suppression_are_hard_limits(self) -> None:
        duplicates = {key: "same repeated semantic text" for key in list(self.documents) * 2}
        response = self.retriever.retrieve("same", duplicates, token_budget=2, limit=20)
        self.assertLessEqual(response.estimated_tokens, 2)
        self.assertTrue(response.truncated)


if __name__ == "__main__":
    unittest.main()
