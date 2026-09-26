#!/usr/bin/env python3
"""Perf benchmark: sync ``_build_file_inventory`` vs. the two async
inventory-builder implementations that exist in this repo (issue #235 /
ADR-009, evidence gathering for issue #264):

- ``simplicio_mapper.mapper.async_inventory.build_file_inventory_async_sync``
  -- the standalone, not-wired-into-any-CLI-command building block added by
  PR #262. Kept as a proven-correct-in-isolation reference implementation
  (see that module's own docstring).
- ``simplicio_mapper.mapper.async_pipeline.build_file_inventory_async`` --
  the implementation actually composed into ``build_artifacts_async`` (PR
  #260) and therefore the one that runs for every real
  ``index``/``map``/``scan`` invocation today via the sync adapter in
  ``simplicio_mapper/mapper/emit.py::build_artifacts``.

Both async paths are structurally required (by their own test suites,
``tests/python/test_mapper_async_inventory.py`` and
``tests/python/test_async_pipeline.py``) to produce output identical to the
sync path, so this script measures wall time / CPU time / peak RSS / files
per second for all three, cold (empty disk cache) and warm (same cache dir
re-run), to give an honest before/after comparison of the actual
async-pipeline path that ships, while keeping the standalone module's
numbers for completeness.

This measures ONLY the file-inventory step (not the full ``build_artifacts``
pipeline -- see ``scripts/async_pipeline_baseline_benchmark.py`` for that
script's historical, pre-async-adapter full-pipeline numbers, which cannot
be regenerated on this revision; see its own module docstring and issue
#264 for why).

Usage:
    python3 scripts/async_inventory_benchmark.py [--files N] [--runs N]
    python3 scripts/async_inventory_benchmark.py --sizes [--runs N] [--write]

``--sizes`` runs the standard small (real fixture) / medium (220 files) /
large (1650 files) report used across this repo's other benchmark docs and
optionally writes ``docs/async-inventory-benchmark.md`` +
``docs/evidence/async-inventory-benchmark.json`` (``--write``). Without
``--sizes``, the original single-size quick mode (``--files``/``--runs``)
still works exactly as before, printing to stdout only.

Reports the honest measured numbers -- per ADR-009's own "Negativas"
section, I/O-bound gains may be modest (or even a wash, or negative) on a
fast local disk with OS-level page caching, especially for small trees;
this script does not assert a hard speedup gate, only prints/writes what
was measured.
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.mapper.async_inventory import build_file_inventory_async_sync  # noqa: E402
from simplicio_mapper.mapper.parse import _build_file_inventory  # noqa: E402

try:
    import asyncio

    from simplicio_mapper.mapper.async_pipeline import (  # noqa: E402
        build_file_inventory_async as pipeline_build_file_inventory_async,
    )
except ImportError:  # pragma: no cover - defensive, module always present today
    pipeline_build_file_inventory_async = None

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a project dependency already
    psutil = None

SCHEMA = "simplicio.async-inventory-benchmark/v1"
MD_DOC_PATH = ROOT / "docs" / "async-inventory-benchmark.md"
JSON_DOC_PATH = ROOT / "docs" / "evidence" / "async-inventory-benchmark.json"
FIXTURE_ROOT = ROOT / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"

_MODULE_TEMPLATE = '''"""Synthetic module {index} for the async-inventory benchmark."""

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

SEED = 20260717


@dataclass(frozen=True)
class SizeSpec:
    name: str
    file_count: int
    use_real_fixture: bool = False


SIZES: list[SizeSpec] = [
    SizeSpec(name="small", file_count=0, use_real_fixture=True),
    SizeSpec(name="medium", file_count=220),
    SizeSpec(name="large", file_count=1650),
]


class _RssSampler:
    """Samples RSS of the current process on a background thread.

    Mirrors ``scripts/async_pipeline_baseline_benchmark.py``'s sampler so
    the two reports' RSS numbers are collected the same way and are
    comparable.
    """

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


@dataclass
class RunStats:
    wall_seconds: list[float] = field(default_factory=list)
    cpu_seconds: list[float] = field(default_factory=list)
    peak_rss_bytes: list[int] = field(default_factory=list)

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
        return int(statistics.median(self.peak_rss_bytes)) if self.peak_rss_bytes else 0


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


def _time_sync(source_dir: Path, cache_dir: Path) -> tuple[float, float, int]:
    with FileProcessingCache(str(cache_dir)) as cache:
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        with _RssSampler() as sampler:
            result = _build_file_inventory(str(source_dir), {}, {}, cache, contents={})
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
    assert len(result) > 0
    return wall, cpu, sampler.peak


def _time_async_inventory(source_dir: Path, cache_dir: Path) -> tuple[float, float, int]:
    with FileProcessingCache(str(cache_dir)) as cache:
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        with _RssSampler() as sampler:
            result = build_file_inventory_async_sync(str(source_dir), {}, {}, cache=cache, contents={})
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
    assert len(result) > 0
    return wall, cpu, sampler.peak


def _time_async_pipeline(source_dir: Path, cache_dir: Path) -> tuple[float, float, int]:
    with FileProcessingCache(str(cache_dir)) as cache:
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        with _RssSampler() as sampler:
            result = asyncio.run(
                pipeline_build_file_inventory_async(str(source_dir), {}, {}, cache, contents={})
            )
        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
    assert len(result) > 0
    return wall, cpu, sampler.peak


_RUNNERS: dict[str, Any] = {
    "sync": _time_sync,
    "async_inventory": _time_async_inventory,
}
if pipeline_build_file_inventory_async is not None:
    _RUNNERS["async_pipeline"] = _time_async_pipeline


def _benchmark_size(spec: SizeSpec, runs: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="async-inventory-bench-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        if spec.use_real_fixture:
            file_count = _copy_real_fixture(source_dir)
        else:
            file_count = _materialize_synthetic_tree(source_dir, spec.file_count)

        stats: dict[str, dict[str, RunStats]] = {
            label: {"cold": RunStats(), "warm": RunStats()} for label in _RUNNERS
        }

        for run_index in range(runs):
            for label, runner in _RUNNERS.items():
                cache_dir = tmp_path / f"{label}-cache-{run_index}"
                wall, cpu, peak = runner(source_dir, cache_dir)
                stats[label]["cold"].wall_seconds.append(wall)
                stats[label]["cold"].cpu_seconds.append(cpu)
                stats[label]["cold"].peak_rss_bytes.append(peak)

                wall, cpu, peak = runner(source_dir, cache_dir)
                stats[label]["warm"].wall_seconds.append(wall)
                stats[label]["warm"].cpu_seconds.append(cpu)
                stats[label]["warm"].peak_rss_bytes.append(peak)

        def _phase_payload(run_stats: RunStats) -> dict[str, Any]:
            return {
                "wall_median_s": round(run_stats.wall_median, 4),
                "wall_p95_s": round(run_stats.wall_p95, 4),
                "cpu_median_s": round(run_stats.cpu_median, 4),
                "peak_rss_mb": round(run_stats.peak_rss_median / (1024 * 1024), 2),
                "files_per_sec": round(file_count / run_stats.wall_median, 2)
                if run_stats.wall_median > 0
                else 0.0,
            }

        result: dict[str, Any] = {"size": spec.name, "file_count": file_count, "runs": runs}
        for label in _RUNNERS:
            cold = _phase_payload(stats[label]["cold"])
            warm = _phase_payload(stats[label]["warm"])
            result[label] = {
                "cold": cold,
                "warm": warm,
                "warm_vs_cold_speedup_ratio": round(cold["wall_median_s"] / warm["wall_median_s"], 2)
                if warm["wall_median_s"] > 0
                else float("nan"),
            }

        for label in _RUNNERS:
            if label == "sync":
                continue
            sync_cold = result["sync"]["cold"]["wall_median_s"]
            sync_warm = result["sync"]["warm"]["wall_median_s"]
            label_cold = result[label]["cold"]["wall_median_s"]
            label_warm = result[label]["warm"]["wall_median_s"]
            result[label]["speedup_vs_sync"] = {
                "cold": round(sync_cold / label_cold, 2) if label_cold > 0 else float("nan"),
                "warm": round(sync_warm / label_warm, 2) if label_warm > 0 else float("nan"),
            }

        return result


def _render_markdown(results: list[dict[str, Any]], generated_at: str, python_version: str, runs: int) -> str:
    labels = list(_RUNNERS.keys())
    lines = [
        "# Async file-inventory benchmark -- sync vs. async (issue #264)",
        "",
        f"Measured: {generated_at}, Python `{python_version}`, `--runs {runs}` "
        "on this machine. Tool: `scripts/async_inventory_benchmark.py --sizes --write`.",
        "",
        "Compares three implementations of the file-inventory walk-and-parse "
        "step, all callable directly on this revision (unlike the full "
        "`build_artifacts` pipeline, whose pre-async sync form no longer "
        "exists as an independently callable path -- see "
        "`docs/async-pipeline-baseline-benchmark.md` for the historical, "
        "frozen full-pipeline baseline measured before the async adapter "
        "landed, and this doc's \"Limitations\" section below):",
        "",
        "- `sync` -- `simplicio_mapper.mapper.parse._build_file_inventory` "
        "(the original, single-threaded loop; still present, no longer "
        "called by `build_artifacts` in production).",
        "- `async_inventory` -- "
        "`simplicio_mapper.mapper.async_inventory.build_file_inventory_async_sync` "
        "(PR #262; standalone, proven-correct building block, not wired "
        "into any CLI command).",
        "- `async_pipeline` -- "
        "`simplicio_mapper.mapper.async_pipeline.build_file_inventory_async` "
        "(PR #260; the implementation actually composed into "
        "`build_artifacts_async`, i.e. what every `index`/`map`/`scan` run "
        "uses today via the sync adapter in `simplicio_mapper/mapper/emit.py`).",
        "",
        "Cold = fresh empty disk cache; warm = same cache dir re-run "
        "immediately after (disk-cache hit path).",
        "",
    ]

    for r in results:
        lines.append(f"## {r['size']} ({r['file_count']} files, {r['runs']} run(s))")
        lines.append("")
        lines.append(
            "| Path | Cold wall p50/p95 (s) | Cold CPU (s) | Cold peak RSS (MB) | "
            "Cold files/s | Warm wall p50/p95 (s) | Warm CPU (s) | Warm peak RSS (MB) | "
            "Warm files/s | Warm/Cold | vs sync (cold/warm) |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for label in labels:
            entry = r[label]
            cold = entry["cold"]
            warm = entry["warm"]
            vs_sync = entry.get("speedup_vs_sync")
            vs_sync_str = (
                f"{vs_sync['cold']}x / {vs_sync['warm']}x" if vs_sync is not None else "n/a (baseline)"
            )
            lines.append(
                f"| `{label}` | {cold['wall_median_s']} / {cold['wall_p95_s']} | "
                f"{cold['cpu_median_s']} | {cold['peak_rss_mb']} | {cold['files_per_sec']} | "
                f"{warm['wall_median_s']} / {warm['wall_p95_s']} | {warm['cpu_median_s']} | "
                f"{warm['peak_rss_mb']} | {warm['files_per_sec']} | "
                f"{entry['warm_vs_cold_speedup_ratio']}x | {vs_sync_str} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Reading these numbers",
            "",
            "- **Cache hit/miss proxy**: this script does not expose raw "
            "`diskcache` hit/miss counters, so the warm/cold wall-time ratio "
            "is used as the cache-effectiveness proxy, matching "
            "`docs/async-pipeline-baseline-benchmark.md`'s convention.",
            "- **files/s** is `file_count / wall_median`.",
            "- **small** uses the real committed "
            "`contracts/mapper-artifacts/v1/fixtures/python-minimal/source` "
            "fixture; **medium**/**large** use deterministically generated "
            f"synthetic Python packages (seed `{SEED}`).",
            "- Per ADR-009's own \"Negativas\" section: on a fast local disk "
            "with OS-level page caching, small trees can show a *negative* "
            "speedup for the async paths (asyncio/thread-pool scheduling "
            "overhead outweighs I/O-wait savings when there is barely any "
            "I/O-wait to hide) -- this is expected and reported honestly "
            "here, not treated as a bug or hidden.",
            "",
            "## Limitations",
            "",
            "- This report measures the **inventory stage only**, not the "
            "full `build_artifacts` pipeline (symbol index, call graph, "
            "architecture inventory, JSON writes are unchanged and "
            "synchronous either way -- see ADR-009's \"Contexto\" table).",
            "- A true apples-to-apples **full-pipeline** sync-vs-async "
            "comparison is not reproducible on this revision: "
            "`build_artifacts` unconditionally delegates to "
            "`build_artifacts_async` now (ADR-009 plan step 8), so there is "
            "no independently callable full-pipeline sync entry point left "
            "to re-measure against. "
            "`scripts/async_pipeline_baseline_benchmark.py` refuses to run "
            "here for exactly this reason (see its own guard and issue "
            "#264's comment thread) and its committed numbers in "
            "`docs/async-pipeline-baseline-benchmark.md` remain the last "
            "real, historical, pre-async-adapter full-pipeline baseline -- "
            "frozen, not regenerated by this report.",
            "- Sample sizes here (`--runs 3` by default) are small; wall-time "
            "p95 in particular is noisy at n=3 (see the raw JSON evidence "
            "file for exact per-run figures). Treat single-digit-percent "
            "differences between implementations as within measurement "
            "noise on this machine, not a confirmed regression/improvement.",
            "- Numbers are machine- and OS-specific (this run: Windows, "
            "single local disk, no cross-platform parity claimed).",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_report(runs: int, write: bool) -> int:
    results = [_benchmark_size(spec, runs) for spec in SIZES]
    generated_at = datetime.now(timezone.utc).isoformat()
    python_version = sys.version.split()[0]

    payload = {
        "schema": SCHEMA,
        "generated_at": generated_at,
        "python_version": python_version,
        "seed": SEED,
        "implementations": list(_RUNNERS.keys()),
        "results": results,
    }

    markdown = _render_markdown(results, generated_at, python_version, runs)
    print(markdown)

    if write:
        MD_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        MD_DOC_PATH.write_text(markdown, encoding="utf-8")
        JSON_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        JSON_DOC_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {MD_DOC_PATH}", file=sys.stderr)
        print(f"Wrote {JSON_DOC_PATH}", file=sys.stderr)

    return 0


def _run_quick(file_count: int, runs: int) -> int:
    """Original single-size quick mode, preserved for backward compatibility
    (ad-hoc local checks) -- prints only, never writes docs.
    """
    with tempfile.TemporaryDirectory(prefix="async-inventory-bench-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        actual_file_count = _materialize_synthetic_tree(source_dir, file_count)

        collected: dict[str, dict[str, list[float]]] = {
            label: {"cold": [], "warm": []} for label in _RUNNERS
        }

        for run_index in range(runs):
            for label, runner in _RUNNERS.items():
                cache_dir = tmp_path / f"{label}-cache-{run_index}"
                wall, _cpu, _peak = runner(source_dir, cache_dir)
                collected[label]["cold"].append(wall)
                wall, _cpu, _peak = runner(source_dir, cache_dir)
                collected[label]["warm"].append(wall)

        def _report(label: str, samples: list[float]) -> None:
            median = statistics.median(samples)
            print(
                f"{label:<28} median={median:.4f}s  "
                f"files/s={actual_file_count / median:.1f}  "
                f"samples={[round(s, 4) for s in samples]}"
            )

        print(f"Synthetic tree: {actual_file_count} files, {runs} run(s) each\n")
        for label in _RUNNERS:
            _report(f"{label} (cold, no cache)", collected[label]["cold"])
            _report(f"{label} (warm, cache hit)", collected[label]["warm"])

        sync_cold = statistics.median(collected["sync"]["cold"])
        sync_warm = statistics.median(collected["sync"]["warm"])
        for label in _RUNNERS:
            if label == "sync":
                continue
            cold_speedup = sync_cold / statistics.median(collected[label]["cold"])
            warm_speedup = sync_warm / statistics.median(collected[label]["warm"])
            print(
                f"\n{label}/sync speedup -- cold: {cold_speedup:.2f}x, warm: {warm_speedup:.2f}x"
            )
        print(
            "\n(honest note: on a fast local disk with OS page caching, small "
            "source files may show a modest or even negative speedup, since "
            "asyncio/thread-pool scheduling overhead can outweigh I/O-wait "
            "savings when there is little I/O-wait to hide -- expected per "
            "ADR-009's 'Negativas' section, not a benchmark bug.)"
        )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--files", type=int, default=None, help="Quick mode: synthetic file count for a single ad-hoc run")
    parser.add_argument("--runs", type=int, default=5, help="Cold+warm repetitions (default: 5; --sizes default: 3)")
    parser.add_argument("--sizes", action="store_true", help="Run the standard small/medium/large report (CPU/RSS/p95 included)")
    parser.add_argument("--write", action="store_true", help="With --sizes: write docs/async-inventory-benchmark.md and the JSON evidence file")
    args = parser.parse_args()

    if psutil is None:
        print("psutil not importable; RSS numbers will be 0. Install psutil to fix.", file=sys.stderr)

    if args.sizes or args.write:
        runs = args.runs if args.runs != 5 else 3  # --sizes default runs=3, matching the baseline script's convention
        return _run_report(runs, args.write)

    return _run_quick(args.files or 400, args.runs)


if __name__ == "__main__":
    raise SystemExit(main())
