#!/usr/bin/env python3
"""After benchmark for the async mapping pipeline (issue #235, ADR-009 plan
step 10).

Measures the CURRENT ``simplicio_mapper.mapper.build_artifacts`` -- which is
now a thin ``asyncio.run(build_artifacts_async(...))`` adapter over the
bounded-concurrency ``AsyncMappingPipeline`` (ADR-009 plan steps 4-8, PR
#260) -- using the *exact same* methodology, sizes, and synthetic-tree
generator (same seed) as
``scripts/async_pipeline_baseline_benchmark.py``'s historical "before"
measurement, so the two reports are directly comparable.

Honest framing (do not skip this when reading the numbers): between the
"before" measurement and this "after" measurement, TWO changes landed, not
one:

1. The async pipeline itself (this ADR's subject).
2. PR #255's fix for the O(n^2) ``_candidate_import_targets`` fallback scan
   in ``graph.py`` -- a purely algorithmic fix, unrelated to concurrency,
   that ADR-009's own baseline PR identified as the actual dominant cost at
   scale (93s of a 120s profiled run on the 1650-file tree) and explicitly
   deferred as a separate follow-up.

``build_artifacts()`` today reflects BOTH fixes landed, because there is no
way to invoke "async pipeline, without the O(n^2) fix" or vice versa on the
current revision -- they are both already merged to the same function. This
script cannot and does not attempt to isolate the async pipeline's own
marginal contribution from the O(n^2) fix's contribution; it reports the
combined, real, current behavior of the production entry point, and this
docstring exists specifically so nobody reads the resulting large speedup
number as "the async pipeline alone is Nx faster" -- it is not, and ADR-009
was honest about this risk in its own "Negativas" section.

Usage:
    python3 scripts/async_pipeline_after_benchmark.py [--write] [--runs N]
"""
from __future__ import annotations

import argparse
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

SCHEMA = "simplicio.async-pipeline-after-benchmark/v1"
MD_DOC_PATH = ROOT / "docs" / "async-pipeline-after-benchmark.md"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "async-pipeline-after-benchmark.json"
BASELINE_JSON_PATH = ROOT / "docs" / "evidence" / "async-pipeline-baseline-benchmark.json"
FIXTURE_ROOT = ROOT / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"

SEED = 20260717

