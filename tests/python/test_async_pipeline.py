"""Tests for simplicio_mapper.mapper.async_pipeline (ADR-009, issue #235
plan steps 4-6).

Covers the acceptance criteria called out in the ADR and in the issue:
bounded concurrency (never unbounded), clean cancellation (no orphaned
tasks, semaphore released), per-file timeout fail-soft (one slow file
never hangs the whole run), output equivalence with the sync
``_build_file_inventory`` path (the regression gate this module must never
break), and the ``uvloop`` opt-in/fallback selection logic.

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
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import orjson  # noqa: E402

from simplicio_mapper.mapper.async_pipeline import (  # noqa: E402
    _install_uvloop_if_available,
    _max_concurrent_files,
    _per_file_timeout_s,
    build_artifacts_async,
    build_file_inventory_async,
)
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402
from simplicio_mapper.mapper.parse import _build_file_inventory  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _make_tracking_parse(delay: float = 0.05, slow_rel: str | None = None, slow_delay: float = 0.0):
    """Build a drop-in replacement for ``_cached_parse_file`` that tracks
    how many calls are concurrently in flight (for the bounded-concurrency
    test) and can optionally make one specific file artificially slow (for
    the timeout test), while returning a shape compatible with what real
    callers of ``_cached_parse_file`` expect back.
    """
    lock = threading.Lock()
    state = {"current": 0, "max": 0, "calls": 0}

    def _tracking_parse_file(cwd, abs_path, rel, stat, cache, contents=None):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
            state["calls"] += 1
        try:
            time.sleep(slow_delay if (slow_rel is not None and rel == slow_rel) else delay)
        finally:
            with lock:
                state["current"] -= 1
        return {
            "language": "python",
            "file_hash": f"hash:{rel}",
            "imports": [],
            "exports": [],
            "text_preview": "",
        }

    return _tracking_parse_file, state


class BoundedConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for i in range(24):
            _write(self.dir, f"src/mod_{i:02d}.py", f"def f_{i}():\n    return {i}\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_never_exceeds_the_configured_semaphore_cap(self) -> None:
        tracking_parse, state = _make_tracking_parse(delay=0.05)
        with mock.patch(
            "simplicio_mapper.mapper.async_pipeline._cached_parse_file",
            side_effect=tracking_parse,
        ):
            files = await build_file_inventory_async(
                str(self.dir), {"name": "fixture"}, {}, None, max_concurrent=4,
            )
        self.assertEqual(len(files), 24)
        self.assertLessEqual(state["max"], 4)
        # Concurrency actually happened (not accidentally serialized) --
        # otherwise this test would pass trivially for any cap.
        self.assertGreater(state["max"], 1)
        self.assertEqual(state["calls"], 24)

    async def test_default_cap_is_min_32_and_cpu_scaled(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES", None)
            cap = _max_concurrent_files()
        expected = min(32, (os.cpu_count() or 4) * 4)
        self.assertEqual(cap, expected)

    async def test_env_override_controls_the_cap(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "7"}):
            self.assertEqual(_max_concurrent_files(), 7)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "not-a-number"}):
            self.assertEqual(_max_concurrent_files(), min(32, (os.cpu_count() or 4) * 4))
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "0"}):
            self.assertEqual(_max_concurrent_files(), min(32, (os.cpu_count() or 4) * 4))


class TimeoutTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for i in range(6):
            _write(self.dir, f"src/fast_{i}.py", f"def f_{i}():\n    return {i}\n")
        _write(self.dir, "src/slow.py", "def slow():\n    return 'slow'\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_one_slow_file_times_out_without_hanging_the_run(self) -> None:
        tracking_parse, state = _make_tracking_parse(delay=0.01, slow_rel="src/slow.py", slow_delay=5.0)
        degraded: dict = {}
        start = time.monotonic()
        with mock.patch(
            "simplicio_mapper.mapper.async_pipeline._cached_parse_file",
            side_effect=tracking_parse,
        ):
            files = await build_file_inventory_async(
                str(self.dir),
                {"name": "fixture"},
                {},
                None,
                max_concurrent=8,
                timeout_s=0.15,
                degraded=degraded,
            )
        elapsed = time.monotonic() - start
        # The slow file sleeps 5s; the whole run must finish in a small
        # fraction of that (bounded by the 0.15s per-file timeout, not by
        # the slow file's actual duration).
        self.assertLess(elapsed, 2.0)
        paths = {f.path for f in files}
        self.assertNotIn("src/slow.py", paths)
        for i in range(6):
            self.assertIn(f"src/fast_{i}.py", paths)
        self.assertIn("timed_out_files", degraded)
        self.assertIn("src/slow.py", degraded["timed_out_files"])

    async def test_per_file_timeout_env_override(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_FILE_TIMEOUT_S": "1.5"}):
            self.assertEqual(_per_file_timeout_s(), 1.5)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_FILE_TIMEOUT_S": "garbage"}):
            self.assertEqual(_per_file_timeout_s(), 30.0)


class CancellationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for i in range(10):
            _write(self.dir, f"src/mod_{i:02d}.py", f"def f_{i}():\n    return {i}\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_cancelling_the_pipeline_propagates_cleanly_and_releases_the_semaphore(self) -> None:
        tracking_parse, state = _make_tracking_parse(delay=0.5)
        with mock.patch(
            "simplicio_mapper.mapper.async_pipeline._cached_parse_file",
            side_effect=tracking_parse,
        ):
            task = asyncio.ensure_future(
                build_file_inventory_async(
                    str(self.dir), {"name": "fixture"}, {}, None, max_concurrent=3,
                )
            )
            # Let a handful of tasks actually start (acquire the semaphore)
            # before cancelling, so this exercises real in-flight state,
            # not just an empty task list.
            await asyncio.sleep(0.05)
            self.assertGreater(state["current"], 0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            # Give the (unstoppable, per ADR-009's documented to_thread
            # limitation) background OS threads a moment to actually
            # finish their current sleep so we can observe steady state.
            await asyncio.sleep(0.6)

        # No task spawned by the pipeline should still be alive/pending
        # once the OS threads have had a chance to unwind.
        current = asyncio.current_task()
        leftover = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        self.assertEqual(leftover, [])
        # The semaphore itself must have been released by every acquirer
        # (via `finally`) rather than leaking permits -- confirmed
        # indirectly: state["current"] must have returned to 0, i.e. no
        # worker is stuck holding a slot forever.
        self.assertEqual(state["current"], 0)


class OutputEquivalenceTest(unittest.TestCase):
    """Regression gate (ADR-009): the async inventory path must produce
    output structurally identical to the existing sync
    ``_build_file_inventory`` for the same input tree.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "src/index.js", "const express = require('express');\nexpress();\n")
        _write(self.dir, "tests/index.test.js", "test('smoke', () => {});\n")
        _write(self.dir, "src/util/helpers.py", "import os\n\n\ndef helper():\n    return os.getcwd()\n")
        _write(self.dir, "package.json", '{"name": "fixture", "dependencies": {"express": "^4.0.0"}}')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_async_inventory_matches_sync_inventory_byte_for_byte(self) -> None:
        pkg = {"name": "fixture", "dependencies": {"express": "^4.0.0"}}
        sync_files = _build_file_inventory(str(self.dir), pkg, {}, None)
        async_files = asyncio.run(
            build_file_inventory_async(str(self.dir), pkg, {}, None)
        )
        sync_dicts = [f.to_dict() for f in sync_files]
        async_dicts = [f.to_dict() for f in async_files]
        self.assertEqual(sync_dicts, async_dicts)
        # Same sort order too, not just the same set.
        self.assertEqual([f.path for f in sync_files], [f.path for f in async_files])

    def test_async_inventory_matches_sync_inventory_with_a_shared_cache(self) -> None:
        from simplicio_mapper.cache import FileProcessingCache

        pkg = {"name": "fixture"}
        cache_dir = self.dir / ".cache-sync"
        with FileProcessingCache(cache_dir) as cache:
            sync_files = _build_file_inventory(str(self.dir), pkg, {}, cache)

        cache_dir_async = self.dir / ".cache-async"
        with FileProcessingCache(cache_dir_async) as cache:
            async_files = asyncio.run(
                build_file_inventory_async(str(self.dir), pkg, {}, cache)
            )

        self.assertEqual(
            [f.to_dict() for f in sync_files],
            [f.to_dict() for f in async_files],
        )

    def test_build_artifacts_json_artifacts_are_byte_identical_modulo_timestamp(self) -> None:
        # build_artifacts() is now itself a thin adapter over
        # build_artifacts_async() (ADR-009 plan step 8), so this also acts
        # as an end-to-end smoke test of the full pipeline, not only the
        # inventory stage.
        first = build_artifacts(str(self.dir))
        second = asyncio.run(build_artifacts_async(str(self.dir)))

        def _normalize(artifacts: dict) -> bytes:
            project_map = dict(artifacts["project_map"])
            project_map.pop("generated_at", None)
            precedent_index = dict(artifacts["precedent_index"])
            precedent_index.pop("generated_at", None)
            symbol_index = dict(artifacts["symbol_index"])
            symbol_index.pop("generated_at", None)
            call_graph = dict(artifacts["call_graph"])
            call_graph.pop("generated_at", None)
            architecture_inventory = dict(artifacts["architecture_inventory"])
            architecture_inventory.pop("generated_at", None)
            return orjson.dumps(
                {
                    "project_map": project_map,
                    "precedent_index": precedent_index,
                    "architecture_inventory": architecture_inventory,
                    "symbol_index": symbol_index,
                    "call_graph": call_graph,
                },
                option=orjson.OPT_SORT_KEYS,
            )

        self.assertEqual(_normalize(first), _normalize(second))


