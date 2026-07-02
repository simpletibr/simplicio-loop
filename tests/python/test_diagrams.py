"""Unit tests for simplicio_mapper.diagrams (F4 mermaid renderer).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.diagrams import (  # noqa: E402
    escape_label,
    render_call_sequence,
    render_flowchart,
    render_state_diagram,
    sanitize_id,
    to_markdown_block,
)


class SanitizeIdTest(unittest.TestCase):
    def test_collision_between_different_raw_values_is_resolved(self) -> None:
        seen: dict[str, str] = {}
        first = sanitize_id("a/b.py", seen)
        second = sanitize_id("a_b.py", seen)
        self.assertNotEqual(first, second)

    def test_same_raw_value_is_memoized(self) -> None:
        seen: dict[str, str] = {}
        first = sanitize_id("simplicio_mapper/cli.py", seen)
        second = sanitize_id("simplicio_mapper/cli.py", seen)
        self.assertEqual(first, second)

    def test_id_never_starts_with_digit(self) -> None:
        seen: dict[str, str] = {}
        node_id = sanitize_id("123file.py", seen)
        self.assertFalse(node_id[0].isdigit())


class EscapeLabelTest(unittest.TestCase):
    def test_escapes_adversarial_characters(self) -> None:
        label = escape_label('a"b].py|c{d}\ne')
        for bad in ('"', "[", "]", "|", "{", "}", "\n"):
            self.assertNotIn(bad, label)

    def test_empty_label_has_placeholder(self) -> None:
        self.assertEqual(escape_label(""), "?")


class RenderFlowchartTest(unittest.TestCase):
    def test_deterministic_output_for_same_input(self) -> None:
        nodes = [{"id": "b", "label": "B"}, {"id": "a", "label": "A"}]
        edges = [{"source": "a", "target": "b"}]
        first = render_flowchart(nodes, edges)
        second = render_flowchart(nodes, edges)
        self.assertEqual(first["mermaid"], second["mermaid"])

    def test_truncation_is_annotated_not_silent(self) -> None:
        nodes = [{"id": f"n{i}", "label": f"Node {i}"} for i in range(10)]
        edges = [{"source": f"n{i}", "target": f"n{i + 1}"} for i in range(9)]
        result = render_flowchart(nodes, edges, max_nodes=3, max_edges=3)
        self.assertEqual(result["truncated_nodes"], 7)
        self.assertIn("truncated", result["mermaid"])
        self.assertEqual(len(result["fallback"]), 10)

    def test_duplicate_edges_are_deduped_with_count(self) -> None:
        nodes = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
        edges = [{"source": "a", "target": "b"} for _ in range(3)]
        result = render_flowchart(nodes, edges)
        self.assertIn("3 edges", result["mermaid"])

    def test_self_edges_are_dropped(self) -> None:
        nodes = [{"id": "a", "label": "A"}]
        edges = [{"source": "a", "target": "a"}]
        result = render_flowchart(nodes, edges)
        self.assertEqual(result["edge_count"], 0)

    def test_adversarial_filenames_do_not_break_mermaid(self) -> None:
        nodes = [{"id": 'a"b].py', "label": 'a"b].py'}, {"id": "c[d]{e}", "label": "c[d]{e}"}]
        edges = [{"source": 'a"b].py', "target": "c[d]{e}"}]
        result = render_flowchart(nodes, edges)
        # Each node line must have exactly the two delimiter quotes around the label
        # (`id["label"]`); no stray quote/bracket/brace leaking from the raw input.
        for line in result["mermaid"].splitlines():
            if not line.strip().startswith(('flowchart', '%%')) and "[" in line:
                self.assertEqual(line.count('"'), 2)
                label = line.split('"', 2)[1]
                for bad in ('"', "[", "]", "{", "}"):
                    self.assertNotIn(bad, label)


class RenderCallSequenceTest(unittest.TestCase):
    def test_linear_chain_renders_all_participants(self) -> None:
        chain = [{"actor": "cli.main", "label": "start"}, {"actor": "mapper.build", "label": "build"}]
        result = render_call_sequence(chain)
        self.assertIn("participant", result["mermaid"])
        self.assertIn("->>+", result["mermaid"])

    def test_truncation_reports_omitted_steps(self) -> None:
        chain = [{"actor": f"step{i}", "label": f"call {i}"} for i in range(30)]
        result = render_call_sequence(chain, max_steps=5)
        self.assertEqual(result["truncated_steps"], 25)


class RenderStateDiagramTest(unittest.TestCase):
    def test_transitions_between_kept_states_only(self) -> None:
        result = render_state_diagram(
            ["pending", "done"],
            [{"from": "pending", "to": "done", "label": "complete"}],
        )
        self.assertIn("-->", result["mermaid"])
        self.assertIn("complete", result["mermaid"])


class ToMarkdownBlockTest(unittest.TestCase):
    def test_wraps_mermaid_fence_and_fallback(self) -> None:
        result = render_flowchart([{"id": "a", "label": "A"}], [])
        block = to_markdown_block(result, heading="Example")
        self.assertIn("```mermaid", block)
        self.assertIn("#### Example", block)
        self.assertIn("<details>", block)


if __name__ == "__main__":
    unittest.main()
