"""``simplicio-mapper benchmark pipeline-threshold`` / ``shadow-rollout`` --
issue #279 Phase-0 local, per-machine calibration for the sync/async
mapping-pipeline dispatch threshold (ADR-011), plus (this PR, still ADR-011
scope) an opt-in shadow-rollout comparison mode (issue #279 plan step 15).

Dispatched before ``_parse_args`` in ``cli/__init__.py::main``, same shape
as ``contract``/``doctor``/``canonical`` (a sub-verb + flags, not the usual
``<command> <root>`` shape). Two verbs live here (``pipeline-threshold``,
``shadow-rollout``); kept as one module/dispatch point so a future
``benchmark`` verb (e.g. one measuring a different hot path) has a natural
home without touching the top-level ``commands`` tuple in ``_args.py``.

This CLI is purely additive and read/write-scoped to
``<root>/<out>/pipeline-calibration.json`` / ``<root>/<out>/pipeline-shadow.json``
-- it never changes ``emit.py``'s default dispatch behavior for anyone who
has not explicitly run it (see
``simplicio_mapper/mapper/pipeline_calibration.py``,
``simplicio_mapper/mapper/pipeline_shadow.py`` and
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
from ..mapper.pipeline_shadow import run_shadow_comparison, write_shadow_report

_USAGE = (
    "usage: simplicio-mapper benchmark pipeline-threshold [path] "
    "[--sizes N,N,N] [--runs N] [--out DIR] [--json]\n"
    "       simplicio-mapper benchmark shadow-rollout [path] "
    "[--out DIR] [--json]"
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


def _parse_shadow_args(argv: Sequence[str]) -> dict:
    opts: dict = {"root": ".", "out": ".simplicio", "json": False}
    positionals: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--out":
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


def _run_pipeline_threshold(argv: Sequence[str]) -> int:
    opts = _parse_benchmark_args(argv)
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


def _run_shadow_rollout(argv: Sequence[str]) -> int:
    opts = _parse_shadow_args(argv)
    payload = run_shadow_comparison(opts["root"], output_dir=opts["out"])
    path = write_shadow_report(opts["root"], payload, output_dir=opts["out"])
    if opts["json"]:
        print(json.dumps({"shadow_report_file": path, **payload}, ensure_ascii=False, sort_keys=True))
    else:
        print(f"pipeline shadow-rollout report written to {path}")
        print(
            f"configured_profile={payload['configured_profile']} "
            f"(returned to caller, never replaced) "
            f"candidate_profile={payload['candidate_profile']}"
        )
        print(
            f"configured_wall_s={payload['configured_wall_s']} "
            f"candidate_wall_s={payload['candidate_wall_s']} "
            f"faster_profile={payload['faster_profile']}"
        )
        print(f"equivalent_output={payload['equivalent_output']}")
        if not payload["equivalent_output"]:
            for artifact_key, diff_paths in payload["diffs"].items():
                print(f"  {artifact_key}: {len(diff_paths)} differing path(s), e.g. {diff_paths[:3]}")
    return 0


def run_benchmark_cli(argv: Sequence[str]) -> int:
    """Entry point for ``simplicio-mapper benchmark <verb> ...``."""
    if not argv:
        print(_USAGE, file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "pipeline-threshold":
        return _run_pipeline_threshold(rest)
    if verb == "shadow-rollout":
        return _run_shadow_rollout(rest)
    print(_USAGE, file=sys.stderr)
    return 2
