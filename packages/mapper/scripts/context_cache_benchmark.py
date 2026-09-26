#!/usr/bin/env python3
"""Benchmark real ContextCache/query behavior with replayable JSON receipts.

The benchmark always runs against a throwaway copy of the real committed
``python-minimal`` fixture so every scenario can be replayed deterministically
without mutating the repository itself.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# The local imports intentionally follow the repository-path bootstrap below.
# ruff: noqa: E402, I001

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_mapper.context_cache import ContextCache
from simplicio_mapper.query import run_query
import simplicio_mapper.query as query_module

REPORT_SCHEMA = "simplicio.context-cache-benchmark/v1"
FIXTURE_SOURCE = REPO / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"
DEFAULT_WORKERS = 4
DEFAULT_SCENARIOS = (
    "cold-warm",
    "one-file-changed",
    "schema-changed",
    "corrupted-cache",
    "concurrent-access",
)
DEFAULT_QUERY = {"verb": "impact", "arg": "src/util.py", "limit": 20}


def _metric(value: Any, status: str, *, note: str | None = None) -> dict[str, Any]:
    payload = {"value": value, "status": status}
    if note:
        payload["note"] = note
    return payload


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def _temporary_env(**updates: str | None):
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextmanager
def _temporary_attr(obj: Any, name: str, value: Any):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


def _fixture_copy() -> tempfile.TemporaryDirectory[str]:
    if not FIXTURE_SOURCE.is_dir():
        raise SystemExit(f"fixture source not found: {FIXTURE_SOURCE}")
    tmp = tempfile.TemporaryDirectory(prefix="context-cache-benchmark-")
    shutil.copytree(FIXTURE_SOURCE, Path(tmp.name) / "source")
    return tmp


def _cache_path(cwd: Path) -> Path:
    return cwd / ".simplicio-loop" / "context-cache.json"


def _run_query(cwd: Path, *, verb: str, arg: str, limit: int = 20) -> dict[str, Any]:
    started = time.perf_counter()
    payload = run_query(str(cwd), verb=verb, arg=arg, limit=limit)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 4)
    cache_block = copy.deepcopy(payload.get("cache") or {})
    return {
        "query": {"verb": verb, "arg": arg, "limit": limit},
        "elapsed_ms": _metric(elapsed_ms, "measured"),
        "result_total": _metric(payload.get("total", 0), "measured"),
        "source": _metric(payload.get("source", "unknown"), "measured"),
        "cache": {
            "status": "measured",
            "block": cache_block,
        },
    }


def _scenario_cold_warm(cwd: Path) -> dict[str, Any]:
    cold = _run_query(cwd, **DEFAULT_QUERY)
    warm = _run_query(cwd, **DEFAULT_QUERY)
    return {
        "name": "cold-warm",
        "status": "measured",
        "runs": [cold, warm],
        "observations": {
            "warm_minus_cold_ms": _metric(
                round(warm["elapsed_ms"]["value"] - cold["elapsed_ms"]["value"], 4),
                "measured",
            ),
            "warm_tokens_avoided": _metric(
                warm["cache"]["block"].get("receipt", {}).get("tokens_avoided", 0),
                "estimated",
                note="ContextCache token accounting uses the repo heuristic chars-div-4.",
            ),
        },
    }


def _scenario_one_file_changed(cwd: Path) -> dict[str, Any]:
    baseline = _run_query(cwd, **DEFAULT_QUERY)
    target = cwd / "src" / "util.py"
    before_hash = _sha256_file(target)
    target.write_text(target.read_text(encoding="utf-8") + "\n# benchmark one-file-changed\n", encoding="utf-8")
    after_hash = _sha256_file(target)
    changed = _run_query(cwd, **DEFAULT_QUERY)
    warm_after_change = _run_query(cwd, **DEFAULT_QUERY)
    return {
        "name": "one-file-changed",
        "status": "measured",
        "file": {
            "path": "src/util.py",
            "before_sha256": _metric(before_hash, "measured"),
            "after_sha256": _metric(after_hash, "measured"),
        },
        "runs": [baseline, changed, warm_after_change],
        "observations": {
            "changed_reason": _metric(
                changed["cache"]["block"].get("receipt", {}).get("reason"),
                "measured",
            ),
        },
    }


def _scenario_schema_changed(cwd: Path) -> dict[str, Any]:
    baseline = _run_query(cwd, **DEFAULT_QUERY)
    bumped_schema = f"{query_module.ASK_SCHEMA}.bench-schema-bump"
    with _temporary_attr(query_module, "ASK_SCHEMA", bumped_schema):
        schema_miss = _run_query(cwd, **DEFAULT_QUERY)
        schema_warm = _run_query(cwd, **DEFAULT_QUERY)
    original_schema_again = _run_query(cwd, **DEFAULT_QUERY)
    return {
        "name": "schema-changed",
        "status": "measured",
        "schema_override": {
            "original": _metric(baseline["cache"]["block"].get("receipt", {}).get("layer"), "measured"),
            "simulated_schema": _metric(
                bumped_schema,
                "measured",
                note="Measured by replaying the real query path while temporarily overriding query.ASK_SCHEMA in-process.",
            ),
        },
        "runs": [baseline, schema_miss, schema_warm, original_schema_again],
    }


def _corrupt_cache_file(cache_path: Path, *, key_hash: str) -> None:
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["structured"]["entries"][key_hash]["checksum"] = "corrupted-by-benchmark"
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _scenario_corrupted_cache(cwd: Path) -> dict[str, Any]:
    baseline = _run_query(cwd, **DEFAULT_QUERY)
    key_hash = baseline["cache"]["block"].get("key_hash", "")
    cache_path = _cache_path(cwd)
    _corrupt_cache_file(cache_path, key_hash=key_hash)
    preflight = ContextCache(cache_path).explain(key_hash)
    repaired = _run_query(cwd, **DEFAULT_QUERY)
    warm_after_repair = _run_query(cwd, **DEFAULT_QUERY)
    return {
        "name": "corrupted-cache",
        "status": "measured",
        "preflight_quarantine": _metric(preflight, "measured"),
        "runs": [baseline, repaired, warm_after_repair],
    }


def _scenario_concurrent_access(cwd: Path, workers: int) -> dict[str, Any]:
    plans = [
        {"verb": "impact", "arg": "src/util.py", "limit": 20},
        {"verb": "tests-for", "arg": "src/util.py", "limit": 20},
        {"verb": "impact", "arg": "src/app.py", "limit": 20},
        {"verb": "tests-for", "arg": "src/app.py", "limit": 20},
    ]
    for plan in plans:
        _run_query(cwd, **plan)

    barrier = threading.Barrier(max(1, workers))
    results: list[dict[str, Any] | None] = [None] * max(1, workers)
    errors: list[str] = []

    def worker(index: int) -> None:
        plan = plans[index % len(plans)]
        try:
            barrier.wait(timeout=5)
            results[index] = _run_query(cwd, **plan)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - surfaced in report/tests
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(max(1, workers))]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 4)

    follow_up = _run_query(cwd, **DEFAULT_QUERY)
    cache = ContextCache(_cache_path(cwd))
    return {
        "name": "concurrent-access",
        "status": "measured",
        "workers": _metric(max(1, workers), "measured"),
        "elapsed_ms": _metric(elapsed_ms, "measured"),
        "errors": _metric(errors, "measured"),
        "runs": [result for result in results if result is not None],
        "follow_up": follow_up,
        "cache_stats": _metric(cache.stats(), "measured"),
    }


def _scenario_runner(name: str, cwd: Path, workers: int) -> dict[str, Any]:
    if name == "cold-warm":
        return _scenario_cold_warm(cwd)
    if name == "one-file-changed":
        return _scenario_one_file_changed(cwd)
    if name == "schema-changed":
        return _scenario_schema_changed(cwd)
    if name == "corrupted-cache":
        return _scenario_corrupted_cache(cwd)
    if name == "concurrent-access":
        return _scenario_concurrent_access(cwd, workers)
    raise ValueError(f"unknown scenario: {name}")


def run(*, scenarios: list[str] | None = None, workers: int = DEFAULT_WORKERS) -> dict[str, Any]:
    selected = list(scenarios or DEFAULT_SCENARIOS)
    receipts: list[dict[str, Any]] = []
    with _temporary_env(
        SIMPLICIO_MAPPER_NO_RUNTIME_IMPACT="1",
        SIMPLICIO_MAPPER_NO_RUNTIME_TESTS_FOR="1",
        SIMPLICIO_MAPPER_NO_RUNTIME_PRECEDENT="1",
    ):
        for scenario_name in selected:
            tmp = _fixture_copy()
            try:
                cwd = Path(tmp.name) / "source"
                receipts.append(_scenario_runner(scenario_name, cwd, workers))
            finally:
                tmp.cleanup()
    return {
        "schema": REPORT_SCHEMA,
        "version": 1,
        "generated_at": _now_iso(),
        "fixture": os.path.relpath(FIXTURE_SOURCE, REPO).replace(os.sep, "/"),
        "replay": {
            "cwd": str(REPO),
            "command": [sys.executable, "scripts/context_cache_benchmark.py", "--scenario", "<name>"],
            "default_workers": DEFAULT_WORKERS,
        },
        "scenarios": receipts,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_path: str | None = None
    workers = DEFAULT_WORKERS
    scenarios: list[str] = []
    i = 0
    while i < len(argv):
        argument = argv[i]
        if argument == "--out":
            i += 1
            out_path = argv[i]
        elif argument == "--workers":
            i += 1
            workers = max(1, int(argv[i]))
        elif argument == "--scenario":
            i += 1
            scenarios.append(argv[i])
        else:
            print(f"unknown argument: {argument}", file=sys.stderr)
            return 2
        i += 1

    report = run(scenarios=scenarios or None, workers=workers)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if out_path:
        Path(out_path).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