_MODULE_TEMPLATE = '''"""Synthetic module {index} for the async-pipeline after benchmark."""

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
    with tempfile.TemporaryDirectory(prefix="async-pipeline-after-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        output_dir_name = ".simplicio-loop"
        if spec.use_real_fixture:
            file_count = _copy_real_fixture(source_dir)
        else:
            file_count = _materialize_synthetic_tree(source_dir, spec.file_count)

        cold_stats = RunStats(wall_seconds=[], cpu_seconds=[], peak_rss_bytes=[])
        warm_stats = RunStats(wall_seconds=[], cpu_seconds=[], peak_rss_bytes=[])

        for run_index in range(runs):
            output_dir = source_dir / f"{output_dir_name}-cold-{run_index}"
            wall, cpu, peak = _run_once(source_dir, output_dir)
            cold_stats.wall_seconds.append(wall)
            cold_stats.cpu_seconds.append(cpu)
            cold_stats.peak_rss_bytes.append(peak)

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


def _load_baseline() -> dict[str, Any] | None:
    if not BASELINE_JSON_PATH.exists():
        return None
    payload = json.loads(BASELINE_JSON_PATH.read_text(encoding="utf-8"))
    return {r["size"]: r for r in payload["results"]}


def _render_markdown(
    results: list[dict[str, Any]],
    generated_at: str,
    python_version: str,
    baseline_by_size: dict[str, Any] | None,
) -> str:
    lines = [
        "# Async mapping pipeline -- after benchmark (issue #235, ADR-009 plan step 10)",
        "",
        f"Measured: {generated_at} against the CURRENT "
        "`simplicio_mapper.mapper.build_artifacts` -- now a thin "
        "`asyncio.run(build_artifacts_async(...))` adapter over the bounded-"
        "concurrency `AsyncMappingPipeline` (ADR-009 plan steps 4-8, PR #260). "
        "This is the **after** number for issue #235; compare against "
        "`docs/async-pipeline-baseline-benchmark.md` (the **before** number, "
        "measured on the pre-async, pre-O(n^2)-fix revision).",
        "",
        "**Read this before the table**: two changes landed between before "
        "and after, not one -- this async pipeline AND PR #255's unrelated "
        "fix for the O(n^2) `_candidate_import_targets` fallback scan in "
        "`graph.py` (ADR-009's own profiling identified that quadratic scan, "
        "not blocking I/O, as the dominant cost at scale: 93s of a 120s "
        "profiled run on the 1650-file tree). Both fixes are already merged "
        "into the same `build_artifacts()` on this revision, so this report "
        "cannot and does not isolate the async pipeline's own marginal "
        "contribution from the O(n^2) fix's contribution -- it reports the "
        "combined, real, current behavior of the production entry point "
        "every `index`/`map`/`scan` command calls.",
        "",
        f"Python: `{python_version}`. Tool: "
        "`scripts/async_pipeline_after_benchmark.py`. Cold = fresh empty "
        "disk cache; warm = same output dir re-run immediately after "
        "(disk-cache hit path). Same synthetic-tree generator, seed, and "
        "sizes as the baseline benchmark, so rows are directly comparable.",
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

    lines.extend(["", "## Before vs. after (cold wall time)", ""])
    if baseline_by_size:
        lines.append("| Size | Before cold wall p50 (s) | After cold wall p50 (s) | Speedup |")
        lines.append("|---|---:|---:|---:|")
        for r in results:
            before = baseline_by_size.get(r["size"])
            if not before:
                continue
            before_wall = before["cold"]["wall_median_s"]
            after_wall = r["cold"]["wall_median_s"]
            speedup = before_wall / after_wall if after_wall > 0 else float("nan")
            lines.append(
                f"| {r['size']} | {before_wall} | {after_wall} | {speedup:.2f}x |"
            )
        lines.append("")
        lines.append(
            "Honest caveat (see the framing note above the first table): the "
            "before/after delta above bundles the async pipeline together "
            "with PR #255's O(n^2) algorithmic fix. For the small tree (4 "
            "files, effectively no I/O-wait or quadratic-scan cost to hide), "
            "expect the speedup to be modest or even a wash, matching "
            "ADR-009's own honest prediction in its \"Negativas\" section -- "
            "a large speedup here would be the surprising result needing "
            "explanation, not the expected one. For medium/large trees, "
            "most of any large speedup should be attributed to the O(n^2) "
            "fix rather than asserted as the async pipeline's own doing, "
            "per the framing note above."
        )
    else:
        lines.append(
            "(No baseline JSON found at "
            f"`{BASELINE_JSON_PATH.relative_to(ROOT)}` -- run "
            "`scripts/async_pipeline_baseline_benchmark.py` on a pre-async "
            "revision first to produce it.)"
        )

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true",
        help="Write docs/async-pipeline-after-benchmark.md and the JSON evidence file",
    )
    parser.add_argument(
        "--runs", type=int, default=3,
        help="Number of cold+warm iterations per size (default: 3)",
    )
    args = parser.parse_args()

    if psutil is None:
        print("psutil not importable; RSS numbers will be 0. Install psutil to fix.", file=sys.stderr)

    results = [_benchmark_size(spec, args.runs) for spec in SIZES]
    baseline_by_size = _load_baseline()

    generated_at = datetime.now(timezone.utc).isoformat()
    python_version = sys.version.split()[0]
    payload = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "python_version": python_version,
        "seed": SEED,
        "results": results,
        "baseline_reference": str(BASELINE_JSON_PATH.relative_to(ROOT)) if baseline_by_size else None,
    }

    markdown = _render_markdown(results, generated_at, python_version, baseline_by_size)
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
