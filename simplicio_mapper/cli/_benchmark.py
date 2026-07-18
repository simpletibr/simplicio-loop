"""``simplicio-mapper benchmark pipeline-threshold`` -- issue #279 Phase-0
local, per-machine calibration for the sync/async mapping-pipeline dispatch
threshold (ADR-010).

Dispatched before ``_parse_args`` in ``cli/__init__.py::main``, same shape
as ``contract``/``doctor``/``canonical`` (a sub-verb + flags, not the usual
``<command> <root>`` shape). Currently a single verb (``pipeline-threshold``);
kept as its own module/dispatch point so a future ``benchmark`` verb (e.g.
one measuring a different hot path) has a natural home without touching the
top-level ``commands`` tuple in ``_args.py``.

This CLI is purely additive and read/write-scoped to
``<root>/<out>/pipeline-calibration.json`` -- it never changes
``emit.py``'s default dispatch behavior for anyone who has not explicitly
run it (see ``simplicio_mapper/mapper/pipeline_calibration.py`` and
``simplicio_mapper/mapper/emit.py::_async_pipeline_min_files``).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence

from ..mapper.pipeline_calibration import (
    DEFAULT_CALIBRATION_SIZES,
    run_calibration,
    write_calibration,
)

_USAGE = (
    "usage: simplicio-mapper benchmark pipeline-threshold [path] "
    "[--sizes N,N,N] [--runs N] [--out DIR] [--json]"
)


def _parse_benchmark_args(argv: Sequence[str]) -> dict:
    opts: dict = {
        "root": ".",
        "sizes": DEFAULT_CALIBRATION_SIZES,
        "runs": 1,
        "out": ".simplicio",
        "json": False,
    }
    positionals: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--sizes":
            i += 1
            try:
                raw = argv[i]
            except IndexError:
                print("--sizes requires a value", file=sys.stderr)
                sys.exit(2)
            try:
                opts["sizes"] = tuple(
                    sorted({int(part) for part in raw.split(",") if part.strip()})
                )
            except ValueError:
                print("--sizes must be a comma-separated list of integers", file=sys.stderr)
                sys.exit(2)
        elif arg == "--runs":
            i += 1
            try:
                opts["runs"] = max(1, int(argv[i]))
            except (IndexError, ValueError):
                print("--runs requires an integer value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--out":
            i += 1
            try:
                opts["out"] = argv[i]
            except IndexError:
                print("--out requires a value", file=sys.stderr)
                sys.exit(2)
        elif arg == "--json":
            opts["json"] = True
        elif not arg.startswith("-"):
            positionals.append(arg)
        else:
            print(f"unknown flag: {arg}", file=sys.stderr)
            sys.exit(2)
        i += 1
    if positionals:
        opts["root"] = positionals[0]
    return opts


def run_benchmark_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper benchmark <verb> ...``."""
    if not argv or argv[0] != "pipeline-threshold":
        print(_USAGE, file=sys.stderr)
        return 2
    opts = _parse_benchmark_args(argv[1:])
    payload = run_calibration(sizes=opts["sizes"], runs=opts["runs"])
    path = write_calibration(opts["root"], payload, output_dir=opts["out"])
    if opts["json"]:
        print(json.dumps({"calibration_file": path, **payload}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"pipeline-threshold calibration written to {path}")
        print(
            f"recommended_threshold={payload['recommended_threshold']} "
            f"(hardcoded default: {payload['hardcoded_default_threshold']}, "
            f"calibrated={payload['calibrated']})"
        )
        for row in payload["sizes_measured"]:
            print(
                f"  files={row['actual_file_count']} "
                f"sync={row['sync_wall_median_s']}s "
                f"async={row['async_wall_median_s']}s "
                f"async_faster={row['async_faster']}"
            )
    return 0
