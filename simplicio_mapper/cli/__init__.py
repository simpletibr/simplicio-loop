"""Command-line entry point for simplicio-mapper.

Mirrors ``bin/map.js``: generates or refreshes the machine-readable mapper
artifacts under ``.simplicio/``. Exposed as the ``simplicio-mapper`` and
``llm-project-mapper`` console scripts (see ``pyproject.toml``).

Issue #159 (god-file split): this module used to be a single ~2800-line
``cli.py`` file. It is now a package -- each subcommand family lives in its
own module below, and this ``__init__.py`` only re-exports the public
``main`` entrypoint (``simplicio_mapper.cli:main`` in ``pyproject.toml``
stays valid unchanged) and wires the top-level dispatch. Pure move-and-wire
refactor: no renamed public API, no behavior change -- see
``tests/python/test_cli_help_snapshot.py`` for the before/after `--help`
and representative-subcommand-output snapshot proving this.

Module map:
  _shared.py         - schema-id constants, HELP_TEXT, shared config sets.
  _args.py           - argv parsing (``_parse_args``) + safe JSON reads.
  _index_engine.py   - index state/signature/lock primitives, tagging,
                        geometry, confidence filtering, TOON emission.
  _endpoints.py      - client/server HTTP endpoint inventory extraction.
  _screens.py        - frontend route/screen inventory extraction.
  _flowchart.py      - screen->service->backend mermaid flowchart engine
                        (depends on _endpoints.py and _screens.py).
  _repo_commands.py  - flows/sync/history/diff/business/survey/drift/ask/
                        docs/export-docs subcommands (thin wrappers over
                        sibling modules: flows.py, history.py, business.py,
                        survey.py, drift.py, docsync.py, query.py).
  _background.py     - detached index refresh + the index/map/update
                        command bodies (depends on _index_engine.py).
  _status_engine.py  - scan/status/inspect/handoff/macro (depends on
                        _index_engine.py and _background.py).
  _benchmark.py      - ``benchmark pipeline-threshold`` local calibration
                        for the sync/async mapping-pipeline dispatch
                        threshold (issue #279 Phase-0, ADR-010).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

from ..mapper import write_architecture_docs
from ._args import _parse_args, _read_json_safe
from ._background import _run_background, _run_index, _watch
from ._endpoints import _run_endpoints
from ._flowchart import (
    _run_flowchart,
    build_service_flowchart,
    render_service_flowchart_markdown,
)
from ._index_engine import _emit_index_json, _index_result, _run_once
from ._repo_commands import (
    _run_ask,
    _run_business,
    _run_diff,
    _run_docs,
    _run_drift,
    _run_export_docs,
    _run_flows,
    _run_history,
    _run_survey,
    _run_sync,
    _run_visualize,
)
from ._screens import _run_screens
from ._status_engine import _run_handoff, _run_inspect, _run_macro, _run_scan, _run_status


def _run_delta(opts: dict) -> int:
    from ..incremental import run_incremental_scan

    root = os.path.abspath(opts["root"])
    meta = dict(_read_json_safe(os.path.join(root, ".starter-meta.json")))
    if opts.get("stack"):
        meta["stack"] = opts["stack"]
    if opts.get("product_name"):
        meta["product_name"] = opts["product_name"]
    payload = run_incremental_scan(
        root,
        out=opts["out"],
        meta=meta,
        full_rescan=opts.get("full_rescan", False),
        changed_paths=opts.get("changed_paths") or None,
    )
    if opts.get("json"):
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"delta mode={payload['mode']} events={len(payload['events'])} "
            f"revision={payload['scan_revision']} full_rescan={payload['full_rescan']}"
        )
    return 0


__all__ = [
    "main",
    # Re-exported for `simplicio_mapper/mapper.py`'s existing
    # `from .cli import build_service_flowchart, render_service_flowchart_markdown`
    # (write_architecture_docs) -- kept working unchanged by this split.
    "build_service_flowchart",
    "render_service_flowchart_markdown",
]


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `contract` takes a subcommand + a list of paths, not the usual
    # `<command> <root>` shape the rest of the CLI expects, so it is
    # dispatched before `_parse_args` (issue #157, mapper-artifacts contract).
    if argv and argv[0] == "contract":
        from ..contract import run_contract_cli

        return run_contract_cli(argv[1:])
    # `doctor --contracts` similarly takes flags/paths rather than the usual
    # `<command> <root>` shape (issue #164, ecosystem contract harness).
    if argv and argv[0] == "doctor":
        from ..ecosystem_contract import run_doctor_cli

        return run_doctor_cli(argv[1:])
    # `canonical build|status|verify|gc` takes a sub-verb + path, same shape
    # as `snapshot`/`contract`/`doctor` above -- dispatched before
    # `_parse_args` (issue #266, ADR-008 migration step 7: read-safe
    # canonical-map CLI surface; issue #268 added the `gc` verb, issue #267
    # added the `verify` verb, to the same dispatch).
    if argv and argv[0] == "canonical":
        from ._canonical import run_canonical_cli

        return run_canonical_cli(argv[1:])
    # `benchmark pipeline-threshold [path]` takes a sub-verb + flags, same
    # shape as `canonical`/`contract`/`doctor` above -- dispatched before
    # `_parse_args` (issue #279 Phase-0: local per-machine sync/async
    # dispatch-threshold calibration, ADR-011).
    if argv and argv[0] == "benchmark":
        from ._benchmark import run_benchmark_cli

        return run_benchmark_cli(argv[1:])
    # `version` exposes issue #280's machine-readable release identity.
    if argv and argv[0] == "version":
        from ..release_manifest import run_version_cli

        return run_version_cli(argv[1:])
    # `release-manifest` similarly takes flags rather than the usual
    # `<command> <root>` shape (issue #280, Phase-0 local release manifest).
    if argv and argv[0] == "release-manifest":
        from ..release_manifest import run_release_manifest_cli

        return run_release_manifest_cli(argv[1:])
    # `schema-compat` similarly takes flags rather than the usual
    # `<command> <root>` shape (issue #280, compatible/breaking schema-change
    # classifier for project-map/precedent-index/context-snapshot/overlays).
    if argv and argv[0] == "schema-compat":
        from ..schema_compat import run_schema_compat_cli

        return run_schema_compat_cli(argv[1:])
    # `prototype-context <root> --type <type> --arg <target>` similarly takes
    # a root + flags rather than plain `<command> <root>` (issue #286
    # Phase-0: bounded context pack for Prototype-First -- see
    # `simplicio_mapper/prototype_context.py` module docstring for scope).
    if argv and argv[0] == "prototype-context":
        from ..prototype_context import run_prototype_context_cli

        return run_prototype_context_cli(argv[1:])
    opts = _parse_args(argv)
    if opts["background"] and opts["command"] in ("index", "map", "update"):
        return _run_background(opts)
    if opts["docs_only"] and opts["command"] in ("index", "map", "update"):
        return _run_docs(opts)
    if opts["command"] == "macro":
        return _run_macro(opts)
    if opts["command"] == "scan":
        return _run_scan(opts)
    if opts["command"] == "status":
        return _run_status(opts)
    if opts["command"] == "inspect":
        return _run_inspect(opts)
    if opts["command"] == "handoff":
        return _run_handoff(opts)
    if opts["command"] == "orient":
        from ..orient import run_orientation_cli

        return run_orientation_cli(opts)
    if opts["command"] == "endpoints":
        return _run_endpoints(opts)
    if opts["command"] == "screens":
        return _run_screens(opts)
    if opts["command"] == "flowchart":
        return _run_flowchart(opts)
    if opts["command"] == "flows":
        return _run_flows(opts)
    if opts["command"] == "visualize":
        return _run_visualize(opts)
    if opts["command"] == "preview":
        from ..visualization import run_preview_cli

        return run_preview_cli(opts)
    if opts["command"] == "sync":
        return _run_sync(opts)
    if opts["command"] == "history":
        return _run_history(opts)
    if opts["command"] == "diff":
        return _run_diff(opts)
    if opts["command"] == "ask":
        return _run_ask(opts)
    if opts["command"] == "business":
        return _run_business(opts)
    if opts["command"] == "survey":
        return _run_survey(opts)
    if opts["command"] == "drift":
        return _run_drift(opts)
    if opts["command"] == "delta":
        return _run_delta(opts)
    if opts["command"] == "snapshot":
        from ._snapshot import run_snapshot_cli

        # argv[0] is "snapshot"; pass the rest to the sub-command parser.
        return run_snapshot_cli((sys.argv[1:] if argv is None else argv)[1:])
    if opts["command"] == "docs":
        return _run_docs(opts)
    if opts["command"] == "export-docs":
        return _run_export_docs(opts)
    if opts["command"] == "index":
        try:
            return _run_index(opts)
        except Exception as error:  # noqa: BLE001 - CLI boundary must report a stable failure
            payload = _index_result(
                os.path.abspath(opts["root"]),
                opts["out"],
                status="failed",
                error=str(error),
            )
            if opts["json"] or opts.get("for_llm"):
                _emit_index_json(opts, payload)
            else:
                print(f"index failed: {error}", file=sys.stderr)
            return 1
    _run_once(opts)
    if opts["docs"]:
        write_architecture_docs(opts["root"], output_dir=opts["out"])
    if opts["watch"]:
        _watch(opts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
