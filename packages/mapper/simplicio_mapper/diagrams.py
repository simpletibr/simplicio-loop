"""Deterministic Mermaid + SVG diagram rendering shared by mapper doc renderers.

Implements the guardrails required by the Flow Documentation Engine spec
(``.specs/product/flow-documentation-spec.md`` F4): stable ordering (same
input tree -> same diagram, byte for byte), sanitized/collision-free node
ids, escaped labels, a hard cap on nodes/edges with an explicit truncation
note (never a silent cut), and a textual fallback list next to every
diagram so the same information survives when Mermaid is not rendered.

Every diagram type also has an SVG sibling (``render_*_svg``) that consumes
the same raw ``nodes``/``edges``/``chain``/``states`` inputs and applies the
same ordering/truncation rules, so a Mermaid block and its companion
standalone ``.svg`` artifact always agree. SVG rendering is pure-Python
(string templating, no layout library dependency) — a lightweight layered
layout, not a graphviz-quality one.

See ``SIMPLICIO_INTEGRATION.md`` "Diagram Contract" for the consumer-facing
description of these guarantees.
"""

from __future__ import annotations

import re

DEFAULT_MAX_NODES = 30
DEFAULT_MAX_EDGES = 60
DEFAULT_MAX_SEQUENCE_STEPS = 25
DEFAULT_MAX_STATES = 20

_ID_INVALID = re.compile(r"[^A-Za-z0-9_]+")


def sanitize_id(raw: str, seen: dict[str, str]) -> str:
    """Return a stable, collision-free Mermaid node id for ``raw``.

    ``seen`` is a caller-owned memo (``raw`` -> ``id``) so repeated calls for
    the same raw value always return the same id within one diagram, even
    when two different raw values would otherwise sanitize to the same
    string (e.g. ``a/b.py`` and ``a_b.py``).
    """
    if raw in seen:
        return seen[raw]
    base = _ID_INVALID.sub("_", raw).strip("_") or "n"
    if base[0].isdigit():
        base = f"n_{base}"
    used = set(seen.values())
    candidate = base
    suffix = 0
    while candidate in used:
        suffix += 1
        candidate = f"{base}_{suffix}"
    seen[raw] = candidate
    return candidate


def escape_label(text: str) -> str:
    """Escape a label for safe embedding inside a Mermaid node/edge."""
    value = (text or "").replace("\\", "/")
    value = value.replace('"', "'").replace("\n", " ").replace("\r", " ")
    value = value.replace("|", "/").replace("[", "(").replace("]", ")")
    value = value.replace("{", "(").replace("}", ")")
    value = re.sub(r"\s+", " ", value).strip()
    return value or "?"


def _prepare_flowchart_elements(
    nodes: list[dict],
    edges: list[dict],
    max_nodes: int,
    max_edges: int,
) -> tuple[list[dict], list[dict], int, list[tuple[tuple[str, str, str], int]], list[tuple[tuple[str, str, str], int]], int]:
    """Shared node/edge selection for the Mermaid and SVG flowchart renderers.

    Returns ``(ordered_nodes, kept_nodes, omitted_nodes, ordered_edges,
    kept_edges, omitted_edges)`` — ``ordered_edges`` is the deduped,
    fully-sorted edge list (pre-truncation, used for the ``edge_count``);
    ``kept_edges`` is the same list capped at ``max_edges``. Self-edges are
    dropped and parallel edges collapse into one with a count.
    """
    by_id: dict[str, dict] = {}
    for node in nodes:
        by_id[node["id"]] = node
    ordered_nodes = sorted(by_id.values(), key=lambda n: (n.get("label") or n["id"], n["id"]))
    kept_nodes = ordered_nodes[:max_nodes]
    omitted_nodes = len(ordered_nodes) - len(kept_nodes)
    kept_ids = {n["id"] for n in kept_nodes}

    edge_counts: dict[tuple[str, str, str], int] = {}
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source not in kept_ids or target not in kept_ids or source == target:
            continue
        key = (source, target, edge.get("label") or "")
        edge_counts[key] = edge_counts.get(key, 0) + 1
    ordered_edges = sorted(edge_counts.items(), key=lambda kv: kv[0])
    kept_edges = ordered_edges[:max_edges]
    omitted_edges = len(ordered_edges) - len(kept_edges)
    return ordered_nodes, kept_nodes, omitted_nodes, ordered_edges, kept_edges, omitted_edges


