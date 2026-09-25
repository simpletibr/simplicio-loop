"""Unit tests for simplicio_mapper.diagrams (F4 mermaid renderer).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.diagrams import (  # noqa: E402
    escape_label,
    render_call_sequence,
    render_call_sequence_svg,
    render_flowchart,
    render_flowchart_svg,
    render_state_diagram,
    render_state_diagram_svg,
    sanitize_id,
    to_image_markdown,
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


class ToImageMarkdownTest(unittest.TestCase):
    def test_renders_markdown_image_syntax(self) -> None:
        self.assertEqual(
            to_image_markdown("diagrams/architecture-modules.svg", "Module diagram"),
            "![Module diagram](diagrams/architecture-modules.svg)",
        )


class RenderFlowchartSvgTest(unittest.TestCase):
    def _nodes_edges(self, count: int) -> tuple[list[dict], list[dict]]:
        nodes = [{"id": f"n{i}", "label": f"Node {i}"} for i in range(count)]
        edges = [{"source": f"n{i}", "target": f"n{i + 1}"} for i in range(count - 1)]
        return nodes, edges

    def test_output_is_well_formed_xml(self) -> None:
        nodes, edges = self._nodes_edges(5)
        result = render_flowchart_svg(nodes, edges, direction="TB")
        ET.fromstring(result["svg"])  # raises on malformed XML
        self.assertTrue(result["svg"].startswith("<svg"))

    def test_deterministic_output_for_same_input(self) -> None:
        nodes, edges = self._nodes_edges(6)
        first = render_flowchart_svg(nodes, edges)
        second = render_flowchart_svg(nodes, edges)
        self.assertEqual(first["svg"], second["svg"])

    def test_truncation_is_annotated_not_silent(self) -> None:
        nodes, edges = self._nodes_edges(10)
        result = render_flowchart_svg(nodes, edges, max_nodes=3, max_edges=3)
        self.assertEqual(result["truncated_nodes"], 7)
        self.assertIn("truncated", result["svg"])
        self.assertEqual(len(result["fallback"]), 10)

    def test_adversarial_labels_stay_well_formed_xml(self) -> None:
        nodes = [
            {"id": 'a"b].py', "label": "<script>alert(1)</script>"},
            {"id": "c&d", "label": "c&d\"'<>"},
        ]
        edges = [{"source": 'a"b].py', "target": "c&d"}]
        result = render_flowchart_svg(nodes, edges)
        root = ET.fromstring(result["svg"])
        self.assertIsNotNone(root)
        self.assertNotIn("<script>", result["svg"])

    def test_empty_graph_still_renders_valid_svg(self) -> None:
        result = render_flowchart_svg([], [])
        ET.fromstring(result["svg"])

    def test_stadium_shape_used_for_state_nodes(self) -> None:
        nodes = [{"id": "a", "label": "A"}]
        rect = render_flowchart_svg(nodes, [], node_shape="rect")
        stadium = render_flowchart_svg(nodes, [], node_shape="stadium")
        self.assertNotEqual(rect["svg"], stadium["svg"])

    def _box_positions(self, result: dict, node_ids: list[str]) -> dict[str, tuple[str, str]]:
        boxes = re.findall(r'<rect x="(-?\d+)" y="(-?\d+)" width="180"', result["svg"])
        return dict(zip(node_ids, boxes))

    def test_cycle_with_resolvable_predecessor_does_not_collapse_to_root_level(self) -> None:
        # a->b, b->c, c->b: b is reachable from root a, and c is reachable
        # from b. A Kahn queue that only enqueues once indegree hits 0 gets
        # stuck on the b<->c cycle and never dequeues b, so it never walks
        # b->c -- c silently defaults to level 0, landing on the same row
        # as root `a` even though there's a real a->b->c path into it.
        nodes = [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}, {"id": "c", "label": "c"}]
        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "b"},
        ]
        result = render_flowchart_svg(nodes, edges, direction="TB")
        positions = self._box_positions(result, ["a", "b", "c"])
        self.assertNotEqual(positions["c"][1], positions["a"][1])
        self.assertNotEqual(positions["b"][1], positions["a"][1])

    def test_cycle_plus_external_root_keeps_all_positions_distinct(self) -> None:
        nodes = [{"id": n, "label": n} for n in ("a", "b", "c", "d")]
        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "c", "target": "a"},
            {"source": "d", "target": "a"},
        ]
        result = render_flowchart_svg(nodes, edges, direction="TB")
        positions = self._box_positions(result, ["a", "b", "c", "d"])
        self.assertEqual(len(set(positions.values())), 4)

    def test_large_pure_cycle_keeps_bounded_distinct_positions(self) -> None:
        node_ids = [f"n{i}" for i in range(30)]
        nodes = [{"id": n, "label": n} for n in node_ids]
        edges = [{"source": node_ids[i], "target": node_ids[(i + 1) % 30]} for i in range(30)]
        result = render_flowchart_svg(nodes, edges, direction="TB")
        ET.fromstring(result["svg"])
        positions = self._box_positions(result, node_ids)
        self.assertEqual(len(set(positions.values())), 30)

    def test_plain_chain_still_layers_strictly_in_order(self) -> None:
        node_ids = [f"n{i}" for i in range(5)]
        nodes = [{"id": n, "label": n} for n in node_ids]
        edges = [{"source": node_ids[i], "target": node_ids[i + 1]} for i in range(4)]
        result = render_flowchart_svg(nodes, edges, direction="TB")
        positions = self._box_positions(result, node_ids)
        ys = [int(positions[n][1]) for n in node_ids]
        self.assertEqual(ys, sorted(ys))
        self.assertEqual(len(set(ys)), 5)


class RenderCallSequenceSvgTest(unittest.TestCase):
    def test_output_is_well_formed_xml(self) -> None:
        chain = [
            {"actor": "cli.main", "label": "start"},
            {"actor": "mapper.build", "label": "build"},
            {"actor": "writer.persist", "label": "persist"},
        ]
        result = render_call_sequence_svg(chain)
        ET.fromstring(result["svg"])
        self.assertTrue(result["svg"].startswith("<svg"))

    def test_truncation_reports_omitted_steps(self) -> None:
        chain = [{"actor": f"step{i}", "label": f"call {i}"} for i in range(30)]
        result = render_call_sequence_svg(chain, max_steps=5)
        self.assertEqual(result["truncated_steps"], 25)
        self.assertIn("omitted", result["svg"])

    def test_empty_chain_still_renders_valid_svg(self) -> None:
        result = render_call_sequence_svg([])
        ET.fromstring(result["svg"])


class RenderStateDiagramSvgTest(unittest.TestCase):
    def test_output_is_well_formed_xml(self) -> None:
        result = render_state_diagram_svg(
            ["pending", "done", "cancelled"],
            [{"from": "pending", "to": "done", "label": "complete"}, {"from": "pending", "to": "cancelled"}],
        )
        ET.fromstring(result["svg"])
        self.assertTrue(result["svg"].startswith("<svg"))

    def test_truncation_reports_omitted_states(self) -> None:
        states = [f"s{i}" for i in range(25)]
        result = render_state_diagram_svg(states, [], max_states=5)
        self.assertEqual(result["truncated_states"], 20)


if __name__ == "__main__":
    unittest.main()
