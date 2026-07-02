"""Flow inventory builder (Flow Documentation Engine F2).

Generalizes the web-only ``flowchart`` extractor to any stack: derives
end-to-end flows from the call graph, starting at entry points (CLI
commands, ``main`` functions, bin/ scripts) and walking ``calls`` edges to
the effects the flow produces (filesystem writes, network calls,
subprocess spawns, cache/DB access).

Emits ``simplicio.flow-inventory/v1`` as documented in
``SIMPLICIO_INTEGRATION.md``. Every step and effect carries ``path``/``line``
evidence; nothing here infers business semantics (see ``business.py`` /
F3 for that layer).
"""

from __future__ import annotations

import os
import re
from collections import deque
from typing import Any

from .diagrams import render_flowchart, to_markdown_block

FLOW_INVENTORY_SCHEMA = "simplicio.flow-inventory/v1"
FLOW_ARTIFACT_VERSION = 1

DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_STEPS = 25
DEFAULT_FANOUT_CAP = 8

# (regex, effect type) — heuristic signals scanned once per visited file.
# Order matters: first match per line wins so a line is not double-counted.
_EFFECT_SIGNALS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"_write_json_stable|_write_text_stable|orjson\.dumps|json\.dump\("), "fs-write"),
    (re.compile(r"open\([^)]*['\"]w"), "fs-write"),
    (re.compile(r"os\.replace\(|shutil\.copyfile\(|fs\.writeFileSync\(|fs\.copyFileSync\("), "fs-write"),
    (re.compile(r"open\([^)]*['\"]r|fs\.readFileSync\("), "fs-read"),
    (re.compile(r"subprocess\.|Popen\(|os\.system\(|child_process\."), "subprocess"),
    (re.compile(r"requests\.|urlopen\(|http\.client|fetch\(|axios\."), "network"),
    (re.compile(r"diskcache|FileProcessingCache|sqlite3|cursor\.execute|\.query\("), "cache-or-db"),
]

_READ_CACHE: dict[str, str] = {}


