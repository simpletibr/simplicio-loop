#!/usr/bin/env python3
"""Historical baseline benchmark for the synchronous mapping pipeline (issue #235).

This script is valid only on a revision where
``simplicio_mapper.mapper.build_artifacts`` executes the synchronous pipeline.
After the async adapter landed, invoking that public function measures the
current async pipeline instead. Publishing those results as a synchronous
"before" baseline would be false.

The guard below refuses to run on an async-adapter revision. To produce a
before/after report, run this script from a pre-async Git revision and compare
it with a separately recorded current-pipeline receipt. For the current
inventory-level sync/async comparison, use
``scripts/async_inventory_benchmark.py``.

Metrics captured per size, cold (empty cache) and warm (populated cache):

- wall time: median and p95 across repeated runs (``time.perf_counter``)
- CPU time: ``time.process_time()`` delta (single-process CPU seconds spent)
- peak RSS: sampled via a background thread at ~20ms resolution
- files/sec: files walked divided by median wall time
- cache proxy: warm/cold ratio; cache hit counts are not publicly exposed

Usage (on a pre-async revision only):
    python3 scripts/async_pipeline_baseline_benchmark.py [--write] [--runs N]

``--write`` writes the Markdown report to
``docs/async-pipeline-baseline-benchmark.md`` and the raw JSON to
``docs/evidence/async-pipeline-baseline-benchmark.json``. Without it, the
script only prints the report to stdout (dry run).
"""
from __future__ import annotations

import argparse
import inspect
import json
import shutil
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import build_artifacts  # noqa: E402

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a project dependency already
    psutil = None

SCHEMA = "simplicio.async-pipeline-baseline-benchmark/v1"
MD_DOC_PATH = ROOT / "docs" / "async-pipeline-baseline-benchmark.md"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "async-pipeline-baseline-benchmark.json"
FIXTURE_ROOT = ROOT / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"

SEED = 20260717

_MODULE_TEMPLATE = '''"""Synthetic module {index} for the async-pipeline baseline benchmark."""

from __future__ import annotations

import json
import os
from typing import Any

from .helpers_{group} import helper_{index}


class Service{index}:
    """Synthetic service class to exercise class/def regex parsing."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def process(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = helper_{index}(payload)
        except ValueError:
            result = {{}}
        return result


def build_service_{index}(config: dict[str, Any]) -> Service{index}:
    return Service{index}(config)
'''

_HELPER_TEMPLATE = '''"""Synthetic helper module for group {group}."""

from __future__ import annotations

from typing import Any


def helper_{index}(payload: dict[str, Any]) -> dict[str, Any]:
    return {{"echo": payload, "group": "{group}"}}
'''


@dataclass(frozen=True)
class SizeSpec:
    name: str
    file_count: int
    use_real_fixture: bool = False


SIZES: list[SizeSpec] = [
    SizeSpec(name="small", file_count=0, use_real_fixture=True),
    SizeSpec(name="medium", file_count=200),
    SizeSpec(name="large", file_count=1500),
]


@dataclass
class RunStats:
    wall_seconds: list[float]
    cpu_seconds: list[float]
    peak_rss_bytes: list[int]

    @property
    def wall_median(self) -> float:
        return statistics.median(self.wall_seconds)

    @property
    def wall_p95(self) -> float:
        if len(self.wall_seconds) == 1:
            return self.wall_seconds[0]
        quantiles = statistics.quantiles(self.wall_seconds, n=100, method="inclusive")
        return quantiles[94]

    @property
    def cpu_median(self) -> float:
        return statistics.median(self.cpu_seconds)

    @property
    def peak_rss_median(self) -> int:
        return int(statistics.median(self.peak_rss_bytes))


