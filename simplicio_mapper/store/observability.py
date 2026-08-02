"""Local, content-free MapperStore metrics and reproducible benchmarks."""

from __future__ import annotations

import platform
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .health import doctor_store, redact

METRICS_SCHEMA = "simplicio.mapper-store.metrics/v1"
BENCHMARK_SCHEMA = "simplicio.mapper-store.benchmark/v1"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 4)


class Metrics:
    """Small in-process collector that never stores SQL or payload content."""

    def __init__(self) -> None:
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._counts: dict[str, int] = defaultdict(int)
        self._retries = 0
        self._lock_wait_ms: list[float] = []
        self._errors: dict[str, int] = defaultdict(int)
        self._rows: dict[str, int] = defaultdict(int)

    def observe(
        self,
        operation: str,
        duration_ms: float,
        *,
        rows: int = 0,
        retries: int = 0,
        lock_wait_ms: float = 0.0,
        error_code: str | None = None,
    ) -> None:
        if not operation or duration_ms < 0 or rows < 0 or retries < 0 or lock_wait_ms < 0:
            raise ValueError("invalid metric observation")
        self._durations[operation].append(round(float(duration_ms), 4))
        self._counts[operation] += 1
        self._rows[operation] += rows
        self._retries += retries
        self._lock_wait_ms.append(round(float(lock_wait_ms), 4))
        if error_code:
            self._errors[str(error_code)] += 1

    def time(self, operation: str, *, rows: int = 0, retries: int = 0, lock_wait_ms: float = 0.0):
        started = time.perf_counter()

        def finish(error_code: str | None = None) -> None:
            self.observe(
                operation,
                (time.perf_counter() - started) * 1000,
                rows=rows,
                retries=retries,
                lock_wait_ms=lock_wait_ms,
                error_code=error_code,
            )

        return finish

    def snapshot(self, *, database: str | Path | None = None) -> dict[str, Any]:
        operations = {
            name: {
                "count": self._counts[name],
                "rows": self._rows[name],
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
                "p99_ms": _percentile(values, 0.99),
            }
            for name, values in sorted(self._durations.items())
        }
        payload: dict[str, Any] = {
            "schema": METRICS_SCHEMA,
            "database": str(database) if database is not None else None,
            "operations": operations,
            "retries": self._retries,
            "lock_wait_ms": {
                "count": len(self._lock_wait_ms),
                "p50": _percentile(self._lock_wait_ms, 0.50),
                "p95": _percentile(self._lock_wait_ms, 0.95),
                "p99": _percentile(self._lock_wait_ms, 0.99),
            },
            "errors": dict(sorted(self._errors.items())),
            "cache": {"hit_rate": None, "reason_code": "CACHE_INSTRUMENTATION_UNAVAILABLE"},
        }
        return redact(payload)


def metrics_for_store(path: str | Path, metrics: Metrics | None = None) -> dict[str, Any]:
    """Combine local observations with safe store-size/WAL/row gauges."""

    collector = metrics or Metrics()
    snapshot = collector.snapshot(database=path)
    report = doctor_store(path)
    snapshot["gauges"] = {
        "database_bytes": report.get("counts", {}).get("database_bytes"),
        "wal_bytes": report.get("counts", {}).get("wal_bytes"),
        "rows": sum(
            value for value in report.get("counts", {}).get("rows", {}).values() if isinstance(value, int)
        ),
        "state": report.get("state"),
    }
    snapshot["reason_codes"] = report.get("reason_codes", [])
    return redact(snapshot)


def _benchmark_query(path: Path) -> int:
    wal = path.with_name(path.name + "-wal").is_file()
    query = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro" + ("" if wal else "&immutable=1")
    with closing(sqlite3.connect(query, uri=True, isolation_level=None)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0])


def run_benchmark(
    path: str | Path,
    *,
    workers: tuple[int, ...] = (1, 6, 64),
    repetitions: int = 3,
) -> dict[str, Any]:
    """Measure cold/warm read probes and preserve raw timings.

    This is intentionally a read probe, not a fabricated end-to-end claim.  A
    caller can compare the raw samples for a real installed-package smoke run.
    """

    database = Path(path).expanduser().absolute()
    if not database.is_file():
        raise FileNotFoundError(database)
    if repetitions < 1 or any(worker < 1 for worker in workers):
        raise ValueError("workers and repetitions must be positive")
    cases: list[dict[str, Any]] = []
    for worker_count in workers:
        cold: list[float] = []
        for _ in range(repetitions):
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                list(pool.map(lambda _item: _benchmark_query(database), range(worker_count)))
            cold.append(round((time.perf_counter() - started) * 1000, 4))
        warm_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            list(pool.map(lambda _item: _benchmark_query(database), range(worker_count * repetitions)))
        warm_elapsed = round((time.perf_counter() - warm_started) * 1000, 4)
        cases.append(
            {
                "workers": worker_count,
                "cold_ms": cold,
                "warm_ms": [warm_elapsed],
                "cold_p50_ms": _percentile(cold, 0.50),
                "cold_p95_ms": _percentile(cold, 0.95),
                "cold_p99_ms": _percentile(cold, 0.99),
            }
        )
    return redact(
        {
            "schema": BENCHMARK_SCHEMA,
            "status": "measured",
            "database": str(database),
            "environment": {
                "python": sys.version.split()[0],
                "sqlite": sqlite3.sqlite_version,
                "platform": platform.platform(),
            },
            "repetitions": repetitions,
            "cases": cases,
            "raw_data": {"units": "milliseconds", "content": "query-count-only"},
            "claim": "UNVERIFIED_END_TO_END_PERFORMANCE",
        }
    )


__all__ = ["BENCHMARK_SCHEMA", "METRICS_SCHEMA", "Metrics", "metrics_for_store", "run_benchmark"]
