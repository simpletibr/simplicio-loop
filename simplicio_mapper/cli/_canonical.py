"""``simplicio-mapper canonical gc`` -- crash-safe canonical-map GC (issue #268).

Mirrors the ``run_snapshot_cli``/``run_contract_cli`` pattern: ``canonical``
takes a subcommand (today, only ``gc``) plus its own small flag set, so it is
dispatched in ``cli/__init__.py::main`` before the generic ``<command> <root>``
``_parse_args`` shape applies (same reason ``contract``/``doctor``/``snapshot``
are dispatched early there).

Dry-run is the default: mutation requires the explicit ``--apply`` opt-in
(issue #268 AC). See :mod:`simplicio_mapper.mapper.canonical_gc` for the
actual candidate classification and crash-safe removal logic -- this module
only parses argv, resolves ``--root``, and prints the resulting receipt.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence

from ..mapper.canonical_gc import run_canonical_gc


def _run_gc(opts: dict) -> int:
    root = os.path.abspath(opts["root"])
    receipt = run_canonical_gc(
        root,
        storage_root=opts.get("storage_root") or None,
        apply=opts.get("apply", False),
        ttl_seconds=opts.get("ttl_seconds"),
        promoted_grace_seconds=opts.get("grace_seconds"),
    )
    if opts.get("json"):
        print(json.dumps(receipt, sort_keys=True))
    else:
        candidates = receipt["candidates"]
        removed = receipt["removed"]
        preserved = receipt["preserved"]
        print(f"canonical gc mode={receipt['mode']} candidates={len(candidates)}")
        print(f"  removed={len(removed)} preserved={len(preserved)}")
        for entry in candidates:
            marker = "removed" if entry in removed else ("would-remove" if entry["action"] == "remove" else "keep")
            print(f"  [{marker}] {entry['location']} reason={entry['reason']}")
        if not opts.get("apply", False) and any(c["action"] == "remove" for c in candidates):
            print("  (dry-run: pass --apply to actually remove the entries above)")
    return 0


def run_canonical_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper canonical <subcommand> ...``."""
    if not argv:
        print("usage: simplicio-mapper canonical gc <root> [options]", file=sys.stderr)
        return 2
    sub = argv[0]
    rest = argv[1:]
    opts: dict = {
        "root": os.getcwd(),
        "json": False,
        "apply": False,
        "storage_root": "",
        "ttl_seconds": None,
        "grace_seconds": None,
    }
    positionals: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("-h", "--help"):
            print("usage: simplicio-mapper canonical gc [<root>] [--json] [--apply] [--storage-root DIR]")
            print("                                      [--ttl-seconds N] [--grace-seconds N]")
            return 0
        elif arg == "--json":
            opts["json"] = True
        elif arg == "--apply":
            opts["apply"] = True
        elif arg == "--storage-root":
            i += 1
            opts["storage_root"] = rest[i]
        elif arg == "--ttl-seconds":
            i += 1
            opts["ttl_seconds"] = float(rest[i])
        elif arg == "--grace-seconds":
            i += 1
            opts["grace_seconds"] = float(rest[i])
        elif arg.startswith("-"):
            print(f"unknown canonical option: {arg}", file=sys.stderr)
            return 2
        else:
            positionals.append(arg)
        i += 1
    if positionals:
        opts["root"] = positionals[0]

    if sub == "gc":
        return _run_gc(opts)
    print(f"unknown canonical subcommand: {sub}", file=sys.stderr)
    return 2


__all__ = ["run_canonical_cli"]
