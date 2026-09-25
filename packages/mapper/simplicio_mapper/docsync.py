"""Diff-driven documentation sync (Flow Documentation Engine F5).

Maps a git diff (working tree, staged, or an explicit range) to the
symbols, flows and generated docs it affects, then regenerates only what
changed instead of a full ``map``/``docs`` rebuild. Manual docs
(``docs/**``, ``.specs/**``) are never edited — when they textually
reference a changed path they are reported under ``needs_review`` instead.

Emits ``simplicio.docs-sync/v1`` as documented in
``SIMPLICIO_INTEGRATION.md``.
"""

from __future__ import annotations

import os
import subprocess

from .flows import _flow_diagram_svgs, build_flow_inventory, render_flow_inventory_markdown
from .mapper import (
    _render_module_doc,
    _slugify,
    _write_text_stable,
    build_artifacts,
    write_mapping_artifacts,
)

DOCS_SYNC_SCHEMA = "simplicio.docs-sync/v1"
DOCS_SYNC_VERSION = 1

_MANUAL_DOC_DIRS = ("docs", ".specs")
_MANUAL_DOC_EXCLUDE_DIRS = {".simplicio", "node_modules", ".git", "__pycache__"}


def _run_git(cwd: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _changed_files_from_git(cwd: str, range_spec: str | None, staged: bool) -> list[str] | None:
    if range_spec:
        output = _run_git(cwd, ["diff", "--name-only", range_spec])
    elif staged:
        output = _run_git(cwd, ["diff", "--name-only", "--cached"])
    else:
        output = _run_git(cwd, ["diff", "--name-only", "HEAD"])
        if output is None:
            output = _run_git(cwd, ["diff", "--name-only"])
        untracked = _run_git(cwd, ["ls-files", "--others", "--exclude-standard"])
        if output is not None and untracked is not None:
            output = output + untracked
    if output is None:
        return None
    return sorted({line.strip().replace(os.sep, "/") for line in output.splitlines() if line.strip()})


def _changed_files_from_cache(cwd: str, out_dir: str) -> list[str]:
    """Fallback for repositories without git: reuses the mapper's own
    changed-file detection (hash/status diff against the previous snapshot)."""
    artifacts = build_artifacts(cwd, output_dir=out_dir, incremental=True)
    return sorted(artifacts["project_map"].get("changed_files") or [])


def _symbols_for_files(symbol_index: dict, files: set[str]) -> list[dict]:
    return sorted(
        (s for s in symbol_index.get("symbols") or [] if s["defined_in"] in files),
        key=lambda s: (s["defined_in"], s.get("line", 0)),
    )


def _flows_touching(flow_inventory: dict, files: set[str]) -> list[str]:
    touched = []
    for flow in flow_inventory.get("flows") or []:
        step_paths = {step["path"] for step in flow.get("steps") or []}
        effect_paths = {effect["evidence"]["path"] for effect in flow.get("effects") or []}
        flow_paths = step_paths | effect_paths | {flow["entry"]["path"]}
        if flow_paths & files:
            touched.append(flow["id"])
    return sorted(touched)


def _modules_for_files(files: set[str]) -> set[str]:
    return {(f.split("/", 1)[0] if "/" in f else ".") for f in files}


def _scan_manual_docs_for_references(cwd: str, files: set[str]) -> list[dict]:
    """Best-effort textual scan of docs/** and .specs/** for references to a
    changed path. Never edits these files — only flags them for review."""
    if not files:
        return []
    candidates: list[str] = []
    for base in _MANUAL_DOC_DIRS:
        base_path = os.path.join(cwd, base)
        if not os.path.isdir(base_path):
            continue
        for current, dirs, names in os.walk(base_path):
            dirs[:] = [d for d in dirs if d not in _MANUAL_DOC_EXCLUDE_DIRS]
            candidates.extend(os.path.join(current, name) for name in names if name.endswith(".md"))

    needs_review = []
    for doc_path in sorted(candidates):
        try:
            with open(doc_path, encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
        except OSError:
            continue
        rel_doc = os.path.relpath(doc_path, cwd).replace(os.sep, "/")
        for changed in sorted(files):
            if changed and changed in text:
                needs_review.append({"doc": rel_doc, "reason": f"references {changed}"})
                break
    return needs_review


def _would_change(path: str, new_text: str) -> bool:
    new_text = new_text.rstrip() + "\n"
    try:
        with open(path, encoding="utf-8") as handle:
            current = handle.read()
    except OSError:
        return True
    return current != new_text


def build_docs_sync(
    cwd: str,
    out_dir: str = ".simplicio",
    range_spec: str | None = None,
    staged: bool = False,
    check: bool = False,
) -> dict:
    """Compute (and, unless ``check``, apply) the doc-sync payload for the
    diff currently in ``cwd``."""
    abs_cwd = os.path.abspath(cwd)
    abs_out = os.path.abspath(os.path.join(abs_cwd, out_dir))
    changed = _changed_files_from_git(abs_cwd, range_spec, staged)
    diff_source = "git"
    if changed is None:
        changed = _changed_files_from_cache(abs_cwd, out_dir)
        diff_source = "cache"
    changed_set = set(changed)

    # Always compute artifacts fresh in memory so --check reflects the current
    # tree even though it must not persist anything to disk.
    artifacts = build_artifacts(abs_cwd, output_dir=out_dir)
    if not check:
        write_mapping_artifacts(abs_cwd, output_dir=out_dir)

    inventory = artifacts["architecture_inventory"]
    symbol_index = artifacts["symbol_index"]
    flow_inventory = build_flow_inventory(abs_cwd, artifacts)

    affected_symbols = _symbols_for_files(symbol_index, changed_set)
    affected_flows = _flows_touching(flow_inventory, changed_set)
    affected_modules = _modules_for_files(changed_set)
    needs_review = _scan_manual_docs_for_references(abs_cwd, changed_set)

    docs_root = os.path.join(abs_out, "docs")
    regenerated_docs: list[str] = []
    stale_docs: list[str] = []

    if changed_set:
        # Whole-repo aggregate docs always reflect the current tree.
        for name, text in _render_global_docs(inventory, artifacts["symbol_index"], artifacts["call_graph"]):
            path = os.path.join(docs_root, name)
            if check:
                if _would_change(path, text):
                    stale_docs.append(path.replace(os.sep, "/"))
            else:
                _write_text_stable(path, text)
                regenerated_docs.append(path.replace(os.sep, "/"))

        # Per-module docs: only the modules touched by the diff are re-rendered.
        modules_by_name = {module["name"]: module for module in inventory.get("modules", [])}
        for module_name in sorted(affected_modules & modules_by_name.keys()):
            module = modules_by_name[module_name]
            text = _render_module_doc(module, inventory)
            path = os.path.join(docs_root, "modules", f"{_slugify(module_name)}.md")
            if check:
                if _would_change(path, text):
                    stale_docs.append(path.replace(os.sep, "/"))
            else:
                _write_text_stable(path, text)
                regenerated_docs.append(path.replace(os.sep, "/"))

        # flows.md only regenerates when the diff actually touches a known flow.
        if affected_flows:
            text = render_flow_inventory_markdown(flow_inventory)
            path = os.path.join(docs_root, "flows.md")
            if check:
                if _would_change(path, text):
                    stale_docs.append(path.replace(os.sep, "/"))
            else:
                _write_text_stable(path, text)
                regenerated_docs.append(path.replace(os.sep, "/"))
            for rel_path, svg in _flow_diagram_svgs(flow_inventory).items():
                svg_path = os.path.join(docs_root, rel_path)
                if check:
                    if _would_change(svg_path, svg):
                        stale_docs.append(svg_path.replace(os.sep, "/"))
                else:
                    _write_text_stable(svg_path, svg)
                    regenerated_docs.append(svg_path.replace(os.sep, "/"))

    return {
        "schema": DOCS_SYNC_SCHEMA,
        "version": DOCS_SYNC_VERSION,
        "diff": {
            "range": range_spec or ("staged" if staged else "working-tree"),
            "files": len(changed_set),
            "source": diff_source,
        },
        "changed_files": sorted(changed_set),
        "affected_symbols": [
            {"symbol": s.get("qualified_name") or s.get("name"), "path": s["defined_in"]}
            for s in affected_symbols
        ],
        "affected_flows": affected_flows,
        "regenerated_docs": sorted(set(regenerated_docs)),
        "needs_review": needs_review,
        "stale": bool(stale_docs) if check else False,
        "stale_docs": sorted(set(stale_docs)),
    }


def _render_global_docs(inventory: dict, symbol_index: dict, call_graph: dict) -> list[tuple[str, str]]:
    # Local import avoids a module-level cycle (mapper imports cli which
    # could in turn want docsync in the future).
    from .mapper import (
        _global_diagram_svgs,
        _render_architecture_overview,
        _render_call_graph_doc,
        _render_layers_doc,
    )

    module_index = ["# Modules", ""]
    for module in inventory.get("modules", []):
        module_index.append(f"- [{module['name']}](modules/{_slugify(module['name'])}.md)")

    docs = [
        ("architecture.md", _render_architecture_overview(inventory, symbol_index, call_graph)),
        ("layers.md", _render_layers_doc(inventory)),
        ("call-graph.md", _render_call_graph_doc(call_graph)),
        ("modules.md", "\n".join(module_index)),
    ]
    docs.extend(_global_diagram_svgs(inventory, call_graph).items())
    return docs
