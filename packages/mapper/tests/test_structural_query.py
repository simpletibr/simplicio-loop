from __future__ import annotations

import unittest

from simplicio_mapper.structural_graph import EdgeKind, NodeKind
from simplicio_mapper.structural_parser import build_structural_graph
from simplicio_mapper.structural_query import StructuralQueryEngine


class StructuralQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {
            "a.py": "def helper():\n    return 1\n\ndef main():\n    return helper()\n",
            "b.py": "from a import main\n\ndef unused():\n    pass\n",
        }
        cls.graph, cls.coverage = build_structural_graph(cls.sources.items(), repo_identity="repo", generation_id="generation-1")
        cls.engine = StructuralQueryEngine(cls.graph, cls.coverage)

    def test_search_and_dsl_are_read_only_and_bounded(self) -> None:
        response = self.engine.search_graph(kind=NodeKind.FUNCTION, limit=1)
        self.assertTrue(response.truncated)
        dsl = self.engine.execute("MATCH (n:function) RETURN n LIMIT 2")
        self.assertEqual(len(dsl.results), 2)
        with self.assertRaises(ValueError):
            self.engine.execute("MATCH (n) DELETE n")

    def test_trace_is_cycle_safe(self) -> None:
        main = self.graph.find(name="main")[0]
        response = self.engine.trace_path(main.node_id, edge_kind=EdgeKind.CALLS, depth=4)
        self.assertTrue(response.explain["cycle_safe"])
        self.assertLessEqual(len(response.results), 20)

    def test_architecture_and_impact_expose_coverage(self) -> None:
        architecture = self.engine.architecture()
        self.assertEqual(architecture.coverage["files"], 2)
        impact = self.engine.impact(changed_paths=["a.py"])
        self.assertTrue(impact.coverage["negative_claims_allowed"])

    def test_dead_code_is_a_candidate_not_a_proven_negative_claim(self) -> None:
        response = self.engine.dead_code()
        self.assertFalse(response.explain["negative_claims"])
        self.assertTrue(any(row["name"].endswith("unused") for row in response.results))

    def test_snippet_requires_the_pinned_content_hash(self) -> None:
        function = self.graph.find(name="helper")[0]
        response = self.engine.code_snippet(function.node_id, self.sources)
        self.assertEqual(response.results[0]["path"], "a.py")
        bad = dict(self.sources)
        bad["a.py"] += "# changed\n"
        self.assertEqual(self.engine.code_snippet(function.node_id, bad).results, ())


if __name__ == "__main__":
    unittest.main()