def _read_cached(cwd: str, rel_path: str) -> str:
    key = os.path.join(cwd, rel_path)
    if key in _READ_CACHE:
        return _READ_CACHE[key]
    try:
        with open(key, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        text = ""
    _READ_CACHE[key] = text
    return text


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _scan_effects(cwd: str, rel_path: str) -> list[dict]:
    text = _read_cached(cwd, rel_path)
    if not text:
        return []
    found: list[dict] = []
    seen_lines: set[tuple[str, int]] = set()
    for pattern, effect_type in _EFFECT_SIGNALS:
        for match in pattern.finditer(text):
            line = _line_of(text, match.start())
            key = (effect_type, line)
            if key in seen_lines:
                continue
            seen_lines.add(key)
            found.append({
                "type": effect_type,
                "evidence": {"path": rel_path, "line": line},
            })
    return sorted(found, key=lambda item: (item["type"], item["evidence"]["line"]))


def _module_name_for_path(rel: str) -> str:
    if "/" not in rel:
        return "."
    return rel.split("/", 1)[0]


def _symbols_by_file(symbol_index: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for symbol in symbol_index.get("symbols") or []:
        index.setdefault(symbol["defined_in"], []).append(symbol)
    for symbols in index.values():
        symbols.sort(key=lambda item: item.get("line", 0))
    return index


def _calls_by_source_file(call_graph: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for edge in call_graph.get("edges") or []:
        if edge.get("type") != "calls":
            continue
        index.setdefault(edge["source_file"], []).append(edge)
    for edges in index.values():
        edges.sort(key=lambda item: (item.get("target_file") or "", item.get("target_symbol") or ""))
    return index


def _layers_for_path(rel: str, architecture_inventory: dict) -> list[str]:
    for file_entry in architecture_inventory.get("files") or []:
        if file_entry.get("path") == rel:
            return list(file_entry.get("layers") or [])
    return []


def _flow_kind(entry_path: str) -> str:
    if entry_path.startswith("bin/") or "/bin/" in entry_path:
        return "cli-command"
    if entry_path.endswith((".py", ".js", ".ts")):
        return "entrypoint"
    return "entrypoint"


def _flow_id(entry_path: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", entry_path)
    return re.sub(r"[^a-z0-9]+", ".", stem.lower()).strip(".") or "flow"


def _derive_flow(
    entry_path: str,
    cwd: str,
    symbols_by_file: dict[str, list[dict]],
    calls_by_file: dict[str, list[dict]],
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_steps: int = DEFAULT_MAX_STEPS,
    fanout_cap: int = DEFAULT_FANOUT_CAP,
) -> tuple[list[dict], list[dict], set[str]]:
    visited_files = {entry_path}
    steps: list[dict] = []
    effects: list[dict] = []
    queue: deque[tuple[str, int]] = deque([(entry_path, 0)])

    while queue and len(steps) < max_steps:
        current_file, depth = queue.popleft()
        file_symbols = symbols_by_file.get(current_file) or []
        entry_symbol = file_symbols[0] if file_symbols else None
        steps.append({
            "module": _module_name_for_path(current_file),
            "path": current_file,
            "symbol": entry_symbol.get("qualified_name") if entry_symbol else None,
            "line": entry_symbol.get("line", 0) if entry_symbol else 0,
        })
        effects.extend(_scan_effects(cwd, current_file))
        if depth >= max_depth:
            continue
        for edge in (calls_by_file.get(current_file) or [])[:fanout_cap]:
            target_file = edge.get("target_file")
            if not target_file or target_file in visited_files:
                continue
            visited_files.add(target_file)
            queue.append((target_file, depth + 1))

    return steps, effects, visited_files


def _dedupe_effects(effects: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, int]] = set()
    out = []
    for effect in effects:
        key = (effect["type"], effect["evidence"]["path"], effect["evidence"]["line"])
        if key in seen:
            continue
        seen.add(key)
        out.append(effect)
    return sorted(out, key=lambda item: (item["type"], item["evidence"]["path"], item["evidence"]["line"]))


def build_flow_inventory(cwd: str, artifacts: dict[str, Any]) -> dict:
    """Build the ``simplicio.flow-inventory/v1`` payload from already-built
    mapper artifacts (see ``mapper.build_artifacts``)."""
    _READ_CACHE.clear()
    abs_cwd = os.path.abspath(cwd)
    project_map = artifacts["project_map"]
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    architecture_inventory = artifacts["architecture_inventory"]

    entry_points = sorted(set(project_map.get("entry_points") or []))
    symbols_by_file = _symbols_by_file(symbol_index)
    calls_by_file = _calls_by_source_file(call_graph)

    flows = []
    for entry in entry_points:
        steps, raw_effects, visited = _derive_flow(entry, abs_cwd, symbols_by_file, calls_by_file)
        effects = _dedupe_effects(raw_effects)
        entry_step = steps[0] if steps else {"symbol": None, "line": 0}
        layers_touched = sorted({
            layer
            for path in visited
            for layer in _layers_for_path(path, architecture_inventory)
        })
        flows.append({
            "id": _flow_id(entry),
            "kind": _flow_kind(entry),
            "entry": {
                "path": entry,
                "symbol": entry_step.get("symbol"),
                "line": entry_step.get("line", 0),
            },
            "steps": steps,
            "effects": effects,
            "layers_touched": layers_touched,
            "confidence": "observed" if effects else "heuristic",
        })

    flows.sort(key=lambda item: item["id"])
    coverage = {
        "entrypoints_total": len(entry_points),
        "entrypoints_with_flow": len([f for f in flows if len(f["steps"]) > 1 or f["effects"]]),
    }
    return {
        "schema": FLOW_INVENTORY_SCHEMA,
        "version": FLOW_ARTIFACT_VERSION,
        "generated_at": project_map.get("generated_at"),
        "root": abs_cwd.replace(os.sep, "/"),
        "flows": flows,
        "coverage": coverage,
    }


_EFFECT_LABELS = {
    "fs-write": "writes filesystem",
    "fs-read": "reads filesystem",
    "subprocess": "spawns subprocess",
    "network": "makes network call",
    "cache-or-db": "touches cache/DB",
}


def render_flow_inventory_markdown(inventory: dict) -> str:
    coverage = inventory.get("coverage", {})
    flows = inventory.get("flows") or []
    lines = [
        "# Flow Inventory",
        "",
        "Auto-generated from the call graph. A flow starts at a detected entry point "
        "(CLI command, `main`, bin/ script) and follows `calls` edges to the effects "
        "it produces (filesystem, network, subprocess, cache/DB).",
        "",
        "> Steps and effects are **observed** from static analysis (evidence "
        "`path:line`). Dynamic dispatch (e.g. a string-keyed command table) is not "
        "followed by the call graph and may under-report steps — see `confidence`.",
        "",
        "## Coverage",
        "",
        f"- Entry points detected: {coverage.get('entrypoints_total', 0)}",
        f"- Entry points with a derived flow: {coverage.get('entrypoints_with_flow', 0)}",
        f"- Total flows: {len(flows)}",
        "",
    ]
    if not flows:
        lines.append("No entry points were detected in this repository.")
        return "\n".join(lines)

    for flow in flows:
        lines += [
            f"## `{flow['id']}`",
            "",
            f"- Kind: {flow['kind']}",
            f"- Entry: `{flow['entry']['path']}`" + (f" (`{flow['entry']['symbol']}`)" if flow["entry"].get("symbol") else ""),
            f"- Confidence: {flow['confidence']}",
            f"- Layers touched: {', '.join(flow['layers_touched']) or 'none detected'}",
            "",
        ]
        step_nodes = [{"id": step["path"], "label": step["path"]} for step in flow["steps"]]
        step_edges = [
            {"source": flow["steps"][i]["path"], "target": flow["steps"][i + 1]["path"]}
            for i in range(len(flow["steps"]) - 1)
        ]
        if step_nodes:
            diagram = render_flowchart(step_nodes, step_edges, direction="LR")
            lines.append(to_markdown_block(diagram, heading="Steps"))

        if flow["effects"]:
            lines += ["**Effects**", "", "| Type | Evidence |", "| --- | --- |"]
            for effect in flow["effects"]:
                label = _EFFECT_LABELS.get(effect["type"], effect["type"])
                evidence = effect["evidence"]
                lines.append(f"| {label} | `{evidence['path']}:{evidence['line']}` |")
            lines.append("")
        else:
            lines.append("_No observable effects detected for this flow._")
            lines.append("")

    return "\n".join(lines)