def _xml_escape(text: str) -> str:
    """Escape a label for safe embedding inside an SVG text/attribute node."""
    value = text or ""
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return value.replace('"', "&quot;").replace("'", "&apos;")


def _truncate_label(text: str, limit: int) -> str:
    """Shorten ``text`` to ``limit`` characters for a fixed-width SVG box."""
    value = text or ""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def to_image_markdown(rel_svg_path: str, alt_text: str) -> str:
    """Return a Markdown image reference to a companion standalone SVG file."""
    return f"![{alt_text}]({rel_svg_path})"


def render_flowchart(
    nodes: list[dict],
    edges: list[dict],
    direction: str = "TB",
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> dict:
    """Render a deterministic ``flowchart`` diagram.

    ``nodes``: ``[{"id": raw_id, "label": str}, ...]``
    ``edges``: ``[{"source": raw_id, "target": raw_id, "label": optional str}, ...]``

    Returns a dict with the rendered ``mermaid`` body (no code fence),
    truncation counters and a ``fallback`` textual list of every node.
    """
    ordered_nodes, kept_nodes, omitted_nodes, ordered_edges, kept_edges, omitted_edges = (
        _prepare_flowchart_elements(nodes, edges, max_nodes, max_edges)
    )

    seen: dict[str, str] = {}
    lines = [f"flowchart {direction}"]
    for node in kept_nodes:
        node_id = sanitize_id(node["id"], seen)
        lines.append(f'  {node_id}["{escape_label(node.get("label") or node["id"])}"]')
    for (source, target, label), count in kept_edges:
        source_id = sanitize_id(source, seen)
        target_id = sanitize_id(target, seen)
        if count > 1:
            edge_label = f"|{count} edges|"
        elif label:
            edge_label = f"|{escape_label(label)}|"
        else:
            edge_label = ""
        lines.append(f"  {source_id} -->{edge_label} {target_id}")
    if omitted_nodes or omitted_edges:
        lines.append(
            f"  %% truncated: {omitted_nodes} node(s) and {omitted_edges} edge(s) "
            "omitted above max_nodes/max_edges — see the full list below"
        )

    fallback = [f"- {node.get('label') or node['id']} (`{node['id']}`)" for node in ordered_nodes]
    return {
        "mermaid": "\n".join(lines),
        "node_count": len(ordered_nodes),
        "edge_count": len(ordered_edges),
        "truncated_nodes": omitted_nodes,
        "truncated_edges": omitted_edges,
        "fallback": fallback,
    }


_SVG_BOX_W = 180
_SVG_BOX_H = 44
_SVG_GAP_MAIN = 70
_SVG_GAP_CROSS = 30
_SVG_MARGIN = 24


def render_flowchart_svg(
    nodes: list[dict],
    edges: list[dict],
    direction: str = "TB",
    max_nodes: int = DEFAULT_MAX_NODES,
    max_edges: int = DEFAULT_MAX_EDGES,
    node_shape: str = "rect",
) -> dict:
    """Render a deterministic standalone SVG flowchart.

    Same input shape, ordering and truncation rules as :func:`render_flowchart`
    (built on the same :func:`_prepare_flowchart_elements`). Layout is a
    lightweight layered grid (topological level -> row/column via a
    Kahn-style pass; cyclic leftovers fall back to level 0), not a
    graphviz-quality layout. ``node_shape`` is ``"rect"`` or ``"stadium"``
    (rounded pill, used by :func:`render_state_diagram_svg`).
    """
    ordered_nodes, kept_nodes, omitted_nodes, ordered_edges, kept_edges, omitted_edges = (
        _prepare_flowchart_elements(nodes, edges, max_nodes, max_edges)
    )

    # Longest-path level assignment via bounded relaxation (Bellman-Ford
    # style): a plain Kahn queue only propagates past a node once its
    # indegree fully drains, so a node that is part of a cycle but also has
    # a resolvable predecessor gets stuck — it's never dequeued, so its own
    # outgoing edges (and everything downstream of them) silently keep the
    # default level 0 instead of following the resolvable edge into them.
    # Relaxing every kept edge, up to once per node, fixes that: real DAG
    # edges converge to their correct longest-path level within the first
    # few passes, and edges that are part of a cycle just keep incrementing
    # until the pass budget runs out — still deterministic (fixed edge
    # order, fixed pass count), and bounded so it terminates on any input.
    level = {node["id"]: 0 for node in kept_nodes}
    edge_pairs = [(source, target) for (source, target, _label), _count in kept_edges]
    for _pass in range(len(kept_nodes)):
        changed = False
        for source, target in edge_pairs:
            if level[target] < level[source] + 1:
                level[target] = level[source] + 1
                changed = True
        if not changed:
            break
    # Compress to consecutive ranks so a cycle's unbounded level growth
    # doesn't blow up the canvas — only the relative order matters for layout.
    distinct_levels = sorted(set(level.values()))
    rank = {raw: index for index, raw in enumerate(distinct_levels)}
    level = {node_id: rank[raw] for node_id, raw in level.items()}

    by_level: dict[int, list[dict]] = {}
    for node in kept_nodes:  # kept_nodes is already sorted -> stable lane order
        by_level.setdefault(level[node["id"]], []).append(node)
    max_level = max(by_level) if by_level else 0
    max_lane = max((len(items) for items in by_level.values()), default=0)

    positions: dict[str, tuple[float, float]] = {}
    for lvl, items in by_level.items():
        for lane_index, node in enumerate(items):
            if direction == "LR":
                x = _SVG_MARGIN + lvl * (_SVG_BOX_W + _SVG_GAP_MAIN)
                y = _SVG_MARGIN + lane_index * (_SVG_BOX_H + _SVG_GAP_CROSS)
            else:
                x = _SVG_MARGIN + lane_index * (_SVG_BOX_W + _SVG_GAP_CROSS)
                y = _SVG_MARGIN + lvl * (_SVG_BOX_H + _SVG_GAP_MAIN)
            positions[node["id"]] = (x, y)

    if direction == "LR":
        width = _SVG_MARGIN * 2 + (max_level + 1) * (_SVG_BOX_W + _SVG_GAP_MAIN) - _SVG_GAP_MAIN
        height = (
            _SVG_MARGIN * 2 + max_lane * (_SVG_BOX_H + _SVG_GAP_CROSS) - _SVG_GAP_CROSS
            if max_lane
            else _SVG_BOX_H + _SVG_MARGIN * 2
        )
    else:
        width = (
            _SVG_MARGIN * 2 + max_lane * (_SVG_BOX_W + _SVG_GAP_CROSS) - _SVG_GAP_CROSS
            if max_lane
            else _SVG_BOX_W + _SVG_MARGIN * 2
        )
        height = _SVG_MARGIN * 2 + (max_level + 1) * (_SVG_BOX_H + _SVG_GAP_MAIN) - _SVG_GAP_MAIN
    width = max(width, _SVG_BOX_W + _SVG_MARGIN * 2)
    height = max(height, _SVG_BOX_H + _SVG_MARGIN * 2)
    if omitted_nodes or omitted_edges:
        height += 20

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="monospace">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>',
        '<defs><marker id="sm-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#475569"/></marker></defs>',
    ]
    for (source, target, edge_label), count in kept_edges:
        sx, sy = positions[source]
        tx, ty = positions[target]
        x1, y1 = sx + _SVG_BOX_W / 2, sy + _SVG_BOX_H / 2
        x2, y2 = tx + _SVG_BOX_W / 2, ty + _SVG_BOX_H / 2
        parts.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            'stroke="#94a3b8" stroke-width="1.5" marker-end="url(#sm-arrow)"/>'
        )
        label = f"{count} edges" if count > 1 else (edge_label or "")
        if label:
            text = _xml_escape(_truncate_label(label, 20))
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            box_w = max(len(text) * 6, 12)
            parts.append(
                f'<rect x="{mx - box_w / 2:.0f}" y="{my - 8:.0f}" width="{box_w:.0f}" '
                'height="14" fill="#ffffff" opacity="0.85"/>'
            )
            parts.append(
                f'<text x="{mx:.0f}" y="{my + 3:.0f}" text-anchor="middle" font-size="10" '
                f'fill="#475569">{text}</text>'
            )
    rx = _SVG_BOX_H / 2 if node_shape == "stadium" else 8
    for node in kept_nodes:
        x, y = positions[node["id"]]
        label = _xml_escape(_truncate_label(node.get("label") or node["id"], 24))
        parts.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{_SVG_BOX_W}" height="{_SVG_BOX_H}" '
            f'rx="{rx:.0f}" ry="{rx:.0f}" fill="#eef2ff" stroke="#334155" stroke-width="1.5"/>'
        )
        parts.append(
            f'<text x="{x + _SVG_BOX_W / 2:.0f}" y="{y + _SVG_BOX_H / 2 + 4:.0f}" '
            f'text-anchor="middle" font-size="12" fill="#0f172a">{label}</text>'
        )
    if omitted_nodes or omitted_edges:
        parts.append(
            f'<text x="{_SVG_MARGIN}" y="{height - 8:.0f}" font-size="10" fill="#b91c1c">'
            f"truncated: {omitted_nodes} node(s) and {omitted_edges} edge(s) omitted "
            "— see the fallback list</text>"
        )
    parts.append("</svg>")

    fallback = [f"- {node.get('label') or node['id']} (`{node['id']}`)" for node in ordered_nodes]
    return {
        "svg": "\n".join(parts),
        "node_count": len(ordered_nodes),
        "edge_count": len(ordered_edges),
        "truncated_nodes": omitted_nodes,
        "truncated_edges": omitted_edges,
        "fallback": fallback,
    }


