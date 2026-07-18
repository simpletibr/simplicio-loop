"""``simplicio-mapper canonical verify`` -- independent parity proof (issue #267).

Sub-commands: this module currently implements only ``verify`` (ADR-008
step 7's ``canonical status/build/verify/gc`` command family). ``build``
tracks issue #266 and is implemented separately; ``status``/``gc`` are not
yet implemented. This module talks to the canonical-map model layer
(``simplicio_mapper.mapper.canonical_builder``/``canonical_overlay``/
``effective_view``) directly rather than depending on any other
``canonical`` CLI verb.

Takes a subcommand + a root path/flags shape, like ``snapshot``/``contract``
above it, so it is dispatched in ``cli/__init__.py::main`` before
``_parse_args`` (which does not know this shape).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from ..mapper.canonical_verify import DEFAULT_FILE_LIMIT, verify_canonical_parity


def _print_human_receipt(receipt: dict) -> None:
    print(
        f"canonical verify: {receipt['result']} "
        f"(method={receipt['comparison_method']})"
    )
    counts = receipt.get("counts") or {}
    if counts:
        print(
            "  canonical_files={canonical_files} effective_files={effective_files} "
            "remap_files={remap_files} matched={matched} mismatches={mismatches}".format(
                canonical_files=counts.get("canonical_files", 0),
                effective_files=counts.get("effective_files", 0),
                remap_files=counts.get("remap_files", 0),
                matched=counts.get("matched", 0),
                mismatches=counts.get("mismatches", 0),
            )
        )
    print(f"  duration_seconds={receipt.get('duration_seconds')}")
    if receipt.get("digest"):
        print(f"  digest={receipt['digest'][:24]}...")
    if receipt.get("failure_reason"):
        print(f"  failure_reason={receipt['failure_reason']}")
    for item in (receipt.get("mismatches") or [])[:20]:
        print(f"    - {item['reason']}: {item['path']}")


def _run_verify(argv: Sequence[str]) -> int:
    root = "."
    storage_root: str | None = None
    config_fingerprint = "default"
    file_limit = DEFAULT_FILE_LIMIT
    as_json = False

    positionals: list[str] = []
    i = 0
    items = list(argv)
    while i < len(items):
        arg = items[i]
        if arg in ("-h", "--help"):
            print(
                "usage: simplicio-mapper canonical verify <root> [--json] "
                "[--storage-root <dir>] [--config-fingerprint <value>] [--limit <n>]"
            )
            return 0
        elif arg == "--json":
            as_json = True
        elif arg == "--storage-root":
            i += 1
            storage_root = items[i]
        elif arg == "--config-fingerprint":
            i += 1
            config_fingerprint = items[i]
        elif arg == "--limit":
            i += 1
            try:
                file_limit = int(items[i])
            except (ValueError, IndexError):
                print("--limit requires an integer", file=sys.stderr)
                return 2
        elif arg.startswith("-"):
            print(f"unknown canonical verify option: {arg}", file=sys.stderr)
            return 2
        else:
            positionals.append(arg)
        i += 1

    if positionals:
        root = positionals[0]

    receipt = verify_canonical_parity(
        root,
        storage_root=storage_root,
        config_fingerprint=config_fingerprint,
        file_limit=file_limit,
    )

    if as_json:
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    else:
        _print_human_receipt(receipt)

    return 0 if receipt["result"] == "match" else 1


def run_canonical_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper canonical <subcommand> ...``."""
    if not argv:
        print("usage: simplicio-mapper canonical verify <root> [options]", file=sys.stderr)
        return 2
    sub = argv[0]
    rest = argv[1:]
    if sub == "verify":
        return _run_verify(rest)
    print(f"unknown canonical subcommand: {sub!r} (supported: verify)", file=sys.stderr)
    return 2


__all__ = ["run_canonical_cli"]
