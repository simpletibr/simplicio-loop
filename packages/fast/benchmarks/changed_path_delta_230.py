"""Measured changed-path delta handoff benchmark for issue #230."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
import platform
import statistics
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import perf_counter, process_time

from simplicio_fast.snapshot import Snapshot, build_snapshot, source_files
from simplicio_fast.workspace import WorkspaceStore

SCHEMA = "simplicio.fast.changed-path-delta-benchmark/v2"
MIN_REPETITIONS = 10


def workload_shape(symbols: int, files: int | None = None) -> tuple[int, int]:
    """Return the requested file/function distribution for a symbol target."""
    if symbols < 1:
        raise ValueError("symbols must be positive")
    if files is None:
        files = max(1, int(symbols**0.5))
        while files * files < symbols:
            files += 1
    if files < 2:
        raise ValueError("files must be at least two")
    return files, (symbols + files - 1) // files


def _process_metrics() -> tuple[int | None, int | None, str | None]:
    if os.name == "nt":
        try:

            class _Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("page_faults", ctypes.c_ulong),
                    ("peak_working_set", ctypes.c_size_t),
                    ("working_set", ctypes.c_size_t),
                    ("quota_peak_paged_pool", ctypes.c_size_t),
                    ("quota_paged_pool", ctypes.c_size_t),
                    ("quota_peak_nonpaged_pool", ctypes.c_size_t),
                    ("quota_nonpaged_pool", ctypes.c_size_t),
                    ("pagefile", ctypes.c_size_t),
                    ("peak_pagefile", ctypes.c_size_t),
                ]

            counters = _Counters()
            counters.cb = ctypes.sizeof(_Counters)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            process_memory_info = psapi.GetProcessMemoryInfo
            process_memory_info.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(_Counters),
                wintypes.DWORD,
            ]
            process_memory_info.restype = wintypes.BOOL
            if not process_memory_info(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return None, None, "windows_process_memory_query_failed"
            return (
                max(0, int(counters.peak_working_set // 1024)),
                int(counters.page_faults),
                None,
            )
        except (AttributeError, OSError, TypeError):
            return None, None, "windows_process_memory_unavailable"

    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(usage.ru_maxrss)
        if platform.system() == "Darwin":
            rss //= 1024
        faults = int(usage.ru_minflt + usage.ru_majflt)
        return max(0, rss), faults, None
    except (ImportError, AttributeError, OSError, ValueError):
        return None, None, "process_metrics_unavailable"


def _measure(operation: Callable[[], object]) -> tuple[dict[str, object], object]:
    before_rss, before_faults, reason = _process_metrics()
    wall_start = perf_counter()
    cpu_start = process_time()
    result = operation()
    sample = {
        "wall_ms": (perf_counter() - wall_start) * 1000,
        "cpu_ms": (process_time() - cpu_start) * 1000,
        "rss_kib": None,
        "page_faults": None,
    }
    after_rss, after_faults, after_reason = _process_metrics()
    if after_rss is not None:
        sample["rss_kib"] = after_rss
    if after_faults is not None and before_faults is not None:
        sample["page_faults"] = max(0, after_faults - before_faults)
    return sample, result if reason is None else (result, reason or after_reason)


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    def median(name: str) -> float | int | None:
        values = [row[name] for row in rows if isinstance(row[name], (int, float))]
        return statistics.median(values) if values else None

    def percentile(name: str, fraction: float) -> float | None:
        values = sorted(
            float(row[name])
            for row in rows
            if isinstance(row[name], (int, float))
        )
        if not values:
            return None
        position = (len(values) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return values[lower] + (values[upper] - values[lower]) * weight

    return {
        "repetitions": len(rows),
        "wall_ms_median": median("wall_ms"),
        "wall_ms_p95": percentile("wall_ms", 0.95),
        "wall_ms_p99": percentile("wall_ms", 0.99),
        "cpu_ms_median": median("cpu_ms"),
        "cpu_ms_p95": percentile("cpu_ms", 0.95),
        "cpu_ms_p99": percentile("cpu_ms", 0.99),
        "rss_kib_median": median("rss_kib"),
        "page_faults_median": median("page_faults"),
        "parsed_files_median": median("parsed_files"),
        "reused_files_median": median("reused_files"),
        "parsed_bytes_median": median("parsed_bytes"),
        "reused_bytes_median": median("reused_bytes"),
        "mapped_bytes_median": median("mapped_bytes"),
        "stage_coverage_min": (
            min(
                float(row["stage_coverage"])
                for row in rows
                if isinstance(row.get("stage_coverage"), (int, float))
            )
            if any(isinstance(row.get("stage_coverage"), (int, float)) for row in rows)
            else None
        ),
        "parity": all(bool(row["parity"]) for row in rows),
    }


def _performance_gates(categories: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    medians = {
        name: _summary(rows)["wall_ms_median"]
        for name, rows in categories.items()
    }
    one_file = medians["one_file"]
    cold = medians["cold"]
    unchanged = medians["unchanged"]
    warm = medians["warm"]
    checks = {
        "one_file_faster_than_cold": (
            isinstance(one_file, (int, float))
            and isinstance(cold, (int, float))
            and one_file < cold
        ),
        "one_file_within_half_cold": (
            isinstance(one_file, (int, float))
            and isinstance(cold, (int, float))
            and one_file <= cold * 0.5
        ),
        "unchanged_within_two_times_warm": (
            isinstance(unchanged, (int, float))
            and isinstance(warm, (int, float))
            and unchanged <= warm * 2
        ),
        "unchanged_under_reference_budget": (
            isinstance(unchanged, (int, float)) and unchanged <= 5.0
        ),
    }
    return {
        "schema": "simplicio.fast.changed-path-performance-gates/v1",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "medians_ms": medians,
        "unavailable_reason": None
        if all(isinstance(value, (int, float)) for value in medians.values())
        else "wall_median_missing",
    }


def _make_root(
    parent: Path, files: int, label: str, functions_per_file: int = 1
) -> tuple[Path, WorkspaceStore, object, dict[str, int]]:
    root = parent / label
    root.mkdir()
    for index in range(files):
        source = "".join(
            f"def value_{index}_{function}():\n    return {function}\n"
            for function in range(functions_per_file)
        )
        (root / f"module_{index:03d}.py").write_text(source, encoding="utf-8")
    store = WorkspaceStore(root)
    base = store.build_base(config={"benchmark": "issue-230"})
    sizes = {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in source_files(root)
    }
    return root, store, base, sizes


def _mapped_bytes(store: WorkspaceStore, base: object) -> int:
    manifest = store.manifest(base.generation_id)
    return (store.base_dir / base.generation_id / manifest.snapshot).stat().st_size


def _run_category(
    parent: Path,
    files: int,
    repetitions: int,
    category: str,
    functions_per_file: int = 1,
) -> list[dict[str, object]]:
    root, store, base, sizes = _make_root(
        parent, files, category, functions_per_file
    )
    rows: list[dict[str, object]] = []
    if category == "cold":
        for revision in range(repetitions):
            target = root / f"cold-{revision}.sfast"

            def build() -> None:
                build_snapshot(root, target)

            sample, _ = _measure(build)
            sample.update(
                {
                    "parsed_files": files,
                    "reused_files": 0,
                    "parsed_bytes": sum(sizes.values()),
                    "reused_bytes": 0,
                    "mapped_bytes": target.stat().st_size,
                    "parity": True,
                }
            )
            rows.append(sample)
        return rows

    base_mapped_bytes = _mapped_bytes(store, base)
    if category == "warm":
        for revision in range(repetitions):

            def read_snapshot() -> int:
                with Snapshot(
                    store.base_dir / base.generation_id / base.snapshot
                ) as snapshot:
                    return len(snapshot.files())

            sample, count = _measure(read_snapshot)
            if isinstance(count, tuple):
                count = count[0]
            sample.update(
                {
                    "parsed_files": 0,
                    "reused_files": files,
                    "parsed_bytes": 0,
                    "reused_bytes": sum(sizes.values()),
                    "mapped_bytes": base_mapped_bytes,
                    "parity": count == files,
                    "stage_timings_ms": None,
                }
            )
            rows.append(sample)
        return rows

    for revision in range(repetitions):
        source = root / "module_000.py"
        audit_parity = revision in {0, repetitions - 1} and category != "unchanged"
        parity_snapshot = root / f"parity-{revision}.sfast"
        if category == "one_file":
            source.write_text(
                f"def value_0():\n    return {revision + 1}\n", encoding="utf-8"
            )
            if audit_parity:
                build_snapshot(root, parity_snapshot)
            changed_bytes = source.stat().st_size
            expected_parsed = 1
            expected_reused = files - 1
            expected_parsed_bytes = changed_bytes
            expected_reused_bytes = sum(
                size for path, size in sizes.items() if path != "module_000.py"
            )
            changed_paths = ["module_000.py"]
        else:
            # Keep the source identity unchanged: an unchanged delta must
            # measure the hot path, not repeated writes of identical bytes.
            if audit_parity:
                build_snapshot(root, parity_snapshot)
            expected_parsed = 0
            expected_reused = files
            expected_parsed_bytes = 0
            expected_reused_bytes = sum(sizes.values())
            changed_paths = ["module_000.py"]

        def handoff() -> dict[str, object]:
            return store.handoff(
                base.generation_id,
                category,
                changed_paths,
                # Unchanged is measured from validated base + changed-path
                # evidence; background parity remains explicit for other
                # categories and must not contaminate the hot-path budget.
                parity_snapshot=parity_snapshot if audit_parity else None,
            )

        sample, report = _measure(handoff)
        if isinstance(report, tuple):
            report = report[0]
        sample.update(
            {
                "parsed_files": int(report["files_parsed"]),
                "reused_files": int(report["cache_reuse"]),
                "parsed_bytes": expected_parsed_bytes,
                "reused_bytes": expected_reused_bytes,
                "mapped_bytes": base_mapped_bytes,
                "parity": bool(report["parity"]),
                "background_parity": bool(report["parity"]) if audit_parity else None,
                "background_parity_reason": (
                    "audited_revision" if audit_parity else "hot_path_not_materialized"
                ),
                "stage_timings_ms": report.get("stage_timings_ms"),
            }
        )
        stage_timings = sample["stage_timings_ms"]
        if isinstance(stage_timings, dict) and sample["wall_ms"]:
            stage_timings = dict(stage_timings)
            measured_stage_ms = sum(
                float(value)
                for value in stage_timings.values()
                if isinstance(value, (int, float))
            )
            stage_timings["orchestration_and_receipt_residual"] = round(
                max(0.0, float(sample["wall_ms"]) - measured_stage_ms), 3
            )
            sample["stage_timings_ms"] = stage_timings
            sample["stage_coverage"] = round(
                sum(
                    float(value)
                    for value in stage_timings.values()
                    if isinstance(value, (int, float))
                )
                / float(sample["wall_ms"]),
                6,
            )
        else:
            sample["stage_coverage"] = None
        if (
            sample["parsed_files"] != expected_parsed
            or sample["reused_files"] != expected_reused
        ):
            raise AssertionError(f"{category} reuse accounting drifted: {sample}")
        rows.append(sample)
    return rows


def run(
    *, files: int = 24, repetitions: int = MIN_REPETITIONS, functions_per_file: int = 1
) -> dict[str, object]:
    if files < 2:
        raise ValueError("files must be at least two")
    if repetitions < MIN_REPETITIONS:
        raise ValueError(f"repetitions must be at least {MIN_REPETITIONS}")
    if functions_per_file < 1:
        raise ValueError("functions_per_file must be positive")
    with tempfile.TemporaryDirectory(prefix="simplicio-fast-delta-") as directory:
        parent = Path(directory)
        categories = {
            category: _run_category(
                parent, files, repetitions, category, functions_per_file
            )
            for category in ("cold", "warm", "unchanged", "one_file")
        }
        metric_reasons = {
            "rss_kib": "available"
            if all(
                row["rss_kib"] is not None
                for rows in categories.values()
                for row in rows
            )
            else "host_metric_unavailable",
            "page_faults": "available"
            if all(
                row["page_faults"] is not None
                for rows in categories.values()
                for row in rows
            )
            else "host_metric_unavailable",
        }
        performance_gates = _performance_gates(categories)
        return {
            "schema": SCHEMA,
            "status": "pass"
            if all(bool(row["parity"]) for rows in categories.values() for row in rows)
            else "parity_mismatch",
            "workload": {
                "files": files,
                "symbols": files * functions_per_file,
                "functions_per_file": functions_per_file,
                "changed_files": 1,
                "repetitions": repetitions,
                "minimum_repetitions": MIN_REPETITIONS,
                "categories": list(categories),
            },
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "metrics_status": "complete"
                if all(value == "available" for value in metric_reasons.values())
                else "partial",
                "metric_reasons": metric_reasons,
            },
            "categories": {
                name: {
                    "summary": _summary(rows),
                    "raw": rows,
                }
                for name, rows in categories.items()
            },
            "performance_gates": performance_gates,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--files",
        type=int,
        default=None,
        help="source-file count; when omitted with --symbols, use a square-root shape",
    )
    parser.add_argument(
        "--symbols",
        type=int,
        help="target symbol count; distributes symbols across approximately sqrt(N) files",
    )
    parser.add_argument("--repetitions", type=int, default=MIN_REPETITIONS)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    files = args.files if args.files is not None else 24
    functions_per_file = 1
    if args.symbols is not None:
        try:
            files, functions_per_file = workload_shape(args.symbols, args.files)
        except ValueError as error:
            parser.error(str(error))
    receipt = run(
        files=files,
        repetitions=args.repetitions,
        functions_per_file=functions_per_file,
    )
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(payload, encoding="utf-8")
    print(payload, end="")


if __name__ == "__main__":
    main()