def _materialize_synthetic_tree(root: Path, file_count: int) -> int:
    """Write ``file_count`` synthetic python files (plus helper modules) under root.

    Returns the actual number of files written (files + helpers + package
    markers), so files/sec is computed against ground truth, not the request.
    """
    root.mkdir(parents=True, exist_ok=True)
    written = 0
    groups = max(1, file_count // 20)
    indices_by_group: dict[int, list[int]] = {group: [] for group in range(groups)}
    for index in range(file_count):
        indices_by_group[index % groups].append(index)

    for group in range(groups):
        pkg_dir = root / f"pkg_{group}"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
        written += 1
        helpers_source = "".join(
            _HELPER_TEMPLATE.format(group=group, index=i) for i in indices_by_group[group]
        )
        (pkg_dir / f"helpers_{group}.py").write_text(helpers_source, encoding="utf-8")
        written += 1

    for index in range(file_count):
        group = index % groups
        pkg_dir = root / f"pkg_{group}"
        module_path = pkg_dir / f"module_{index}.py"
        module_path.write_text(
            _MODULE_TEMPLATE.format(index=index, group=group), encoding="utf-8"
        )
        written += 1
    return written


def _copy_real_fixture(root: Path) -> int:
    shutil.copytree(FIXTURE_ROOT, root, dirs_exist_ok=True)
    return sum(1 for p in root.rglob("*") if p.is_file())


class _RssSampler:
    """Samples RSS of the current process on a background thread."""

    def __init__(self, interval_s: float = 0.02) -> None:
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._peak = 0
        self._thread: threading.Thread | None = None
        self._proc = psutil.Process() if psutil is not None else None

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._proc is not None:
                rss = self._proc.memory_info().rss
                if rss > self._peak:
                    self._peak = rss
            self._stop.wait(self._interval_s)

    def __enter__(self) -> _RssSampler:
        if self._proc is not None:
            self._peak = self._proc.memory_info().rss
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    @property
    def peak(self) -> int:
        return self._peak


def _run_once(source_dir: Path, output_dir: Path) -> tuple[float, float, int]:
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    with _RssSampler() as sampler:
        build_artifacts(str(source_dir), meta={}, incremental=False, output_dir=str(output_dir))
    wall = time.perf_counter() - wall_start
    cpu = time.process_time() - cpu_start
    return wall, cpu, sampler.peak


def _benchmark_size(spec: SizeSpec, runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="async-pipeline-baseline-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        output_dir_name = ".simplicio"
        if spec.use_real_fixture:
            file_count = _copy_real_fixture(source_dir)
        else:
            file_count = _materialize_synthetic_tree(source_dir, spec.file_count)

        cold_stats = RunStats(wall_seconds=[], cpu_seconds=[], peak_rss_bytes=[])
        warm_stats = RunStats(wall_seconds=[], cpu_seconds=[], peak_rss_bytes=[])

        for run_index in range(runs):
            # Fresh output dir (and thus empty disk cache) every iteration
            # for the cold measurement.
            output_dir = source_dir / f"{output_dir_name}-cold-{run_index}"
            wall, cpu, peak = _run_once(source_dir, output_dir)
            cold_stats.wall_seconds.append(wall)
            cold_stats.cpu_seconds.append(cpu)
            cold_stats.peak_rss_bytes.append(peak)

            # Re-run against the SAME output dir (populated cache from the
            # cold run above) to measure the warm/cache-hit path.
            wall, cpu, peak = _run_once(source_dir, output_dir)
            warm_stats.wall_seconds.append(wall)
            warm_stats.cpu_seconds.append(cpu)
            warm_stats.peak_rss_bytes.append(peak)

        speedup = (
            cold_stats.wall_median / warm_stats.wall_median
            if warm_stats.wall_median > 0
            else float("nan")
        )
        return {
            "size": spec.name,
            "file_count": file_count,
            "runs": runs,
            "cold": {
                "wall_median_s": round(cold_stats.wall_median, 4),
                "wall_p95_s": round(cold_stats.wall_p95, 4),
                "cpu_median_s": round(cold_stats.cpu_median, 4),
                "peak_rss_mb": round(cold_stats.peak_rss_median / (1024 * 1024), 2),
                "files_per_sec": round(file_count / cold_stats.wall_median, 2)
                if cold_stats.wall_median > 0
                else 0.0,
            },
            "warm": {
                "wall_median_s": round(warm_stats.wall_median, 4),
                "wall_p95_s": round(warm_stats.wall_p95, 4),
                "cpu_median_s": round(warm_stats.cpu_median, 4),
                "peak_rss_mb": round(warm_stats.peak_rss_median / (1024 * 1024), 2),
                "files_per_sec": round(file_count / warm_stats.wall_median, 2)
                if warm_stats.wall_median > 0
                else 0.0,
            },
            "warm_vs_cold_speedup_ratio": round(speedup, 2),
        }


def _render_markdown(results: list[dict[str, Any]], generated_at: str, python_version: str) -> str:
    lines = [
        "# Async mapping pipeline -- baseline benchmark (issue #235)",
        "",
        f"Measured: {generated_at} against the current *synchronous* "
        "`simplicio_mapper.mapper.build_artifacts` pipeline -- this is the "
        "**before** number for the `AsyncMappingPipeline` epic (issue #235, "
        "plan steps 1-2). No production code changed for this measurement.",
        "",
        f"Python: `{python_version}`. Tool: "
        "`scripts/async_pipeline_baseline_benchmark.py`. Cold = fresh empty "
        "disk cache; warm = same output dir re-run immediately after "
        "(disk-cache hit path).",
        "",
        "| Size | Files | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | Cold files/s | Warm wall p50/p95 (s) | Warm files/s | Warm/Cold speedup |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        cold = r["cold"]
        warm = r["warm"]
        lines.append(
            f"| {r['size']} | {r['file_count']} | "
            f"{cold['wall_median_s']} / {cold['wall_p95_s']} | "
            f"{cold['cpu_median_s']} | {cold['peak_rss_mb']} | "
            f"{cold['files_per_sec']} | "
            f"{warm['wall_median_s']} / {warm['wall_p95_s']} | "
            f"{warm['files_per_sec']} | {r['warm_vs_cold_speedup_ratio']}x |"
        )
    lines.extend(
        [
            "",
            "## Reading these numbers",
            "",
            "- **Cold** exercises the full sequential pipeline: `os.walk` "
            "discovery, per-file blocking `open()` + regex parse "
            "(`_cached_parse_file`), one `diskcache` miss+set per file, then "
            "a single-threaded write of 5 JSON artifacts.",
            "- **Warm** re-runs against the same `.simplicio/cache` dir, so "
            "every file should hit `FileProcessingCache.get_processed_file` "
            "instead of re-parsing -- the warm/cold ratio is the current "
            "cache's real speedup, which any async rewrite must not regress.",
            "- **files/s** is `file_count / wall_median`; this is the number "
            "a future `AsyncMappingPipeline` (bounded concurrency + "
            "`asyncio.to_thread` for the blocking reads) is expected to "
            "raise for medium/large trees, where I/O-wait dominates.",
            "- The **small** row uses the real committed "
            "`contracts/mapper-artifacts/v1/fixtures/python-minimal/source` "
            "fixture (4 files) so the numbers stay anchored to a real, "
            "reviewable input, not only synthetic data. Medium/large rows "
            "use deterministically generated synthetic Python packages "
            "(seed "
            f"`{SEED}`) so file counts are exact and reproducible without "
            "committing large trees to the repo.",
            "",
            "## Follow-up (not done here)",
            "",
            "This script only *measures* the current pipeline (issue #235 "
            "plan steps 1-2). See "
            "`.specs/architecture/ADR-009-async-mapping-pipeline.md` for the "
            "proposed `AsyncMappingPipeline` design and the remaining plan "
            "steps (3-10), tracked as follow-up work against issue #235.",
        ]
    )
    return "\n".join(lines) + "\n"



def _assert_historical_sync_baseline() -> None:
    """Reject mislabeled baseline runs after the async adapter is active."""
    source = inspect.getsource(build_artifacts)
    if "build_artifacts_async" in source:
        raise RuntimeError(
            "refusing to publish a synchronous baseline from the current async "
            "adapter; run this script from a pre-async Git revision and use "
            "scripts/async_inventory_benchmark.py for current comparisons"
        )
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true",
        help="Write docs/async-pipeline-baseline-benchmark.md and the JSON evidence file",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Number of cold+warm iterations per size (default: 3)",
    )
    args = parser.parse_args()

    _assert_historical_sync_baseline()

    if psutil is None:
        print("psutil not importable; RSS numbers will be 0. Install psutil to fix.", file=sys.stderr)

    results = [_benchmark_size(spec, args.runs) for spec in SIZES]

    generated_at = datetime.now(timezone.utc).isoformat()
    python_version = sys.version.split()[0]
    payload = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "python_version": python_version,
        "seed": SEED,
        "results": results,
    }

    markdown = _render_markdown(results, generated_at, python_version)
    print(markdown)

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
