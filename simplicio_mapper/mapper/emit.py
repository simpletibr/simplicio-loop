"""Serialization layer: assembles ``.simplicio/*.json`` artifacts
(project-map, precedent-index, architecture-inventory, symbol-index,
call-graph) from ``.parse``/``.graph`` output, writes them + the
rendered markdown/SVG architecture docs to disk. Split from the
former monolithic ``mapper.py`` (issue #159) -- pure move, no
behavior change.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import Callable
from typing import Any

import orjson

from ..cache import FileProcessingCache
from ..diagrams import render_flowchart, render_flowchart_svg, to_image_markdown, to_markdown_block
from ..models import ProjectFile
from .graph import (
    _build_architecture_inventory,
    _build_call_graph,
    _build_symbol_index,
    _collect_architecture_signals,
)
from .parse import (
    _JSON_WRITE_OPTIONS,
    ARTIFACT_SCHEMA,
    ARTIFACT_VERSION,
    LLM_DIRECTIVES,
    PRECEDENT_SCHEMA,
    TEXT_EXTS,
    _agent_id_from_seed,
    _build_brown_hilbert_map,
    _build_file_inventory,
    _build_precedent_items,
    _collect_entities,
    _detect_changed_files,
    _git_status_map,
    _group_modules,
    _load_previous_map,
    _module_name_for_path,
    _now_iso,
    _parse_json_safe,
    _walk,
)


def _build_agent_tree(
    files: list[ProjectFile],
    bh_map: dict[str, tuple[str, str]],
) -> dict:
    """Build a nested Brown-Hilbert agent tree from the file inventory.

    The tree mirrors the project's module structure and annotates every node
    with its BH address, agent ID, and the resources it owns.
    """
    # Collect module nodes
    module_groups: dict[str, dict] = {}
    for f in files:
        module = f.path.split("/")[0] if "/" in f.path else "."
        if module not in module_groups:
            mod_addr, mod_agent = bh_map.get(f"__module__:{module}", ("R.0", ""))
            module_groups[module] = {
                "bh_address": mod_addr,
                "agent_id": mod_agent,
                "module": module,
                "children": [],
            }
        addr, agent = bh_map.get(f.path, ("", ""))
        module_groups[module]["children"].append({
            "bh_address": addr,
            "agent_id": agent,
            "path": f.path,
            "language": f.language,
            "roles": f.roles,
        })

    # Root node
    root_agent = _agent_id_from_seed("R")
    root_node: dict = {
        "bh_address": "R",
        "agent_id": root_agent,
        "module": ".",
        "children": [],
    }

    for module_name in sorted(module_groups):
        root_node["children"].append(module_groups[module_name])

    return root_node

#: Env var overriding the file-count threshold below which `build_artifacts`
#: routes through the plain synchronous pipeline instead of the async one
#: (issue #235 follow-up: size-based dispatch). See
#: `docs/async-pipeline-dispatch-benchmark.md` for the measurement behind
#: the default below -- small/medium trees were measurably SLOWER under the
#: async pipeline (asyncio/thread-pool scheduling overhead outweighs I/O-wait
#: savings when there is little I/O-wait to hide), so the async path is now
#: opt-in above this file count, not the unconditional default.
_ASYNC_PIPELINE_MIN_FILES_ENV = "SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES"
_DEFAULT_ASYNC_PIPELINE_MIN_FILES = 600


def _async_pipeline_min_files(cwd: str | None = None, output_dir: str = ".simplicio") -> int:
    """Threshold (inclusive-exclusive: async engages at >= this count).

    Resolution order (issue #279 Phase-0: local per-machine calibration,
    see ``pipeline_calibration.py`` / ADR-010):

    1. ``SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES`` env var override --
       unchanged, highest priority, exactly as before this issue (any
       non-positive or non-integer override is ignored in favor of the
       next tier rather than silently disabling one of the two pipelines).
    2. A cached, machine-specific calibration file at
       ``<cwd>/<output_dir>/pipeline-calibration.json`` (written by
       ``simplicio-mapper benchmark pipeline-threshold``), if *cwd* is
       given and a valid one exists.
    3. The hardcoded, Windows-measured default (600) -- exactly today's
       behavior when neither of the above is present, so a caller that
       never ran calibration and never set the env var sees byte-for-byte
       unchanged behavior.
    """
    override = os.environ.get(_ASYNC_PIPELINE_MIN_FILES_ENV)
    if override:
        try:
            value = int(override)
        except ValueError:
            value = 0
        if value > 0:
            return value
    if cwd is not None:
        from .pipeline_calibration import load_calibrated_threshold

        calibrated = load_calibrated_threshold(cwd, output_dir)
        if calibrated is not None:
            return calibrated
    return _DEFAULT_ASYNC_PIPELINE_MIN_FILES


def _fast_file_count(cwd: str, cap: int) -> int:
    """Cheap, content-free file-count probe used only to pick a pipeline.

    Reuses the exact same directory walk/skip logic as
    ``parse._collect_text_files`` (``_walk`` -> ``SKIP_DIRS``/worktree
    exclusions) and the same extension allowlist (``TEXT_EXTS``), but never
    opens a file or calls ``os.path.getsize`` -- this must stay a fast
    pre-pass, not a second expensive walk. Early-exits as soon as ``cap``
    matching files have been seen, so probing a very large tree costs
    O(cap) directory entries touched, not O(total files) -- a repo with
    100k files and a threshold of 600 still only walks until the 600th
    match, then immediately routes to the async pipeline.
    """
    count = 0
    for file in _walk(cwd):
        ext = os.path.splitext(file)[1].lower()
        if ext not in TEXT_EXTS:
            continue
        count += 1
        if count >= cap:
            return count
    return count


def _build_artifacts_sync(cwd: str, meta: dict | None = None, incremental: bool = False,
                           output_dir: str = ".simplicio") -> dict:
    """Original, fully-synchronous pipeline (pre-issue-#235 behavior).

    Kept side-by-side with the async pipeline (`async_pipeline.build_artifacts_async`)
    rather than removed: the after-benchmark (ADR-009 plan step 10,
    `docs/async-pipeline-after-benchmark.md`) showed small/medium synthetic
    trees are genuinely SLOWER end-to-end under the async pipeline than this
    plain loop, because `asyncio`/thread-pool scheduling overhead outweighs
    the I/O-wait it hides when there is little I/O-wait to begin with.
    `build_artifacts` dispatches to this function for trees below
    `_async_pipeline_min_files()`.
    """
    meta = meta or {}
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    pkg = _parse_json_safe(os.path.join(abs_cwd, "package.json"))
    contents: dict[str, str] = {}
    skipped_large_files: list[str] = []
    degraded = {
        "git_timeout": False,
        "git_status_unavailable": False,
        "skipped_large_files": [],
        "large_file_limit_bytes": 250000,
    }
    status_map = _git_status_map(abs_cwd, degraded=degraded)
    previous_map = _load_previous_map(abs_out)
    cache_dir = os.path.join(abs_out, "cache")
    with FileProcessingCache(cache_dir) as file_cache:
        files = _build_file_inventory(
            abs_cwd,
            pkg,
            status_map,
            file_cache,
            contents=contents,
            skipped_large_files=skipped_large_files,
        )
    degraded["skipped_large_files"] = sorted(skipped_large_files)
    file_entries = [file.to_dict() for file in files]
    corpus = "\n".join(file.text_preview for file in files[:80])
    changed_files = _detect_changed_files(files, previous_map, status_map, incremental)
    stack = meta.get("stack") or pkg.get("type") or "unknown"
    product_name = meta.get("product_name") or pkg.get("name") or os.path.basename(abs_cwd)
    architecture_signals = _collect_architecture_signals(pkg, corpus, stack)
    generated_at = _now_iso()

    if os.path.exists(os.path.join(abs_cwd, "pnpm-lock.yaml")):
        package_manager = "pnpm"
    elif os.path.exists(os.path.join(abs_cwd, "yarn.lock")):
        package_manager = "yarn"
    else:
        package_manager = "npm"

    web_signal = "react" in architecture_signals or "nextjs" in architecture_signals
    if meta.get("project_mode") == "monorepo":
        system_type = "monorepo"
    else:
        system_type = "web" if web_signal else "library-or-service"

    project_map = {
        "schema": ARTIFACT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "update_mode": "incremental" if incremental else "full",
        "product": {
            "name": product_name,
            "stack": stack,
            "project_mode": meta.get("project_mode", "root"),
        },
        "files": file_entries,
        "entry_points": [f.path for f in files if "entrypoint" in f.roles],
        "test_files": [f.path for f in files if "test" in f.roles],
        "config_files": [f.path for f in files if "config" in f.roles],
        "modules": _group_modules(files),
        "entities": _collect_entities(files),
        "architecture": {
            "signals": architecture_signals,
            "system_type": system_type,
        },
        "dependencies": {
            "package_manager": package_manager,
            "manifest": "package.json" if pkg.get("name") else None,
            "runtime": sorted((pkg.get("dependencies") or {}).keys()),
            "dev": sorted((pkg.get("devDependencies") or {}).keys()),
        },
        "recent_changes": [
            {"path": file, "status": status_map.get(file, "modified")} for file in changed_files
        ],
        "changed_files": changed_files,
        "integration": {
            "dev_cli_mapper": "read .simplicio/project-map.json, then use .simplicio/precedent-index.json for task-specific examples",
            "contract": "SIMPLICIO_INTEGRATION.md",
            "llm_directives": LLM_DIRECTIVES,
        },
        "degraded": degraded,
    }

    precedent_index = {
        "schema": PRECEDENT_SCHEMA,
        "version": ARTIFACT_VERSION,
        "generated_at": generated_at,
        "source_project_map": ".simplicio/project-map.json",
        "items": _build_precedent_items(abs_cwd, files, contents=contents),
    }

    symbol_index = _build_symbol_index(abs_cwd, files, generated_at, contents=contents)
    call_graph = _build_call_graph(abs_cwd, files, symbol_index, generated_at, contents=contents)
    architecture_inventory = _build_architecture_inventory(
        abs_cwd,
        project_map,
        files,
        symbol_index,
        call_graph,
        generated_at,
    )

    bh_map = _build_brown_hilbert_map(files)
    agent_tree = _build_agent_tree(files, bh_map)

    project_map["agent_tree"] = agent_tree
    contents.clear()

    return {
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
    }


def build_artifacts(cwd: str, meta: dict | None = None, incremental: bool = False,
                    output_dir: str = ".simplicio") -> dict:
    """Build every `.simplicio/*.json` artifact for *cwd*.

    Size-based dispatch (issue #235 follow-up, ADR-009 plan step 10's
    honest after-benchmark): a cheap, content-free file-count probe
    (`_fast_file_count`) decides whether this run goes through the plain
    synchronous pipeline (`_build_artifacts_sync`, restored pre-#235
    behavior) or the bounded-concurrency async pipeline
    (`async_pipeline.build_artifacts_async`, driven to completion via
    `asyncio.run`). The after-benchmark showed the async pipeline is a real
    win only at large scale (>= roughly 600 files on this measurement) --
    below that, `asyncio`/thread-pool scheduling overhead measurably
    outweighs the I/O-wait it hides, so small/medium trees (the common
    case for this tool) now default back to the faster synchronous path.
    See `docs/async-pipeline-dispatch-benchmark.md` for the crossover
    measurement and `_DEFAULT_ASYNC_PIPELINE_MIN_FILES` for the chosen
    default. Issue #279 Phase-0 adds an opt-in, per-machine override: if
    `<output_dir>/pipeline-calibration.json` exists and is valid (written by
    `simplicio-mapper benchmark pipeline-threshold`, see
    `pipeline_calibration.py`), its `recommended_threshold` is used instead
    of the hardcoded default -- absent that file, behavior is unchanged.

    Callers that are themselves already inside an event loop (a future
    async CLI, or an embedding host) should ``await build_artifacts_async(...)``
    directly instead of calling this sync wrapper -- ``asyncio.run`` raises
    ``RuntimeError`` if invoked from a running loop, by design, rather than
    silently nesting event loops.
    """
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    threshold = _async_pipeline_min_files(abs_cwd, output_dir)
    if _fast_file_count(abs_cwd, threshold) < threshold:
        return _build_artifacts_sync(abs_cwd, meta, incremental, output_dir)

    # Local import: `async_pipeline` imports `_build_agent_tree` from this
    # module only inside its own function body, so importing it here (also
    # deferred to call time) keeps the dependency a call-time-only cycle,
    # never a module-load-time one.
    from .async_pipeline import _install_uvloop_if_available, build_artifacts_async

    _install_uvloop_if_available()
    return asyncio.run(build_artifacts_async(abs_cwd, meta, incremental, output_dir))

def _write_json_stable(file: str, data: Any) -> None:
    directory = os.path.dirname(file)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = f"{file}.tmp"
    with open(tmp, "wb") as handle:
        handle.write(orjson.dumps(data, option=_JSON_WRITE_OPTIONS))
    os.replace(tmp, file)

def write_mapping_artifacts(cwd: str, meta: dict | None = None, incremental: bool = False,
                            output_dir: str = ".simplicio",
                            log: Callable[[str], None] | None = None) -> dict:
    log = log or (lambda _line: None)
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    artifacts = build_artifacts(abs_cwd, meta, incremental, output_dir)
    project_map = artifacts["project_map"]
    precedent_index = artifacts["precedent_index"]
    architecture_inventory = artifacts["architecture_inventory"]
    symbol_index = artifacts["symbol_index"]
    call_graph = artifacts["call_graph"]
    project_map_path = os.path.join(abs_out, "project-map.json")
    precedent_path = os.path.join(abs_out, "precedent-index.json")
    architecture_inventory_path = os.path.join(abs_out, "architecture-inventory.json")
    symbol_index_path = os.path.join(abs_out, "symbol-index.json")
    call_graph_path = os.path.join(abs_out, "call-graph.json")
    _write_json_stable(project_map_path, project_map)
    _write_json_stable(precedent_path, precedent_index)
    _write_json_stable(architecture_inventory_path, architecture_inventory)
    _write_json_stable(symbol_index_path, symbol_index)
    _write_json_stable(call_graph_path, call_graph)
    log(f"-> wrote {os.path.relpath(project_map_path, abs_cwd)} "
        f"({len(project_map['files'])} files, {len(project_map['changed_files'])} changed)")
    log(f"-> wrote {os.path.relpath(precedent_path, abs_cwd)} "
        f"({len(precedent_index['items'])} precedents)")
    log(f"-> wrote {os.path.relpath(architecture_inventory_path, abs_cwd)} "
        f"({architecture_inventory['coverage']['modules']} modules, {architecture_inventory['coverage']['layers']} layers)")
    log(f"-> wrote {os.path.relpath(symbol_index_path, abs_cwd)} "
        f"({symbol_index['counts']['symbols']} symbols)")
    log(f"-> wrote {os.path.relpath(call_graph_path, abs_cwd)} "
        f"({call_graph['counts']['edges']} relationships)")
    return {
        "project_map_path": project_map_path,
        "precedent_path": precedent_path,
        "architecture_inventory_path": architecture_inventory_path,
        "symbol_index_path": symbol_index_path,
        "call_graph_path": call_graph_path,
        "project_map": project_map,
        "precedent_index": precedent_index,
        "architecture_inventory": architecture_inventory,
        "symbol_index": symbol_index,
        "call_graph": call_graph,
    }

def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if str(value).startswith(".") and slug:
        return f"dot-{slug}"
    return slug or "root"

def _write_text_stable(file: str, text: str) -> None:
    os.makedirs(os.path.dirname(file), exist_ok=True)
    tmp = f"{file}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")
    os.replace(tmp, file)

def _file_ref(path: str, line: int | None = None) -> str:
    suffix = f":{line}" if line else ""
    return f"`{path}{suffix}`"

def _module_dependency_graph(modules: list[dict], call_graph: dict) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": module["name"], "label": module["name"]} for module in modules]
    edges = []
    for edge in call_graph.get("edges", []):
        if edge.get("type") != "imports" or not edge.get("source_file") or not edge.get("target_file"):
            continue
        source_module = _module_name_for_path(edge["source_file"])
        target_module = _module_name_for_path(edge["target_file"])
        if source_module == target_module:
            continue
        edges.append({"source": source_module, "target": target_module})
    return nodes, edges

def _layer_module_graph(layers: list[dict]) -> tuple[list[dict], list[dict]]:
    layer_nodes = [{"id": f"layer:{layer['name']}", "label": layer["name"]} for layer in layers]
    module_ids = {module for layer in layers for module in layer.get("modules") or []}
    module_nodes = [{"id": f"module:{name}", "label": name} for name in module_ids]
    edges = [
        {"source": f"layer:{layer['name']}", "target": f"module:{module}"}
        for layer in layers
        for module in layer.get("modules") or []
    ]
    return layer_nodes + module_nodes, edges

def _call_graph_file_graph(call_graph: dict) -> tuple[list[dict], list[dict]]:
    # ``target_symbol`` (unresolved calls) and ``target_file`` (imports/resolved
    # calls) are different id spaces — prefixed so a symbol name can never
    # collide with a same-named file path (mirrors the layer:/module: prefix
    # convention in _layer_module_graph).
    seen_nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for edge in call_graph.get("edges", []):
        source_file = edge.get("source_file")
        target_file = edge.get("target_file")
        target_symbol = edge.get("target_symbol")
        if not source_file:
            continue
        if target_file:
            target_id, target_label = target_file, target_file
        elif target_symbol:
            target_id, target_label = f"symbol:{target_symbol}", target_symbol
        else:
            continue
        if source_file == target_id:
            continue
        seen_nodes.setdefault(source_file, {"id": source_file, "label": source_file})
        seen_nodes.setdefault(target_id, {"id": target_id, "label": target_label})
        edges.append({"source": source_file, "target": target_id})
    return list(seen_nodes.values()), edges

def _render_architecture_overview(inventory: dict, symbol_index: dict, call_graph: dict) -> str:
    product = inventory.get("product", {})
    coverage = inventory.get("coverage", {})
    modules = inventory.get("modules", [])
    layers = inventory.get("layers", [])
    lines = [
        f"# {product.get('name') or 'Project'} Architecture Inventory",
        "",
        "Generated from `.simplicio` machine-readable artifacts. Statements below are derived from repository structure, imports, symbols and deterministic heuristics.",
        "",
        "## Coverage",
        "",
        f"- Files: {coverage.get('files', 0)}",
        f"- Modules: {coverage.get('modules', 0)}",
        f"- Layers: {coverage.get('layers', 0)}",
        f"- Symbols: {coverage.get('symbols', 0)}",
        f"- Relationships: {coverage.get('relationships', 0)}",
        f"- Tests: {coverage.get('tests', 0)}",
        "",
        "## Modules",
        "",
    ]
    for module in modules[:40]:
        lines.append(
            f"- `{module['name']}`: {module['file_count']} files; layers: "
            f"{', '.join(module.get('layers') or ['none'])}"
        )
    lines.extend(["", "## Layers", ""])
    for layer in layers:
        lines.append(f"- `{layer['name']}`: {layer['file_count']} files across {len(layer.get('modules', []))} modules")

    module_nodes, module_edges = _module_dependency_graph(modules, call_graph)
    if module_nodes:
        diagram = render_flowchart(module_nodes, module_edges, direction="TB")
        lines.extend(["", "## Module Dependency Diagram", ""])
        lines.append(to_image_markdown("diagrams/architecture-modules.svg", "Module dependency diagram"))
        lines.append("")
        lines.append(to_markdown_block(diagram))

    if symbol_index.get("symbols"):
        lines.extend(["", "## Top Symbols", ""])
        for symbol in symbol_index["symbols"][:40]:
            lines.append(
                f"- `{symbol['name']}` ({symbol['kind']}) in "
                f"{_file_ref(symbol['defined_in'], symbol.get('line'))}"
            )
    return "\n".join(lines)

def _render_layers_doc(inventory: dict) -> str:
    lines = ["# Architecture Layers", ""]
    layers = inventory.get("layers", [])
    graph_nodes, layer_edges = _layer_module_graph(layers)
    if graph_nodes:
        diagram = render_flowchart(graph_nodes, layer_edges, direction="LR")
        lines.append(to_image_markdown("diagrams/layers.svg", "Layers to modules diagram"))
        lines.append("")
        lines.append(to_markdown_block(diagram, heading="Layers -> Modules"))
        lines.append("")
    for layer in layers:
        lines.extend([
            f"## {layer['name']}",
            "",
            f"- Files: {layer['file_count']}",
            f"- Modules: {', '.join(layer.get('modules') or ['none'])}",
            "",
        ])
        for file in layer.get("files", [])[:60]:
            lines.append(f"- {_file_ref(file)}")
        lines.append("")
    return "\n".join(lines)

def _render_call_graph_doc(call_graph: dict) -> str:
    lines = [
        "# Call Graph",
        "",
        "Edges are deterministic or heuristic. Review `confidence` before using a relationship as proof.",
        "",
    ]
    graph_nodes, graph_edges = _call_graph_file_graph(call_graph)
    if graph_nodes:
        diagram = render_flowchart(graph_nodes, graph_edges, direction="TB")
        lines.extend(["## Call Graph Diagram", ""])
        lines.append(to_image_markdown("diagrams/call-graph.svg", "Call graph diagram"))
        lines.append("")
        lines.append(to_markdown_block(diagram))
    lines.extend(["## Relationships", ""])
    for edge in call_graph.get("edges", [])[:300]:
        if edge.get("type") == "imports":
            lines.append(
                f"- imports: {_file_ref(edge['source_file'])} -> {_file_ref(edge['target_file'])} "
                f"(confidence {edge['confidence']})"
            )
        else:
            target = edge.get("target_symbol") or edge.get("target_file")
            line = edge.get("line")
            lines.append(
                f"- calls: {_file_ref(edge['source_file'], line)} -> `{target}` "
                f"(confidence {edge['confidence']})"
            )
    return "\n".join(lines)

def _render_module_doc(module: dict, inventory: dict) -> str:
    files_by_path = {item["path"]: item for item in inventory.get("files", [])}
    lines = [
        f"# Module: {module['name']}",
        "",
        module.get("summary") or "Module summary unavailable.",
        "",
        "## Structure",
        "",
        f"- Files: {module['file_count']}",
        f"- Layers: {', '.join(module.get('layers') or ['none'])}",
        f"- Entry points: {', '.join(_file_ref(path) for path in module.get('entry_points', [])) or 'none detected'}",
        f"- Tests: {', '.join(_file_ref(path) for path in module.get('tests', [])) or 'none detected'}",
        "",
        "## Files",
        "",
    ]
    for path in module.get("files", [])[:120]:
        file_entry = files_by_path.get(path, {})
        summary = file_entry.get("summary", "No summary available.")
        layers = ", ".join(file_entry.get("layers") or [])
        lines.append(f"- {_file_ref(path)}: {summary} Layers: {layers or 'none'}")
    if module.get("public_symbols"):
        lines.extend(["", "## Public Symbols", ""])
        for symbol in module["public_symbols"][:80]:
            lines.append(f"- `{symbol}`")
    return "\n".join(lines)

def _global_diagram_svgs(inventory: dict, call_graph: dict) -> dict[str, str]:
    """Standalone SVG companions for the architecture/layers/call-graph diagrams.

    Keyed by path relative to the docs root (``docs/``). Regenerated by both
    a full ``map``/``docs`` build and the diff-driven ``sync`` (F5) so the
    SVG artifacts stay in sync with the Mermaid blocks that link to them.
    """
    extras: dict[str, str] = {}
    module_nodes, module_edges = _module_dependency_graph(inventory.get("modules", []), call_graph)
    if module_nodes:
        extras["diagrams/architecture-modules.svg"] = render_flowchart_svg(
            module_nodes, module_edges, direction="TB"
        )["svg"]
    layer_graph_nodes, layer_edges = _layer_module_graph(inventory.get("layers", []))
    if layer_graph_nodes:
        extras["diagrams/layers.svg"] = render_flowchart_svg(
            layer_graph_nodes, layer_edges, direction="LR"
        )["svg"]
    call_graph_nodes, call_graph_edges = _call_graph_file_graph(call_graph)
    if call_graph_nodes:
        extras["diagrams/call-graph.svg"] = render_flowchart_svg(
            call_graph_nodes, call_graph_edges, direction="TB"
        )["svg"]
    return extras

def write_architecture_docs(cwd: str, output_dir: str = ".simplicio",
                            docs_dir: str | None = None) -> dict:
    abs_cwd = os.path.abspath(cwd or os.getcwd())
    abs_out = os.path.abspath(os.path.join(abs_cwd, output_dir))
    inventory_path = os.path.join(abs_out, "architecture-inventory.json")
    if not os.path.exists(inventory_path):
        write_mapping_artifacts(abs_cwd, output_dir=output_dir)

    inventory = _parse_json_safe(inventory_path)
    symbol_index = _parse_json_safe(os.path.join(abs_out, "symbol-index.json"))
    call_graph = _parse_json_safe(os.path.join(abs_out, "call-graph.json"))
    root = os.path.abspath(docs_dir or os.path.join(abs_out, "docs"))
    modules_dir = os.path.join(root, "modules")
    paths = []

    docs = {
        os.path.join(root, "architecture.md"): _render_architecture_overview(inventory, symbol_index, call_graph),
        os.path.join(root, "layers.md"): _render_layers_doc(inventory),
        os.path.join(root, "call-graph.md"): _render_call_graph_doc(call_graph),
    }
    module_index = ["# Modules", ""]
    for module in inventory.get("modules", []):
        module_file = os.path.join(modules_dir, f"{_slugify(module['name'])}.md")
        docs[module_file] = _render_module_doc(module, inventory)
        module_index.append(f"- [{module['name']}](modules/{_slugify(module['name'])}.md)")
    docs[os.path.join(root, "modules.md")] = "\n".join(module_index)

    for rel_path, content in _global_diagram_svgs(inventory, call_graph).items():
        docs[os.path.join(root, rel_path)] = content

    # Local import avoids a module-level cycle (cli imports mapper at import time).
    # `.mapper` is now a package (issue #159 split), so `cli` -- a sibling of
    # `simplicio_mapper/mapper/`, not of this submodule -- needs `..cli`.
    from ..cli import build_service_flowchart, render_service_flowchart_markdown
    flowchart_model = build_service_flowchart(abs_cwd)
    docs[os.path.join(root, "flowchart.md")] = render_service_flowchart_markdown(flowchart_model)

    for file, text in docs.items():
        _write_text_stable(file, text)
        paths.append(file)

    return {
        "docs_root": root,
        "paths": sorted(paths),
        "counts": {
            "files": len(paths),
            "modules": len(inventory.get("modules", []) or []),
        },
    }

def export_architecture_docs(cwd: str, target_dir: str, output_dir: str = ".simplicio") -> dict:
    if not target_dir:
        raise ValueError("--target is required for export-docs")
    docs = write_architecture_docs(cwd, output_dir=output_dir)
    source = docs["docs_root"]
    target = os.path.abspath(target_dir)
    os.makedirs(target, exist_ok=True)
    copied = []
    for current, _dirs, files in os.walk(source):
        for name in files:
            if not name.endswith((".md", ".svg")):
                continue
            src = os.path.join(current, name)
            rel = os.path.relpath(src, source)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = f"{dst}.tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            copied.append(dst)
    return {
        "target": target,
        "paths": sorted(copied),
        "counts": {"files": len(copied)},
    }