def render_call_sequence(chain: list[dict], max_steps: int = DEFAULT_MAX_SEQUENCE_STEPS) -> dict:
    """Render a linear ``sequenceDiagram`` from an ordered call chain.

    ``chain``: ``[{"actor": raw_id, "label": str}, ...]`` in call order,
    starting with the entry point.
    """
    ordered = chain[:max_steps]
    omitted = len(chain) - len(ordered)
    seen: dict[str, str] = {}
    lines = ["sequenceDiagram"]
    participants: list[str] = []
    for step in ordered:
        participant_id = sanitize_id(step["actor"], seen)
        if participant_id not in participants:
            participants.append(participant_id)
            lines.append(f"  participant {participant_id} as {escape_label(step['actor'])}")
    for index in range(len(ordered) - 1):
        source_id = sanitize_id(ordered[index]["actor"], seen)
        target_id = sanitize_id(ordered[index + 1]["actor"], seen)
        message = escape_label(ordered[index + 1].get("label") or "calls")
        lines.append(f"  {source_id}->>+{target_id}: {message}")
    if omitted and participants:
        lines.append(f"  Note right of {participants[-1]}: {omitted} more step(s) omitted")
    fallback = [f"{index + 1}. {step.get('label') or step['actor']}" for index, step in enumerate(chain)]
    return {"mermaid": "\n".join(lines), "truncated_steps": omitted, "fallback": fallback}


