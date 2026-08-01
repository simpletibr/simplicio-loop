"""Reproducible concurrent metadata-cache benchmark for issue #417.

The benchmark measures only the cache storage boundary.  Mapper binding and
freshness validation happen before this boundary in production and are not
pretended to be part of the cache timing.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from simplicio.plan_compiler.mapper_context import ContextBindingCache

SCHEMA = "simplicio.dev-cli.issue-417-context-cache-benchmark/v1"


def _writer(args: tuple[str, int]) -> None:
    root, number = args
    cache = ContextBindingCache(root)
    key = f"sha256:{number:064x}"
    identity = {
        "snapshot_id": f"snapshot-{number}",
        "revision": f"revision-{number}",
        "source_digest": f"source-{number}",
        "pack_hash": f"pack-{number}",
        "source_root_identity": "benchmark-root",
    }
    cache._append_event("put", key, identity=identity)


def _run_case(root: Path, writers: int, repeats: int) -> dict[str, Any]:
    case_root = root / f"writers-{writers}"
    case_root.mkdir(parents=True, exist_ok=True)
    samples: list[float] = []
    for repeat in range(repeats):
        if case_root.exists():
            shutil.rmtree(case_root)
        case_root.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=min(writers, os.cpu_count() or 1)) as pool:
            list(pool.map(_writer, ((str(case_root), repeat * writers + n) for n in range(writers))))
        samples.append((time.perf_counter() - started) * 1000.0)
    cache = ContextBindingCache(case_root)
    health = cache.doctor()
    return {
        "writers": writers,
        "repeats": repeats,
        "p50_ms": sorted(samples)[len(samples) // 2],
        "p95_ms": sorted(samples)[max(0, int(len(samples) * 0.95) - 1)],
        "samples_ms": samples,
        "entries": health["entries"],
        "bytes": health["bytes"],
        "chain_status": health["chain_status"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=None, help="directory for temporary benchmark state")
    parser.add_argument("--output", default=None)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if args.repeats < 10:
        parser.error("--repeats must be at least 10")
    owned_root = args.root is None
    root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="issue-417-cache-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        cases = [_run_case(root, writers, args.repeats) for writers in (1, 10, 50)]
        report = {
            "schema": SCHEMA,
            "python": os.sys.version.split()[0],
            "cases": cases,
            "all_chains_valid": all(case["chain_status"] == "valid" for case in cases),
        }
        rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    finally:
        if owned_root:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
