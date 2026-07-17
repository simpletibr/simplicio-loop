#!/usr/bin/env python3
"""Perf benchmark: ``_build_file_inventory`` (sync) vs.
``build_file_inventory_async_sync`` (new, ADR-009 / issue #235 plan steps
4-5) on a synthetic tree, cold (empty disk cache) and warm.

Reuses the deterministic synthetic-tree generator from
``scripts/async_pipeline_baseline_benchmark.py`` so the "before" (existing
ADR-009 baseline) and "after" (this task's new async inventory path) numbers
are directly comparable, measured the same way (``time.perf_counter``,
median across ``--runs`` repetitions).

This measures ONLY the file-inventory step (not the full
``build_artifacts`` pipeline that the existing baseline benchmark covers),
since that is the exact scope of this task -- an async replacement for
``_build_file_inventory``'s walk-and-read-and-parse loop, not the full
pipeline.

Usage:
    python3 scripts/async_inventory_benchmark.py [--files N] [--runs N]

Reports the honest measured numbers -- per ADR-009's own "Negativas"
section, I/O-bound gains may be modest (or even a wash) on a fast local
disk with OS-level page caching; this script does not assert a hard
speedup gate, only prints what was measured.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.mapper.async_inventory import build_file_inventory_async_sync  # noqa: E402
from simplicio_mapper.mapper.parse import _build_file_inventory  # noqa: E402

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


def _time_sync(source_dir: Path, cache_dir: Path) -> float:
    with FileProcessingCache(str(cache_dir)) as cache:
        start = time.perf_counter()
        result = _build_file_inventory(str(source_dir), {}, {}, cache, contents={})
        elapsed = time.perf_counter() - start
    assert len(result) > 0
    return elapsed


def _time_async(source_dir: Path, cache_dir: Path) -> float:
    with FileProcessingCache(str(cache_dir)) as cache:
        start = time.perf_counter()
        result = build_file_inventory_async_sync(str(source_dir), {}, {}, cache=cache, contents={})
        elapsed = time.perf_counter() - start
    assert len(result) > 0
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=400, help="Synthetic file count (default: 400)")
    parser.add_argument("--runs", type=int, default=5, help="Cold+warm repetitions (default: 5)")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="async-inventory-bench-") as tmp:
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source"
        file_count = _materialize_synthetic_tree(source_dir, args.files)

        sync_cold, sync_warm, async_cold, async_warm = [], [], [], []

        for run_index in range(args.runs):
            sync_cache = tmp_path / f"sync-cache-{run_index}"
            sync_cold.append(_time_sync(source_dir, sync_cache))
            sync_warm.append(_time_sync(source_dir, sync_cache))

            async_cache = tmp_path / f"async-cache-{run_index}"
            async_cold.append(_time_async(source_dir, async_cache))
            async_warm.append(_time_async(source_dir, async_cache))

        def _report(label: str, samples: list[float]) -> None:
            median = statistics.median(samples)
            print(
                f"{label:<28} median={median:.4f}s  "
                f"files/s={file_count / median:.1f}  "
                f"samples={[round(s, 4) for s in samples]}"
            )

        print(f"Synthetic tree: {file_count} files, {args.runs} run(s) each\n")
        _report("sync  (cold, no cache)", sync_cold)
        _report("sync  (warm, cache hit)", sync_warm)
        _report("async (cold, no cache)", async_cold)
        _report("async (warm, cache hit)", async_warm)

        cold_speedup = statistics.median(sync_cold) / statistics.median(async_cold)
        warm_speedup = statistics.median(sync_warm) / statistics.median(async_warm)
        print(
            f"\nasync/sync speedup -- cold: {cold_speedup:.2f}x, warm: {warm_speedup:.2f}x\n"
            "(honest note: on a fast local disk with OS page caching, small "
            "source files may show a modest or even negative speedup, since "
            "asyncio/thread-pool scheduling overhead can outweigh I/O-wait "
            "savings when there is little I/O-wait to hide -- expected per "
            "ADR-009's 'Negativas' section, not a benchmark bug.)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
