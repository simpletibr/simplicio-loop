import ctypes
import sys
import types
import unittest
from unittest.mock import patch

from benchmarks.compare_fast import environment_receipt, timed
from benchmarks.compare_fast import run

from benchmarks.run import (
    SHARED_BASE_OVERLAY_SLOTS,
    measure_allocations,
    peak_rss_kib,
    peak_rss_metric,
    run_size,
)


class _FakeFunction:
    def __init__(self, result: bool) -> None:
        self.result = result

    def __call__(self, _process, counters, _size) -> bool:
        if self.result:
            # ``ctypes.wintypes.DWORD`` follows the host C ABI when a Windows
            # path is simulated on Linux, so a hard-coded byte offset is not
            # portable. Assign through the exact structure passed by byref.
            counters._obj.PeakWorkingSetSize = 8192
        return self.result


class _FakeWindowsLibraries:
    class kernel32:
        @staticmethod
        def GetCurrentProcess() -> object:
            return object()

    def __init__(self, result: bool) -> None:
        self.psapi = type(
            "Psapi", (), {"GetProcessMemoryInfo": _FakeFunction(result)}
        )()


class BenchmarkResourceTest(unittest.TestCase):
    def test_timed_receipt_includes_p50_p95_and_p99(self) -> None:
        receipt = timed(lambda: "context", repetitions=10)
        wall = receipt["wall_ms"]
        self.assertIn("median", wall)
        self.assertIn("p95", wall)
        self.assertIn("p99", wall)
        self.assertLessEqual(wall["median"], wall["p95"])
        self.assertLessEqual(wall["p95"], wall["p99"])

    def test_shared_base_overlay_slot_matrix_is_stable(self) -> None:
        self.assertEqual((1, 20, 100), SHARED_BASE_OVERLAY_SLOTS)

    def test_python_benchmark_reports_identity_and_blocked_status(self) -> None:
        receipt = run(files=2, functions=2, repetitions=10)
        self.assertEqual("partial", receipt["status"])
        provenance = receipt["provenance"]
        self.assertEqual(64, len(provenance["corpus_sha256"]))
        self.assertEqual(10, len(provenance["repetition_order"]))
        self.assertEqual(list(range(1, 11)), sorted(provenance["repetition_order"]))
        self.assertEqual(0, provenance["warmup_repetitions"])
        self.assertEqual("blocked", receipt["scenarios"]["full_standalone"]["status"])

    def test_environment_receipt_has_frozen_raw_identity_fields(self) -> None:
        receipt = environment_receipt()
        self.assertEqual("simplicio.fast.environment/v1", receipt["schema"])
        self.assertTrue(receipt["python"])
        self.assertTrue(receipt["python_implementation"])
        self.assertTrue(receipt["platform"])
        self.assertIn("executable", receipt)
        self.assertIn("cpu_count", receipt)

    def test_posix_keeps_resource_getrusage(self) -> None:
        fake_resource = types.SimpleNamespace(
            RUSAGE_SELF=0,
            getrusage=lambda _kind: types.SimpleNamespace(ru_maxrss=2048),
        )
        with patch.dict(sys.modules, {"resource": fake_resource}):
            metric = peak_rss_metric("linux")
            with patch.object(sys, "platform", "linux"):
                numeric_value = peak_rss_kib()
        self.assertIsInstance(metric["value"], int)
        self.assertIsNone(metric["reason"])
        self.assertEqual(metric["value"], numeric_value)

    def test_windows_process_memory_api_returns_kib(self) -> None:
        with patch.object(sys, "platform", "win32"):
            with patch.object(
                ctypes, "windll", _FakeWindowsLibraries(True), create=True
            ):
                metric = peak_rss_metric()
        self.assertEqual(8, metric["value"])
        self.assertIsNone(metric["reason"])

    def test_windows_failure_is_a_machine_readable_partial_metric(self) -> None:
        with patch.object(sys, "platform", "win32"):
            with patch.object(
                ctypes, "windll", _FakeWindowsLibraries(False), create=True
            ):
                metric = peak_rss_metric()
        self.assertIsNone(metric["value"])
        self.assertEqual("windows_get_process_memory_info_failed", metric["reason"])

    def test_allocation_receipt_contains_percentiles_and_raw_samples(self) -> None:
        calls = 0

        def operation() -> None:
            nonlocal calls
            calls += 1
            [index * 2 for index in range(32)]

        receipt = measure_allocations(operation, repetitions=10)
        self.assertEqual("complete", receipt["status"])
        self.assertEqual(10, receipt["repetitions"])
        peak = receipt["peak_bytes"]
        self.assertEqual(10, len(peak["samples"]))
        self.assertLessEqual(peak["median"], peak["p95"])
        self.assertLessEqual(peak["p95"], peak["p99"])
        self.assertEqual(10, calls)

    def test_allocation_receipt_is_partial_when_tracemalloc_is_unavailable(
        self,
    ) -> None:
        with patch("benchmarks.run.tracemalloc", None):
            receipt = measure_allocations(lambda: None, repetitions=10)
        self.assertEqual("partial", receipt["status"])
        self.assertEqual("tracemalloc_unavailable", receipt["reason"])
        self.assertIsNone(receipt["peak_bytes"])

    def test_run_size_emits_allocation_receipts(self) -> None:
        receipt = run_size(1000, repetitions=10)
        for name in ("baseline_ast_query_allocation", "snapshot_mmap_query_allocation"):
            metric = receipt[name]
            self.assertEqual("simplicio.fast.allocation-metric/v1", metric["schema"])
            self.assertEqual("complete", metric["status"])
            self.assertEqual(10, metric["repetitions"])
            self.assertEqual(10, len(metric["peak_bytes"]["samples"]))


if __name__ == "__main__":
    unittest.main()
