"""Concurrency test for `simplicio-mapper prototype-context` (issue #286
mapper-scale follow-up: "1.000 queries concorrentes").

Hammers `build_prototype_context()` 1000 times concurrently against the
committed `python-minimal` fixture
(`contracts/mapper-artifacts/v1/fixtures/python-minimal/source`) and asserts:

- zero exceptions across all 1000 calls;
- every returned payload round-trips through `json.dumps`/`json.loads`
  without corruption (same schema, same target_files, valid context_hash);
- a real, measured p50/p95 latency is reported (not estimated) -- printed to
  stdout so `pytest -s` / `python -m unittest -v` output carries the number,
  and also asserted to be non-negative/finite so a broken timer would fail
  the test rather than silently pass.

The fixture is copied into a fresh temp directory once and shared read-only
across all 1000 calls -- each call still exercises the SAME on-disk
`.simplicio/cache` (`diskcache.Cache`, see `simplicio_mapper/cache.py`)
concurrently, which is the actual concurrency surface this test is meant to
prove safe: many threads racing to read/populate the same file-processing
cache and the same `context-cache.json` must never corrupt either.

Uses `concurrent.futures.ThreadPoolExecutor` (not `multiprocessing`):
`build_prototype_context` is I/O-bound (disk reads, `diskcache`/sqlite,
short-lived `git` subprocesses) rather than CPU-bound, so threads exercise
the real concurrency hazard (shared on-disk cache, shared filesystem) without
the pickling overhead multiprocessing would add for no benefit here.

Run: python3 -m unittest tests.python.test_prototype_context_concurrency -v
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.prototype_context import (  # noqa: E402
    PROTOTYPE_CONTEXT_SCHEMA,
    build_prototype_context,
)

FIXTURE_SOURCE = ROOT / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"
CONCURRENT_CALL_COUNT = 1000
MAX_WORKERS = 64


class PrototypeContextConcurrencyTest(unittest.TestCase):
    """System: 1000 real concurrent `build_prototype_context()` calls."""

    @classmethod
    def setUpClass(cls) -> None:
        if not FIXTURE_SOURCE.is_dir():  # pragma: no cover - guards a moved/renamed fixture
            raise unittest.SkipTest(f"fixture not found: {FIXTURE_SOURCE}")
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = os.path.join(cls._tmp.name, "repo")
        shutil.copytree(str(FIXTURE_SOURCE), cls.root)
        # Warm up process-global, one-time costs (tiktoken BPE load if
        # installed, first diskcache open) OUTSIDE the timed section, so the
        # reported p50/p95 measures steady-state concurrent latency, not a
        # one-off cold-start cost every process pays exactly once.
        build_prototype_context(cls.root, type_="bug", arg="src/app.py")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_1000_concurrent_generations_no_crash_no_corruption(self) -> None:
        import time

        def _one_call(index: int) -> tuple[int, float, dict]:
            # Alternate the query target across the 3 real fixture files so
            # the run also exercises different resolution paths (path vs
            # symbol) concurrently, not just one repeated identical call.
            arg = ["src/app.py", "src/util.py", "greet"][index % 3]
            type_ = ["bug", "workflow", "ui"][index % 3]
            started = time.perf_counter()
            payload = build_prototype_context(self.root, type_=type_, arg=arg)
            elapsed = time.perf_counter() - started
            return index, elapsed, payload

        durations: list[float] = []
        errors: list[BaseException] = []
        payloads_by_index: dict[int, dict] = {}

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(_one_call, i) for i in range(CONCURRENT_CALL_COUNT)]
            for future in as_completed(futures):
                try:
                    index, elapsed, payload = future.result()
                except BaseException as exc:  # noqa: BLE001 - collect every failure, never let one hide others
                    errors.append(exc)
                    continue
                durations.append(elapsed)
                payloads_by_index[index] = payload

        # 1. Zero exceptions across all 1000 real calls.
        self.assertEqual(
            errors,
            [],
            f"{len(errors)}/{CONCURRENT_CALL_COUNT} concurrent prototype-context calls raised: {errors[:3]!r}",
        )
        self.assertEqual(len(durations), CONCURRENT_CALL_COUNT)
        self.assertEqual(len(payloads_by_index), CONCURRENT_CALL_COUNT)

        # 2. No corrupted output: every payload round-trips through JSON and
        # carries the expected schema/shape/hash for its own query.
        for index, payload in payloads_by_index.items():
            arg = ["src/app.py", "src/util.py", "greet"][index % 3]
            expected_type = ["bug", "workflow", "ui"][index % 3]
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            round_tripped = json.loads(serialized)
            self.assertEqual(round_tripped, payload)
            self.assertEqual(payload["schema"], PROTOTYPE_CONTEXT_SCHEMA)
            self.assertEqual(payload["type"], expected_type)
            self.assertIn("context_hash", payload)
            self.assertEqual(len(payload["context_hash"]), 64)
            self.assertTrue(payload["target_files"])
            if arg != "greet":
                self.assertEqual(payload["target_files"], [arg])

        # 3. Real, measured p50/p95 latency -- printed for CI logs and
        # asserted sane (finite, non-negative, p95 >= p50) so a broken timer
        # fails the test instead of silently reporting garbage.
        durations.sort()
        p50 = statistics.median(durations)
        p95_index = min(len(durations) - 1, int(round(0.95 * (len(durations) - 1))))
        p95 = durations[p95_index]
        total = sum(durations)
        print(
            f"\n[prototype-context concurrency] n={len(durations)} "
            f"p50={p50 * 1000:.3f}ms p95={p95 * 1000:.3f}ms "
            f"min={durations[0] * 1000:.3f}ms max={durations[-1] * 1000:.3f}ms "
            f"sum={total:.3f}s"
        )
        self.assertGreaterEqual(p50, 0.0)
        self.assertGreaterEqual(p95, p50)
        self.assertTrue(p95 < 30.0, f"p95 latency implausibly high: {p95}s")


if __name__ == "__main__":
    unittest.main()
