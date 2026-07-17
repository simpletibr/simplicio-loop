"""Unit tests for simplicio_mapper.mapper.async_io (ADR-009 / issue #235
plan steps 3-4, partial -- bounded-concurrency async file-read primitive).

Covers, per the task's acceptance criteria:

(a) correctness -- results match a plain synchronous read for the same file
    set.
(b) bounded concurrency -- peak in-flight reads never exceeds the
    configured limit.
(c) per-file failure isolation -- one bad file does not abort the batch.
(d) timeout -- cancels cleanly, no leaked tasks.
(e) benchmark -- measurable wall-time comparison against a sequential read
    loop (numbers documented honestly in the test output / PR body, not
    asserted as a hard regression gate since I/O timing is environment
    dependent).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.async_io import (  # noqa: E402
    DEFAULT_MAX_CONCURRENCY,
    FileReadResult,
    default_max_concurrency,
    read_files_concurrently,
    read_files_concurrently_sync,
)


def _write_files(tmpdir: str, count: int, body: str = "hello world\n") -> list[str]:
    paths = []
    for i in range(count):
        path = os.path.join(tmpdir, f"file_{i:04d}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(f"{body}{i}\n")
        paths.append(path)
    return paths


class DefaultConcurrencyTests(unittest.TestCase):
    def test_default_is_bounded_by_32_and_cpu_heuristic(self):
        cap = default_max_concurrency()
        self.assertGreaterEqual(cap, 1)
        self.assertLessEqual(cap, 32)
        self.assertEqual(cap, min(32, (os.cpu_count() or 1) * 4))

    def test_module_constant_matches_function(self):
        self.assertEqual(DEFAULT_MAX_CONCURRENCY, default_max_concurrency())


class EmptyInputTests(unittest.TestCase):
    def test_empty_paths_returns_empty_list(self):
        results = asyncio.run(read_files_concurrently([]))
        self.assertEqual(results, [])


class CorrectnessTests(unittest.TestCase):
    """(a) results match a plain synchronous read for the same file set."""

    def test_matches_plain_sync_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_files(tmpdir, 25)

            expected = []
            for path in paths:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    expected.append(handle.read())

            results = asyncio.run(read_files_concurrently(paths, max_concurrency=4))

            self.assertEqual(len(results), len(paths))
            for path, exp_content, result in zip(paths, expected, results):
                self.assertEqual(result.path, path)
                self.assertTrue(result.ok)
                self.assertIsNone(result.error)
                self.assertEqual(result.content, exp_content)

    def test_sync_wrapper_matches_async(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_files(tmpdir, 10)
            results = read_files_concurrently_sync(paths, max_concurrency=3)
            self.assertEqual(len(results), 10)
            self.assertTrue(all(r.ok for r in results))

    def test_result_order_matches_input_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_files(tmpdir, 15)
            results = asyncio.run(read_files_concurrently(paths, max_concurrency=5))
            self.assertEqual([r.path for r in results], paths)

    def test_invalid_max_concurrency_raises(self):
        with self.assertRaises(ValueError):
            asyncio.run(read_files_concurrently(["/tmp/x"], max_concurrency=0))
        with self.assertRaises(ValueError):
            asyncio.run(read_files_concurrently(["/tmp/x"], max_concurrency=-1))


class BoundedConcurrencyTests(unittest.TestCase):
    """(b) concurrency is actually bounded -- instrument with a counter/lock
    to prove peak concurrent in-flight reads never exceeds the configured
    limit."""

    def test_peak_in_flight_never_exceeds_limit(self):
        limit = 4
        file_count = 40
        lock = threading.Lock()
        state = {"current": 0, "peak": 0}

        def _instrumented_read(path: str) -> str:
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            try:
                # Small sleep to widen the window where overlap would show
                # up if the semaphore were not actually bounding things.
                time.sleep(0.01)
                with open(path, encoding="utf-8", errors="replace") as handle:
                    return handle.read()
            finally:
                with lock:
                    state["current"] -= 1

        async def _run() -> list[FileReadResult]:
            import simplicio_mapper.mapper.async_io as async_io_mod

            original = async_io_mod._read_sync
            async_io_mod._read_sync = _instrumented_read
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    paths = _write_files(tmpdir, file_count)
                    return await read_files_concurrently(paths, max_concurrency=limit)
            finally:
                async_io_mod._read_sync = original

        results = asyncio.run(_run())

        self.assertEqual(len(results), file_count)
        self.assertTrue(all(r.ok for r in results))
        self.assertLessEqual(state["peak"], limit)
        # Sanity: with 40 files, a limit of 4, and a 10ms artificial delay,
        # concurrency should actually engage (peak > 1) rather than the
        # semaphore being a no-op that happens to stay under the cap by
        # accident of scheduling.
        self.assertGreater(state["peak"], 1)


class PerFileFailureIsolationTests(unittest.TestCase):
    """(c) a per-file read error doesn't abort the batch and is surfaced
    per-file."""

    def test_missing_file_does_not_abort_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            good_paths = _write_files(tmpdir, 5)
            missing_path = os.path.join(tmpdir, "does_not_exist.txt")
            paths = good_paths[:2] + [missing_path] + good_paths[2:]

            results = asyncio.run(read_files_concurrently(paths, max_concurrency=3))

            self.assertEqual(len(results), len(paths))
            by_path = {r.path: r for r in results}

            failed = by_path[missing_path]
            self.assertFalse(failed.ok)
            self.assertIsNone(failed.content)
            self.assertIsNotNone(failed.error)
            self.assertIn("Error", failed.error or "")

            for good_path in good_paths:
                good_result = by_path[good_path]
                self.assertTrue(good_result.ok)
                self.assertIsNotNone(good_result.content)

    def test_permission_style_error_isolated(self):
        # Simulate an unreadable "file" by pointing at a directory instead
        # (opening a directory for text read raises IsADirectoryError on
        # POSIX / PermissionError-ish on Windows -- either way, an OSError
        # subclass), proving the isolation holds for OS-level failures
        # beyond plain "missing file".
        with tempfile.TemporaryDirectory() as tmpdir:
            good_paths = _write_files(tmpdir, 3)
            bad_dir = os.path.join(tmpdir, "a_directory")
            os.mkdir(bad_dir)
            paths = good_paths + [bad_dir]

            results = asyncio.run(read_files_concurrently(paths, max_concurrency=2))
            by_path = {r.path: r for r in results}

            self.assertFalse(by_path[bad_dir].ok)
            self.assertIsNotNone(by_path[bad_dir].error)
            for good_path in good_paths:
                self.assertTrue(by_path[good_path].ok)


class TimeoutCancellationTests(unittest.TestCase):
    """(d) timeout cancels cleanly with no leaked tasks/threads."""

    def test_timeout_raises_and_cancels_in_flight(self):
        async def _run():
            import simplicio_mapper.mapper.async_io as async_io_mod

            def _slow_read(path: str) -> str:
                time.sleep(1.0)
                return "slow"

            original = async_io_mod._read_sync
            async_io_mod._read_sync = _slow_read
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    paths = _write_files(tmpdir, 8)
                    start = time.perf_counter()
                    with self.assertRaises(asyncio.TimeoutError):
                        await read_files_concurrently(
                            paths, max_concurrency=4, timeout=0.05
                        )
                    elapsed = time.perf_counter() - start
                    # Should time out promptly, not wait for all slow reads.
                    self.assertLess(elapsed, 0.9)
            finally:
                async_io_mod._read_sync = original

        asyncio.run(_run())

    def test_no_leaked_tasks_after_timeout(self):
        async def _run():
            with tempfile.TemporaryDirectory() as tmpdir:
                paths = _write_files(tmpdir, 5)

                async def _hang(path: str) -> str:
                    await asyncio.sleep(5)
                    return "never"

                import simplicio_mapper.mapper.async_io as async_io_mod

                async def _to_thread_stub(path, semaphore):
                    async with semaphore:
                        await asyncio.sleep(5)
                        return FileReadResult(
                            path=path, content="x", error=None, ok=True, duration_s=0.0
                        )

                original = async_io_mod._read_one
                async_io_mod._read_one = _to_thread_stub
                try:
                    before = {
                        t
                        for t in asyncio.all_tasks()
                        if t is not asyncio.current_task()
                    }
                    with self.assertRaises(asyncio.TimeoutError):
                        await read_files_concurrently(
                            paths, max_concurrency=2, timeout=0.05
                        )
                    # Give cancellation a moment to fully propagate.
                    await asyncio.sleep(0.05)
                    after = {
                        t
                        for t in asyncio.all_tasks()
                        if t is not asyncio.current_task()
                    }
                    leaked = after - before
                    leaked_alive = [t for t in leaked if not t.done()]
                    self.assertEqual(
                        leaked_alive, [], "no tasks should remain running after timeout"
                    )
                finally:
                    async_io_mod._read_one = original

        asyncio.run(_run())

    def test_no_timeout_means_no_deadline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_files(tmpdir, 5)
            results = asyncio.run(read_files_concurrently(paths, timeout=None))
            self.assertEqual(len(results), 5)
            self.assertTrue(all(r.ok for r in results))


class BenchmarkTests(unittest.TestCase):
    """(e) benchmark comparing this against a plain sequential read loop on
    a synthetic set of ~200-500 small files.

    Not a hard perf gate (I/O timing is environment-dependent and this is a
    unit test, not scripts/*_benchmark.py) -- prints the measured numbers so
    they show up in ``-v`` test output / CI logs and are reported honestly
    in the PR, per the task's instruction not to fabricate a speedup.
    """

    def test_concurrent_vs_sequential_wall_time(self):
        file_count = 300
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = _write_files(tmpdir, file_count, body="x" * 200 + "\n")

            # Sequential baseline: plain synchronous read loop, same helper
            # semantics (open + read), no concurrency at all.
            start = time.perf_counter()
            sequential_results = []
            for path in paths:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    sequential_results.append(handle.read())
            sequential_elapsed = time.perf_counter() - start

            # Concurrent primitive under test.
            start = time.perf_counter()
            concurrent_results = asyncio.run(
                read_files_concurrently(paths, max_concurrency=32)
            )
            concurrent_elapsed = time.perf_counter() - start

            self.assertEqual(len(concurrent_results), file_count)
            self.assertTrue(all(r.ok for r in concurrent_results))

            speedup = (
                sequential_elapsed / concurrent_elapsed
                if concurrent_elapsed > 0
                else float("inf")
            )

            print(
                f"\n[benchmark] {file_count} files -- "
                f"sequential={sequential_elapsed:.4f}s "
                f"concurrent={concurrent_elapsed:.4f}s "
                f"speedup={speedup:.2f}x "
                "(honest note: on fast local disk / OS page cache, small "
                "in-memory-sized files may show a modest or even negative "
                "speedup vs. a tight sequential loop, since asyncio/thread "
                "scheduling overhead can outweigh I/O-wait savings when "
                "there is barely any I/O-wait to hide -- this is expected "
                "and documented in ADR-009's 'Negativas' section, not a "
                "test bug)."
            )

            # No hard assertion on speedup direction/magnitude: this is an
            # honest measurement, not a fabricated guarantee. We only assert
            # both paths produced correct, complete results.
            self.assertEqual(len(sequential_results), file_count)


if __name__ == "__main__":
    unittest.main()
