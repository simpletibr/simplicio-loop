"""Deterministic Mermaid diagram rendering shared by mapper doc renderers.

Implements the guardrails required by the Flow Documentation Engine spec
(``.specs/product/flow-documentation-spec.md`` F4): stable ordering (same
input tree -> same diagram, byte for byte), sanitized/collision-free node
ids, escaped labels, a hard cap on nodes/edges with an explicit truncation
note (never a silent cut), and a textual fallback list next to every
diagram so the same information survives when Mermaid is not rendered.

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