_SVG_SEQ_LANE_W = 200
_SVG_SEQ_MARGIN = 20
_SVG_SEQ_HEADER_H = 50
_SVG_SEQ_STEP_GAP = 50


def render_call_sequence_svg(chain: list[dict], max_steps: int = DEFAULT_MAX_SEQUENCE_STEPS) -> dict:
    """Render a deterministic standalone SVG sequence diagram.

    Same truncation/ordering semantics as :func:`render_call_sequence`:
    participant lanes in first-appearance order, one arrow per call step.
    """
    ordered = chain[:max_steps]
    omitted = len(chain) - len(ordered)
    participants: list[str] = []
    for step in ordered:
        if step["actor"] not in participants:
            participants.append(step["actor"])

    width = _SVG_SEQ_MARGIN * 2 + max(len(participants), 1) * _SVG_SEQ_LANE_W
    height = (
        _SVG_SEQ_HEADER_H
        + max(len(ordered) - 1, 0) * _SVG_SEQ_STEP_GAP
        + _SVG_SEQ_MARGIN * 2
        + (20 if omitted else 0)
    )
    lane_x = {actor: _SVG_SEQ_MARGIN + index * _SVG_SEQ_LANE_W + _SVG_SEQ_LANE_W / 2 for index, actor in enumerate(participants)}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" font-family="monospace">',
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>',
        '<defs><marker id="sq-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#475569"/></marker></defs>',
    ]
    for actor in participants:
        x = lane_x[actor]
        label = _xml_escape(_truncate_label(actor, 26))
        parts.append(
            f'<line x1="{x:.0f}" y1="{_SVG_SEQ_HEADER_H}" x2="{x:.0f}" y2="{height - _SVG_SEQ_MARGIN:.0f}" '
            'stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="4,4"/>'
        )
        parts.append(
            f'<rect x="{x - 90:.0f}" y="10" width="180" height="28" rx="6" ry="6" '
            'fill="#eef2ff" stroke="#334155" stroke-width="1.5"/>'
        )
        parts.append(f'<text x="{x:.0f}" y="28" text-anchor="middle" font-size="12" fill="#0f172a">{label}</text>')
    for index in range(len(ordered) - 1):
        source = lane_x[ordered[index]["actor"]]
        target = lane_x[ordered[index + 1]["actor"]]
        y = _SVG_SEQ_HEADER_H + index * _SVG_SEQ_STEP_GAP
        message = _xml_escape(_truncate_label(ordered[index + 1].get("label") or "calls", 30))
        parts.append(
            f'<line x1="{source:.0f}" y1="{y:.0f}" x2="{target:.0f}" y2="{y:.0f}" '
            'stroke="#475569" stroke-width="1.5" marker-end="url(#sq-arrow)"/>'
        )
        mx = (source + target) / 2
        parts.append(f'<text x="{mx:.0f}" y="{y - 6:.0f}" text-anchor="middle" font-size="10" fill="#334155">{message}</text>')
    if omitted:
        parts.append(
            f'<text x="{_SVG_SEQ_MARGIN}" y="{height - 8:.0f}" font-size="10" fill="#b91c1c">'
            f"{omitted} more step(s) omitted — see the fallback list</text>"
        )
    parts.append("</svg>")

    fallback = [f"{index + 1}. {step.get('label') or step['actor']}" for index, step in enumerate(chain)]
    return {"svg": "\n".join(parts), "truncated_steps": omitted, "fallback": fallback}


