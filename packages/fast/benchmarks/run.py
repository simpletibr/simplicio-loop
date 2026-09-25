"""Reproducible baseline/Fast benchmark for 1k, 10k and 100k symbols."""

import argparse
import ast
import concurrent.futures
import json
import statistics
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows Python can omit resource.
    resource = None


try:
    import tracemalloc
except ImportError:  # pragma: no cover - Python builds can omit tracemalloc.
    tracemalloc = None
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from simplicio_fast.snapshot import Snapshot, build_snapshot, source_files
from simplicio_fast.workspace import WorkspaceStore

SHARED_BASE_OVERLAY_SLOTS = (1, 20, 100)


def _unavailable(reason: str) -> dict[str, int | str | None]:
    return {"value": None, "reason": reason}


def _posix_peak_rss_kib(platform: str) -> dict[str, int | str | None]:
    try:
        import resource
    except ImportError:
        return _unavailable("posix_resource_module_unavailable")

    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return _unavailable("posix_resource_getrusage_unavailable")

    # Linux and the BSDs report KiB; macOS reports bytes.
    if platform == "darwin":
        value //= 1024
    return {"value": value, "reason": None}


def _windows_peak_rss_kib() -> dict[str, int | str | None]:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory_info.restype = wintypes.BOOL
        if not get_memory_info(process, ctypes.byref(counters), counters.cb):
            return _unavailable("windows_get_process_memory_info_failed")
        return {"value": int(counters.PeakWorkingSetSize // 1024), "reason": None}
    except (AttributeError, ImportError, OSError, TypeError, ValueError):
        return _unavailable("windows_process_memory_api_unavailable")


def peak_rss_metric(platform: str | None = None) -> dict[str, int | str | None]:
    """Return a deterministic peak-RSS value and an unavailable reason, if any."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return _windows_peak_rss_kib()
    return _posix_peak_rss_kib(platform)


def peak_rss_kib() -> int | None:
    """Return peak RSS in KiB for callers that only need the numeric value."""
    return peak_rss_metric()["value"]  # type: ignore[return-value]


def _allocation_percentiles(samples: list[int]) -> dict[str, object]:
    ordered = sorted(samples)
    return {
        "samples": samples,
        "median": statistics.median(ordered),
        "p95": ordered[max(0, int(len(ordered) * 0.95) - 1)],
        "p99": ordered[max(0, int(len(ordered) * 0.99) - 1)],
    }


def measure_allocations(operation, repetitions: int) -> dict[str, object]:
    """Measure traced peak allocations without making the benchmark mandatory on every host."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if tracemalloc is None:
        return {
            "schema": "simplicio.fast.allocation-metric/v1",
            "status": "partial",
            "reason": "tracemalloc_unavailable",
            "repetitions": repetitions,
            "peak_bytes": None,
        }
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    samples: list[int] = []
    try:
        for _ in range(repetitions):
            tracemalloc.reset_peak()
            operation()
            _, peak = tracemalloc.get_traced_memory()
            samples.append(int(peak))
    finally:
        if not was_tracing:
            tracemalloc.stop()
    return {
        "schema": "simplicio.fast.allocation-metric/v1",
        "status": "complete",
        "reason": None,
        "repetitions": repetitions,
        "peak_bytes": _allocation_percentiles(samples),
    }


def generate_project(root: Path, symbols: int) -> None:
    files = max(1, (symbols + 99) // 100)
    package = root / "app"
    package.mkdir(parents=True)
    for file_index in range(files):
        start = file_index * 100
        functions = []
        for offset in range(min(100, symbols - start)):
            index = start + offset
            functions.append(
                f"def update_user_{index}(user_id: int) -> int:\n    return user_id + {index}\n"
            )
        (package / f"service_{file_index:04d}.py").write_text(
            "\n".join(functions), encoding="utf-8"
        )


def measure_shared_slots(
    root: Path, snapshot_path: Path, slots: int, repetitions: int = 10
) -> dict[str, float | int | str]:
    store = WorkspaceStore(root, root / ".bench-store")
    base = store.build_base()
    wall: list[float] = []
    cpu: list[float] = []
    rss = peak_rss_kib()
    for _ in range(repetitions):
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=slots) as executor:
            list(
                executor.map(
                    lambda index: store.create_overlay(
                        f"slot-{slots}-{index}", base.generation_id
                    ),
                    range(slots),
                )
            )
        wall.append((time.perf_counter() - wall_start) * 1000)
        cpu.append((time.process_time() - cpu_start) * 1000)
        observed = peak_rss_kib()
        if observed is not None:
            rss = max(rss or observed, observed)
    return {
        "slots": slots,
        "repetitions": repetitions,
        "mode": "one-canonical-base-plus-isolated-overlays",
        "wall_median_ms": statistics.median(wall),
        "wall_p95_ms": sorted(wall)[max(0, int(repetitions * 0.95) - 1)],
        "cpu_median_ms": statistics.median(cpu),
        "peak_rss_kib": rss,
        "peak_rss_reason": None
        if rss is not None
        else "native process RSS unavailable on this host",
        "base_generation": base.generation_id,
    }


def baseline_query(root: Path, term: str) -> int:
    matches = 0
    for path in source_files(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        matches += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and term.casefold() in node.name.casefold()
        )
    return matches


def measure(operation, repetitions: int) -> dict[str, float | int]:
    wall: list[float] = []
    cpu: list[float] = []
    for _ in range(repetitions):
        wall_start = time.perf_counter()
        cpu_start = time.process_time()
        operation()
        wall.append((time.perf_counter() - wall_start) * 1000)
        cpu.append((time.process_time() - cpu_start) * 1000)
    return {
        "repetitions": repetitions,
        "wall_median_ms": statistics.median(wall),
        "wall_p95_ms": sorted(wall)[max(0, int(repetitions * 0.95) - 1)],
        "cpu_median_ms": statistics.median(cpu),
    }


def process_usage() -> dict[str, int | str | None]:
    peak_rss = peak_rss_metric()
    usage = resource.getrusage(resource.RUSAGE_SELF) if resource is not None else None
    return {
        "peak_rss_kib": peak_rss["value"],
        "peak_rss_reason": peak_rss["reason"],
        "minor_page_faults": int(getattr(usage, "ru_minflt", 0)) if usage else None,
        "major_page_faults": int(getattr(usage, "ru_majflt", 0)) if usage else None,
    }


def run_size(size: int, repetitions: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "project"
        generate_project(root, size)
        snapshot_path = root / ".simplicio/fast/project.sfast"
        baseline = measure(lambda: baseline_query(root, "update_user"), repetitions)

        baseline_allocation = measure_allocations(
            lambda: baseline_query(root, "update_user"), repetitions
        )
        cold = build_snapshot(root, snapshot_path)
        with Snapshot(snapshot_path) as snapshot:
            mapped = measure(lambda: snapshot.find("update_user"), repetitions)

            mapped_allocation = measure_allocations(
                lambda: snapshot.find("update_user"), repetitions
            )
        warm_build = build_snapshot(root, snapshot_path)
        changed_file = root / "app/service_0000.py"
        changed_file.write_text(
            changed_file.read_text(encoding="utf-8")
            + "\ndef deactivate_user(user_id: int) -> bool:\n    return user_id >= 0\n",
            encoding="utf-8",
        )
        incremental = build_snapshot(root, snapshot_path)
        with Snapshot(snapshot_path) as snapshot:
            changed_visible = len(snapshot.find("deactivate_user")) == 1
        peak_rss = peak_rss_metric()
        status = "complete" if peak_rss["reason"] is None else "partial"
        return {
            "schema": "simplicio.fast.benchmark/v1",
            "status": status,
            "symbols_requested": size,
            "files": cold.files,
            "repetitions": repetitions,
            "environment": {
                "python": sys.version.split()[0],
                "generated_files": cold.files,
                "peak_rss_kib": peak_rss["value"],
                "peak_rss_reason": peak_rss["reason"],
                "metrics_status": status,
            },
            "baseline_ast_query": baseline,
            "baseline_ast_query_allocation": baseline_allocation,
            "snapshot_cold_build": asdict(cold),
            "snapshot_mmap_query": mapped,
            "snapshot_mmap_query_allocation": mapped_allocation,
            "snapshot_no_change_build": asdict(warm_build),
            "snapshot_one_file_change": asdict(incremental),
            "changed_symbol_visible": changed_visible,
            "shared_base_overlay_slots": [
                measure_shared_slots(root, snapshot_path, slots)
                for slots in SHARED_BASE_OVERLAY_SLOTS
            ],
            "query_speedup": baseline["wall_median_ms"] / mapped["wall_median_ms"],
            "query_cpu_reduction_percent": (
                1 - mapped["cpu_median_ms"] / baseline["cpu_median_ms"]
            )
            * 100,
            "usage": process_usage(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes", default="1000,10000,100000", help="comma-separated symbol counts"
    )
    parser.add_argument("--repetitions", type=int, default=10)
    args = parser.parse_args()
    if args.repetitions < 10:
        parser.error("--repetitions must be at least 10")
    sizes = [int(value) for value in args.sizes.split(",") if value.strip()]
    if not sizes or any(size < 1 for size in sizes):
        parser.error("--sizes must contain positive integers")
    result = {
        "schema": "simplicio.fast.benchmark/v1",
        "environment": {"python": sys.version.split()[0], "usage": process_usage()},
        "workload": {
            "sizes": sizes,
            "repetitions": args.repetitions,
            "query": "update_user",
        },
        "runs": [run_size(size, args.repetitions) for size in sizes],
    }
    output = Path("benchmarks/results/latest.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
