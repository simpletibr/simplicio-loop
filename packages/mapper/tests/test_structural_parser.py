from __future__ import annotations

import unittest

from simplicio_mapper.structural_graph import EdgeKind, NodeKind
from simplicio_mapper.structural_parser import build_structural_graph, parse_source


class StructuralParserTests(unittest.TestCase):
    def test_python_ast_emits_definitions_imports_and_exact_calls(self) -> None:
        result = parse_source(
            "pkg/app.py",
            "import os\n\ndef helper():\n    return 1\n\ndef main():\n    return helper()\n",
            "repo",
            "generation-1",
        )
        self.assertEqual(result.coverage.parser, "python-ast")
        self.assertTrue(result.coverage.complete)
        self.assertEqual(len([node for node in result.nodes if node.kind == NodeKind.FUNCTION]), 2)
        self.assertTrue(any(edge.kind == EdgeKind.CALLS for edge in result.edges))
        self.assertTrue(any(edge.kind == EdgeKind.IMPORTS for edge in result.edges))

    def test_python_syntax_error_fails_closed(self) -> None:
        result = parse_source("broken.py", "def broken(:\n", "repo", "generation-1")
        self.assertEqual(result.nodes, ())
        self.assertTrue(result.coverage.syntax_errors)
        self.assertFalse(result.coverage.complete)

    def test_non_python_uses_explicit_conservative_fallback(self) -> None:
        result = parse_source("lib.rs", "pub fn run() {}\n", "repo", "generation-1")
        self.assertEqual(result.coverage.parser, "conservative-regex-fallback")
        self.assertLess(result.coverage.confidence, 1.0)
        self.assertTrue(any(node.qualified_name.endswith(":run") for node in result.nodes))
        self.assertTrue(any(edge.resolution_kind == "exact-lexical" for edge in result.edges))

    def test_build_sorts_inputs_and_preserves_one_generation(self) -> None:
        graph, coverage = build_structural_graph(
            [("b.py", "def b():\n    pass\n"), ("a.py", "def a():\n    pass\n")],
            repo_identity="repo",
            generation_id="generation-2",
        )
        self.assertEqual([item.path for item in coverage], ["a.py", "b.py"])
        self.assertTrue(all(node.generation_id == "generation-2" for node in graph.nodes))
        self.assertEqual(len(graph.find(kind=NodeKind.FUNCTION)), 2)


if __name__ == "__main__":
    unittest.main()