def render_state_diagram(
    states: list[str],
    transitions: list[dict],
    max_states: int = DEFAULT_MAX_STATES,
) -> dict:
    """Render a ``stateDiagram-v2`` from a set of states and transitions.

    ``transitions``: ``[{"from": str, "to": str, "label": optional str}, ...]``
    """
    ordered_states = sorted(set(states))
    kept_states = ordered_states[:max_states]
    omitted_states = len(ordered_states) - len(kept_states)
    kept = set(kept_states)

    edge_counts: dict[tuple[str, str, str], int] = {}
    for transition in transitions:
        source, target = transition.get("from"), transition.get("to")
        if source not in kept or target not in kept:
            continue
        key = (source, target, transition.get("label") or "")
        edge_counts[key] = edge_counts.get(key, 0) + 1
    ordered_edges = sorted(edge_counts.items(), key=lambda kv: kv[0])

    seen: dict[str, str] = {}
    lines = ["stateDiagram-v2"]
    for state in kept_states:
        lines.append(f"  {sanitize_id(state, seen)} : {escape_label(state)}")
    for (source, target, label), count in ordered_edges:
        source_id = sanitize_id(source, seen)
        target_id = sanitize_id(target, seen)
        suffix = f" : {escape_label(label)}" if label else (f" : {count}x" if count > 1 else "")
        lines.append(f"  {source_id} --> {target_id}{suffix}")
    if omitted_states:
        lines.append(f"  %% truncated: {omitted_states} state(s) omitted above max_states")
    fallback = [f"- {state}" for state in ordered_states]
    return {"mermaid": "\n".join(lines), "truncated_states": omitted_states, "fallback": fallback}


def render_state_diagram_svg(
    states: list[str],
    transitions: list[dict],
    max_states: int = DEFAULT_MAX_STATES,
    direction: str = "LR",
) -> dict:
    """Render a deterministic standalone SVG state diagram.

    States/transitions are reshaped into the generic node/edge graph and
    rendered by :func:`render_flowchart_svg` with pill-shaped nodes, so the
    layout and truncation guarantees are identical to the flowchart SVG.
    """
    unique_states = sorted(set(states))
    nodes = [{"id": state, "label": state} for state in unique_states]
    edges = [
        {"source": transition.get("from"), "target": transition.get("to"), "label": transition.get("label")}
        for transition in transitions
    ]
    graph = render_flowchart_svg(
        nodes,
        edges,
        direction=direction,
        max_nodes=max_states,
        max_edges=len(edges) or 1,
        node_shape="stadium",
    )
    return {
        "svg": graph["svg"],
        "truncated_states": graph["truncated_nodes"],
        "fallback": [f"- {state}" for state in unique_states],
    }


def to_markdown_block(result: dict, heading: str | None = None) -> str:
    """Wrap a diagram result dict into a Markdown block with fallback list."""
    lines: list[str] = []
    if heading:
        lines += [f"#### {heading}", ""]
    lines += ["```mermaid", result["mermaid"], "```", ""]
    truncated = (
        result.get("truncated_nodes")
        or result.get("truncated_edges")
        or result.get("truncated_steps")
        or result.get("truncated_states")
    )
    fallback = result.get("fallback") or []
    if fallback:
        summary = "Full list (diagram truncated)" if truncated else "Full list"
        lines += [f"<details><summary>{summary}</summary>", ""]
        lines.extend(fallback)
        lines += ["", "</details>", ""]
    return "\n".join(lines)
