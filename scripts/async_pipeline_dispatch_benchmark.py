#!/usr/bin/env python3
"""Crossover + dispatch-active benchmark for the size-based sync/async
pipeline dispatch (issue #235 follow-up, ADR-009 plan step 10's honest
after-benchmark showed small/medium trees regressed under the
unconditionally-async pipeline; this script is the evidence for the
dispatch threshold added in ``simplicio_mapper.mapper.emit.build_artifacts``).

Two things are measured here, both against the CURRENT revision (dispatch
active in production code):

1. **Crossover table** -- at each synthetic tree size, the plain
   synchronous pipeline (``_build_artifacts_sync``) and the bounded-
   concurrency async pipeline (``async_pipeline.build_artifacts_async``)
   are forced explicitly (bypassing the dispatcher) via
   ``SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES``, so the two are compared
   like-for-like on the same revision (both already include PR #255's
   O(n^2) import-resolution fix, unlike the historical before/after tables
   which compare across revisions). This is the *evidence* for where the
   dispatch threshold should sit.
2. **Dispatch-active table** -- the real, unmodified ``build_artifacts()``
   entry point (dispatcher wired in, default threshold) measured at the
   same three sizes as the historical before/after benchmarks (small=4,
   medium=200, large=1500 requested file counts), directly comparable to
   ``docs/async-pipeline-baseline-benchmark.md`` (before) and
   ``docs/async-pipeline-after-benchmark.md`` (after, unconditionally
   async) to confirm the small/medium regression is fixed and large still
   benefits.

Usage:
    python3 scripts/async_pipeline_dispatch_benchmark.py [--write] [--runs N]
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import os  # noqa: E402

from async_pipeline_after_benchmark import (  # noqa: E402
    _copy_real_fixture,
    _materialize_synthetic_tree,
)

from simplicio_mapper.mapper import build_artifacts  # noqa: E402

SCHEMA = "simplicio.async-pipeline-dispatch-benchmark/v1"
MD_DOC_PATH = ROOT / "docs" / "async-pipeline-dispatch-benchmark.md"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "async-pipeline-dispatch-benchmark.json"
BASELINE_JSON_PATH = ROOT / "docs" / "evidence" / "async-pipeline-baseline-benchmark.json"
AFTER_JSON_PATH = ROOT / "docs" / "evidence" / "async-pipeline-after-benchmark.json"

SEED = 20260717
ENV_THRESHOLD = "SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES"

CROSSOVER_SIZES = [50, 100, 400, 800, 1200, 1650]

DISPATCH_SIZES: list[tuple[str, int, bool]] = [
    ("small", 0, True),
    ("medium", 200, False),
    ("large", 1500, False),
]


@dataclass
class Times:
    values: list[float]

    @property
    def median(self) -> float:
        return statistics.median(self.values)


def _make_tree(tmp_path: Path, file_count: int) -> tuple[Path, int]:
    source_dir = tmp_path / "source"
    written = _materialize_synthetic_tree(source_dir, file_count)
    return source_dir, written


def _run_forced(mode: str, source_dir: Path, output_dir: Path) -> float:
    os.environ[ENV_THRESHOLD] = "999999999" if mode == "sync" else "1"
    try:
        start = time.perf_counter()
        build_artifacts(str(source_dir), meta={}, incremental=False, output_dir=str(output_dir))
        return time.perf_counter() - start
    finally:
        os.environ.pop(ENV_THRESHOLD, None)


def _crossover_row(file_count: int, runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dispatch-crossover-") as tmp:
        source_dir, written = _make_tree(Path(tmp), file_count)
        sync_times = Times([])
        async_times = Times([])
        for i in range(runs):
            out = source_dir / f".sync-{i}"
            sync_times.values.append(_run_forced("sync", source_dir, out))
            shutil.rmtree(out, ignore_errors=True)
        for i in range(runs):
            out = source_dir / f".async-{i}"
            async_times.values.append(_run_forced("async", source_dir, out))
            shutil.rmtree(out, ignore_errors=True)
        return {
            "requested_file_count": file_count,
            "actual_file_count": written,
            "sync_wall_median_s": round(sync_times.median, 4),
            "async_wall_median_s": round(async_times.median, 4),
            "sync_faster": sync_times.median < async_times.median,
            "ratio_sync_over_async": round(sync_times.median / async_times.median, 3)
            if async_times.median > 0
            else float("nan"),
        }


def _dispatch_row(name: str, file_count: int, use_real_fixture: bool, runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dispatch-active-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        if use_real_fixture:
            written = _copy_real_fixture(source_dir)
        else:
            written = _materialize_synthetic_tree(source_dir, file_count)

        cold_times = []
        warm_times = []
        for i in range(runs):
            out = source_dir / f".simplicio-cold-{i}"
            start = time.perf_counter()
            build_artifacts(str(source_dir), meta={}, incremental=False, output_dir=str(out))
            cold_times.append(time.perf_counter() - start)

            start = time.perf_counter()
            build_artifacts(str(source_dir), meta={}, incremental=False, output_dir=str(out))
            warm_times.append(time.perf_counter() - start)

        cold_median = statistics.median(cold_times)
        warm_median = statistics.median(warm_times)
        return {
            "size": name,
            "file_count": written,
            "cold_wall_median_s": round(cold_median, 4),
            "warm_wall_median_s": round(warm_median, 4),
            "cold_files_per_sec": round(written / cold_median, 2) if cold_median > 0 else 0.0,
        }


def _render_markdown(
    crossover: list[dict[str, Any]],
    dispatch: list[dict[str, Any]],
    threshold: int,
    generated_at: str,
    python_version: str,
    baseline_by_size: dict[str, Any] | None,
    after_by_size: dict[str, Any] | None,
) -> str:
    lines = [
        "# Async pipeline dispatch -- crossover + confirmation benchmark (issue #235 follow-up)",
        "",
        f"Measured: {generated_at}. Python: `{python_version}`. Tool: "
        "`scripts/async_pipeline_dispatch_benchmark.py`. Both tables below "
        "are measured on the SAME current revision (dispatcher wired into "
        "`build_artifacts()`, PR #255's O(n^2) fix already present in both "
        "paths), so -- unlike the historical before/after tables, which "
        "compare across revisions -- this is a like-for-like sync-vs-async "
        "comparison.",
        "",
        "## Crossover table (forced sync vs. forced async, same revision)",
        "",
        "Each row forces the named path via "
        "`SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES` (bypassing the "
        "dispatcher) and measures cold wall time. This is the evidence used "
        f"to pick the shipped default threshold ({threshold} files).",
        "",
        "| Files (requested / actual) | Sync wall p50 (s) | Async wall p50 (s) | Sync faster? | sync/async ratio |",
        "|---:|---:|---:|---|---:|",
    ]
    for row in crossover:
        lines.append(
            f"| {row['requested_file_count']} / {row['actual_file_count']} | "
            f"{row['sync_wall_median_s']} | {row['async_wall_median_s']} | "
            f"{'yes' if row['sync_faster'] else 'no'} | {row['ratio_sync_over_async']} |"
        )

    lines.extend([
        "",
        "## Dispatch-active table (real `build_artifacts()`, default threshold)",
        "",
        "Same three sizes as the historical before/after benchmarks "
        "(`docs/async-pipeline-baseline-benchmark.md`, "
        "`docs/async-pipeline-after-benchmark.md`), now measured through "
        "the real, unmodified entry point with the dispatcher active.",
        "",
        "| Size | Files | Cold wall p50 (s) | Cold files/s | Warm wall p50 (s) |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in dispatch:
        lines.append(
            f"| {row['size']} | {row['file_count']} | {row['cold_wall_median_s']} | "
            f"{row['cold_files_per_sec']} | {row['warm_wall_median_s']} |"
        )

    if baseline_by_size and after_by_size:
        lines.extend([
            "",
            "## Three-way comparison (cold wall time): before (sync-only, "
            "pre-#235) vs. after (unconditionally-async, PR #260/#271) vs. "
            "dispatch (this change)",
            "",
            "| Size | Before (sync-only) | After (unconditional async) | Dispatch (this fix) | Dispatch vs. before | Dispatch vs. after |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for row in dispatch:
            before = baseline_by_size.get(row["size"])
            after = after_by_size.get(row["size"])
            if not before or not after:
                continue
            before_wall = before["cold"]["wall_median_s"]
            after_wall = after["cold"]["wall_median_s"]
            dispatch_wall = row["cold_wall_median_s"]
            vs_before = before_wall / dispatch_wall if dispatch_wall > 0 else float("nan")
            vs_after = after_wall / dispatch_wall if dispatch_wall > 0 else float("nan")
            lines.append(
                f"| {row['size']} | {before_wall} | {after_wall} | {dispatch_wall} | "
                f"{vs_before:.2f}x | {vs_after:.2f}x |"
            )
        lines.append("")
        lines.append(
            "Reading this table: \"Dispatch vs. before\" close to or above "
            "1.0x means the regression versus the original synchronous "
            "pipeline is fixed (small/medium should land here, since the "
            "dispatcher now routes them through the same synchronous code "
            "path as \"before\", modulo the unrelated O(n^2) fix which "
            "benefits both). \"Dispatch vs. after\" close to 1.0x for the "
            "large row confirms the async pipeline's real win is preserved "
            "once a tree is actually large enough to cross the threshold."
        )

    return "\n".join(lines) + "\n"


def _load_by_size(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {r["size"]: r for r in payload["results"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument(
        "--crossover-runs", type=int, default=None,
        help="Override run count for the (slower) crossover table only",
    )
    args = parser.parse_args()

    from simplicio_mapper.mapper.emit import _async_pipeline_min_files
    threshold = _async_pipeline_min_files()

    crossover_runs = args.crossover_runs if args.crossover_runs is not None else args.runs
    crossover = [_crossover_row(count, crossover_runs) for count in CROSSOVER_SIZES]
    dispatch = [
        _dispatch_row(name, count, use_real_fixture, args.runs)
        for name, count, use_real_fixture in DISPATCH_SIZES
    ]

    baseline_by_size = _load_by_size(BASELINE_JSON_PATH)
    after_by_size = _load_by_size(AFTER_JSON_PATH)

    generated_at = datetime.now(timezone.utc).isoformat()
    python_version = sys.version.split()[0]
    markdown = _render_markdown(
        crossover, dispatch, threshold, generated_at, python_version,
        baseline_by_size, after_by_size,
    )
    print(markdown)

    payload = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "python_version": python_version,
        "seed": SEED,
        "threshold": threshold,
        "crossover": crossover,
        "dispatch_active": dispatch,
    }

    if args.write:
        MD_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        MD_DOC_PATH.write_text(markdown, encoding="utf-8")
        JSON_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_DOC_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {MD_DOC_PATH}", file=sys.stderr)
        print(f"Wrote {JSON_DOC_PATH}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
