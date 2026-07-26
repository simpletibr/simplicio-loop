"""``simplicio-mapper snapshot`` — emit a ContextSnapshot (issue #208, Step 1).

Builds a ``simplicio.context-snapshot/v1`` envelope from the canonical mapper
artifacts under ``.simplicio/`` and writes it to ``.simplicio/context-snapshot.json``.

Sub-commands:

* ``build``    — assemble + write the snapshot (default).
* ``validate`` — check a snapshot file against the shipped v1 schema.
* ``summary``  — print a compact, terminal-first summary (node/edge counts,
                 snapshot_id, revision, omissions).

This is the observer half of issue #208: it observes and reports, it never
plans or executes changes.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

from .. import __version__
from ..context_contract import REPORT_SCHEMA, validate_context_file
from ..context_dag import update_context_dag
from ..context_snapshot import ARTIFACT_VERSION, build_context_graph, build_context_snapshot
from ..fast_backend import resolve_backend, write_backend_receipt
from ..mapper import (
    _parse_json_safe,
    write_mapping_artifacts,
)


def _load_json_safe(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    return _parse_json_safe(path)


def _git_revision(root: str) -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _build_snapshot(
    root: str,
    out: str,
    *,
    refresh: bool,
    task_query: str,
    selection_policy: str,
    budget_tokens: int,
    backend: str = "auto",
    fast_manifest: str = "",
) -> dict:
    abs_root = os.path.abspath(root)
    abs_out = os.path.abspath(os.path.join(abs_root, out))
    project_map_path = os.path.join(abs_out, "project-map.json")
    if refresh or not os.path.isfile(project_map_path):
        write_mapping_artifacts(abs_root, output_dir=out)
    local_artifacts = {
        "project_map": _load_json_safe(project_map_path),
        "symbol_index": _load_json_safe(os.path.join(abs_out, "symbol-index.json")),
        "call_graph": _load_json_safe(os.path.join(abs_out, "call-graph.json")),
        "architecture_inventory": _load_json_safe(os.path.join(abs_out, "architecture-inventory.json")),
    }
    resolution = resolve_backend(
        root=abs_root,
        local_artifacts=local_artifacts,
        mode=backend,
        manifest_path=fast_manifest,
    )
    write_backend_receipt(abs_root, out, resolution.receipt)
    project_map = resolution.artifacts["project_map"]
    symbol_index = resolution.artifacts["symbol_index"]
    call_graph = resolution.artifacts["call_graph"]
    architecture_inventory = resolution.artifacts["architecture_inventory"]
    revision = _git_revision(abs_root) or project_map.get("generated_at", "")
    return build_context_snapshot(
        abs_root,
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        architecture_inventory=architecture_inventory,
        revision=revision,
        task_query=task_query,
        selection_policy=selection_policy,
        budget_tokens=budget_tokens,
    )


def _run_build(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    snapshot = _build_snapshot(
        root,
        out,
        refresh=opts.get("full_rescan", False),
        task_query=opts.get("goal", ""),
        selection_policy=opts.get("selection_policy", "deterministic"),
        budget_tokens=int(opts.get("token_budget", 0)),
        backend=str(opts.get("backend", "auto")),
        fast_manifest=str(opts.get("fast_manifest", "")),
    )
    dest = os.path.join(os.path.abspath(os.path.join(root, out)), "context-snapshot.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, sort_keys=True, indent=2)
        handle.write("\n")
    if opts.get("json") or opts.get("for_llm"):
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
    else:
        _print_summary(snapshot, dest)
    return 0


def _run_dag_build(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    out = opts["out"]
    abs_out = os.path.join(root, out)
    if opts.get("full_rescan", False) or not os.path.isfile(os.path.join(abs_out, "project-map.json")):
        write_mapping_artifacts(root, output_dir=out)
    project_map = _load_json_safe(os.path.join(abs_out, "project-map.json"))
    symbol_index = _load_json_safe(os.path.join(abs_out, "symbol-index.json"))
    call_graph = _load_json_safe(os.path.join(abs_out, "call-graph.json"))
    architecture_inventory = _load_json_safe(os.path.join(abs_out, "architecture-inventory.json"))
    graph = build_context_graph(
        project_map=project_map,
        symbol_index=symbol_index,
        call_graph=call_graph,
        architecture_inventory=architecture_inventory,
    )
    revision = _git_revision(root) or project_map.get("generated_at", "")
    result = update_context_dag(
        root,
        graph.to_dict(),
        out=out,
        build_config_hash=opts.get("build_config_hash", ""),
        producer={"name": "simplicio-mapper", "version": __version__, "artifact_version": ARTIFACT_VERSION},
        revision=revision,
    )
    diff = result["diff"]
    counters = diff["counters"]
    if opts.get("json"):
        print(json.dumps(result["journal_entry"], ensure_ascii=False, sort_keys=True))
    else:
        print(f"dag {result['dag']['dag_id'][:16]}… revision={revision[:12] or '-'}")
        if diff["full_invalidation"]:
            print(f"  full_invalidation=true reason={diff['reason']}")
        else:
            print(
                f"  invalidated={counters.get('invalidated')} added={counters.get('added')} "
                f"removed={counters.get('removed')} of total_nodes={counters.get('total_nodes')}"
            )
        print(f"  -> wrote {os.path.relpath(os.path.join(abs_out, 'context-dag.json'))}")
        print(f"  -> appended {os.path.relpath(os.path.join(abs_out, 'context-dag-journal.jsonl'))}")
    return 0


def _run_validate(opts: dict) -> int:
    paths = opts.get("validate_paths") or []
    if not paths:
        print("usage: simplicio-mapper snapshot validate <path> [<path> ...]", file=sys.stderr)
        return 2
    failed = False
    reports = []
    for path in paths:
        try:
            report = validate_context_file(path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            report = {
                "schema": REPORT_SCHEMA,
                "valid": False,
                "reason_codes": [{"code": "SNAPSHOT_READ_ERROR", "path": "$", "message": str(error)}],
                "snapshot_id": "",
            }
        report["path"] = path
        reports.append(report)
        if not report["valid"]:
            failed = True
        if not opts.get("json"):
            if report["valid"]:
                print(f"[ok]   {path} ({report['schema']})")
            else:
                print(f"[fail] {path} ({report['schema']}):")
                for reason in report["reason_codes"]:
                    print(f"  - {reason['code']}: {reason['message']}")
    if opts.get("json"):
        print(json.dumps({"schema": REPORT_SCHEMA, "valid": not failed, "reports": reports}, sort_keys=True))
    return 1 if failed else 0


def _print_summary(snapshot: dict, dest: str) -> None:
    counts = snapshot.get("graph", {}).get("counts", {})
    print(f"snapshot {snapshot['snapshot_id'][:16]}… schema={snapshot['schema']}")
    print(f"  repo={snapshot['repository_id']} revision={snapshot['revision'][:12] or '-'}")
    print(
        f"  nodes={counts.get('nodes')} ({counts.get('micro')} micro / {counts.get('meso')} meso / {counts.get('macro')} macro) edges={counts.get('edges')}"
    )
    omissions = snapshot.get("task", {}).get("omissions", [])
    if omissions:
        print(f"  needs_broader_context=true omissions={','.join(omissions)}")
    print(f"  -> wrote {os.path.relpath(dest)}")


def _run_summary(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    dest = os.path.join(os.path.abspath(os.path.join(root, opts["out"])), "context-snapshot.json")
    if not os.path.isfile(dest):
        print(f"no snapshot at {dest}; run `simplicio-mapper snapshot build` first", file=sys.stderr)
        return 1
    with open(dest, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    _print_summary(snapshot, dest)
    return 0


def run_snapshot_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper snapshot <subcommand> ...``."""
    if not argv:
        return _run_build({"root": os.getcwd(), "out": ".simplicio", "json": False})
    sub = argv[0]
    rest = argv[1:]
    base = {
        "root": os.getcwd(),
        "out": ".simplicio",
        "json": False,
        "for_llm": "",
        "goal": "",
        "selection_policy": "deterministic",
        "token_budget": 0,
        "full_rescan": False,
        "build_config_hash": "",
        "backend": "auto",
        "fast_manifest": "",
    }
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            print("usage: simplicio-mapper snapshot [build|validate|summary|dag] [options] [paths]")
            return 0
        elif arg == "--root":
            i += 1
            base["root"] = rest[i]
        elif arg == "--out":
            i += 1
            base["out"] = rest[i]
        elif arg == "--json":
            base["json"] = True
        elif arg == "--for-llm":
            i += 1
            base["for_llm"] = rest[i]
        elif arg == "--goal":
            i += 1
            base["goal"] = rest[i]
        elif arg == "--selection-policy":
            i += 1
            base["selection_policy"] = rest[i]
        elif arg == "--token-budget":
            i += 1
            base["token_budget"] = int(rest[i])
        elif arg == "--refresh":
            base["full_rescan"] = True
        elif arg == "--build-config-hash":
            i += 1
            base["build_config_hash"] = rest[i]
        elif arg == "--backend":
            i += 1
            base["backend"] = rest[i]
        elif arg == "--fast-manifest":
            i += 1
            base["fast_manifest"] = rest[i]
        elif arg.startswith("-"):
            print(f"unknown snapshot option: {arg}", file=sys.stderr)
            return 2
        else:
            break
        i += 1
    if sub == "validate":
        base["validate_paths"] = rest[i:]
        return _run_validate(base)
    if sub == "summary":
        return _run_summary(base)
    if sub == "dag":
        return _run_dag_build(base)
    # default / "build"
    return _run_build(base)


__all__ = ["run_snapshot_cli"]