class UvloopSelectionTest(unittest.TestCase):
    def test_windows_never_attempts_uvloop(self) -> None:
        with mock.patch("simplicio_mapper.mapper.async_pipeline.sys.platform", "win32"):
            self.assertFalse(_install_uvloop_if_available())

    def test_non_windows_without_uvloop_installed_falls_back_cleanly(self) -> None:
        # Force the import to fail regardless of whether uvloop happens to
        # be installed in this environment, so the test is deterministic.
        with mock.patch("simplicio_mapper.mapper.async_pipeline.sys.platform", "linux"), \
                mock.patch.dict(sys.modules, {"uvloop": None}):
            self.assertFalse(_install_uvloop_if_available())

    def test_non_windows_installs_uvloop_policy_when_importable(self) -> None:
        import types

        fake_uvloop = types.ModuleType("uvloop")

        class _FakePolicy:
            pass

        fake_uvloop.EventLoopPolicy = _FakePolicy  # type: ignore[attr-defined]

        with mock.patch("simplicio_mapper.mapper.async_pipeline.sys.platform", "linux"), \
                mock.patch.dict(sys.modules, {"uvloop": fake_uvloop}), \
                mock.patch("simplicio_mapper.mapper.async_pipeline.asyncio.set_event_loop_policy") as mocked_set:
            self.assertTrue(_install_uvloop_if_available())
            mocked_set.assert_called_once()
            (policy_instance,), _kwargs = mocked_set.call_args
            self.assertIsInstance(policy_instance, _FakePolicy)

    def test_build_artifacts_never_calls_uvloop_installer_on_windows(self) -> None:
        # Extra safety net for the "no behavior change on Windows" AC --
        # exercised directly on this machine (Windows CI/dev box) rather
        # than only via the mocked platform above.
        if sys.platform != "win32":
            self.skipTest("Windows-specific assertion")
        self.assertFalse(_install_uvloop_if_available())


if __name__ == "__main__":
    unittest.main()
