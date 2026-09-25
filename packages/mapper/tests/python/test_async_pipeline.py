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
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import orjson  # noqa: E402

from simplicio_mapper.cli import main as cli_main  # noqa: E402
from simplicio_mapper.contract import validate_instance  # noqa: E402
from simplicio_mapper.mapper.async_pipeline import (  # noqa: E402
    _install_uvloop_if_available,
    _max_concurrent_files,
    _per_file_timeout_s,
    build_artifacts_async,
    build_file_inventory_async,
)
from simplicio_mapper.mapper.emit import build_artifacts  # noqa: E402
from simplicio_mapper.mapper.parse import _build_file_inventory  # noqa: E402

SCHEMA_ROOT = ROOT / "contracts" / "mapper-artifacts" / "v1" / "schemas"


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
        expected = min(64, (os.cpu_count() or 4) * 4)
        self.assertEqual(cap, expected)

    async def test_env_override_controls_the_cap(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "7"}):
            self.assertEqual(_max_concurrent_files(), 7)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "not-a-number"}):
            self.assertEqual(_max_concurrent_files(), min(64, (os.cpu_count() or 4) * 4))
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "0"}):
            self.assertEqual(_max_concurrent_files(), min(64, (os.cpu_count() or 4) * 4))


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


class QuarantineTest(unittest.IsolatedAsyncioTestCase):
    """Task quarantine (issue #279 step 13): a genuine parse/read failure
    that is not a timeout must not crash the entire in-flight pipeline for
    one bad file -- it is recorded (path + error) and skipped, and every
    other file's result is preserved, exactly like the existing
    ``timed_out_files``/``skipped_large_files`` fail-soft diagnostics.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for i in range(6):
            _write(self.dir, f"src/ok_{i}.py", f"def f_{i}():\n    return {i}\n")
        _write(self.dir, "src/corrupt.py", "def broken():\n    pass\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_one_file_repeatedly_failing_to_parse_is_quarantined_not_fatal(self) -> None:
        def flaky_parse(cwd, abs_path, rel, stat, cache, contents=None):
            if rel == "src/corrupt.py":
                raise ValueError("simulated corrupt/undecodable file")
            return {
                "language": "python",
                "file_hash": f"hash:{rel}",
                "imports": [],
                "exports": [],
                "text_preview": "",
            }

        degraded: dict = {}
        with mock.patch(
            "simplicio_mapper.mapper.async_pipeline._cached_parse_file",
            side_effect=flaky_parse,
        ):
            files = await build_file_inventory_async(
                str(self.dir),
                {"name": "fixture"},
                {},
                None,
                max_concurrent=8,
                degraded=degraded,
            )

        paths = {f.path for f in files}
        # The whole run completed -- it was not aborted by the one bad file.
        self.assertNotIn("src/corrupt.py", paths)
        for i in range(6):
            self.assertIn(f"src/ok_{i}.py", paths)

        # Surfaced as a diagnostic, matching the timed_out_files shape.
        self.assertIn("quarantined_files", degraded)
        entries = degraded["quarantined_files"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["path"], "src/corrupt.py")
        self.assertIn("ValueError", entries[0]["error"])
        self.assertIn("simulated corrupt/undecodable file", entries[0]["error"])


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


def _materialize_large_tree(root: Path, file_count: int) -> int:
    """Deterministic synthetic Python tree, same shape as the generator in
    ``scripts/async_pipeline_baseline_benchmark.py`` (not imported directly
    since ``scripts/`` is not an installed package), for a "large repository"
    system test that must go through the real, wired-in async pipeline.
    """
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
            f'"""Helper {i}."""\n\n\ndef helper_{i}(payload):\n    return {{"echo": payload}}\n\n\n'
            for i in indices_by_group[group]
        )
        (pkg_dir / f"helpers_{group}.py").write_text(helpers_source, encoding="utf-8")
        written += 1

    for index in range(file_count):
        group = index % groups
        pkg_dir = root / f"pkg_{group}"
        module_path = pkg_dir / f"module_{index}.py"
        module_path.write_text(
            f'"""Synthetic module {index}."""\n\n'
            f"from __future__ import annotations\n\n"
            f"from .helpers_{group} import helper_{index}\n\n\n"
            f"class Service{index}:\n"
            f"    def __init__(self, config):\n"
            f"        self.config = config\n\n"
            f"    def process(self, payload):\n"
            f"        return helper_{index}(payload)\n",
            encoding="utf-8",
        )
        written += 1
    return written


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
    )


class LargeRepositorySystemTest(unittest.TestCase):
    """System-level coverage for issue #235's "sistema em repositório
    grande" required test: exercises the REAL, wired-in ``build_artifacts``
    entry point (now a thin ``asyncio.run(build_artifacts_async(...))``
    adapter, ADR-009 plan step 8) through the actual CLI (``simplicio-mapper
    index``), not just the isolated ``async_pipeline`` module, against a
    synthetic tree an order of magnitude larger than every other test in
    this file (~320 files vs. the 4-24 file trees used above), git-backed
    like a real project.

    File count is chosen to stay well under a minute on a slow/shared CI
    runner (the committed baseline shows ~1s cold for a 220-file tree) while
    still being unambiguously "large" relative to this test file's other
    fixtures -- the 1650-file tree used for the baseline/after benchmark
    docs is deliberately not duplicated here to keep the unit-test suite
    fast; that scale is covered by the benchmark scripts instead (see
    ``scripts/async_pipeline_after_benchmark.py``).

    The threshold remains forced down to 1 so the fixture continues to
    exercise the calibrated-receipt path as well as the real, wired-in async
    pipeline through the CLI.  Normal ``auto`` execution is async for this
    tree even without the override; dedicated dispatch coverage lives in
    ``tests/python/test_pipeline_dispatch.py``.
    """

    def setUp(self) -> None:
        self._env_patch = mock.patch.dict(
            os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "1"}
        )
        self._env_patch.start()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "large-repo"
        self.root.mkdir()
        self.file_count = _materialize_large_tree(self.root, 320)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
        _git(self.root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "seed")
        self.project_map_schema = json.loads(
            (SCHEMA_ROOT / "project-map.schema.json").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()
        self._env_patch.stop()

    def test_real_cli_index_end_to_end_over_a_large_tree(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = cli_main(["index", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.mapper-index/v1")
        self.assertEqual(payload["status"], "updated")
        self.assertGreaterEqual(payload["counts"]["files"], self.file_count - 5)

        project_map = json.loads(
            (self.root / ".simplicio" / "project-map.json").read_text(encoding="utf-8")
        )
        errors = validate_instance(project_map, self.project_map_schema, str(SCHEMA_ROOT))
        self.assertEqual(errors, [], errors)
        self.assertGreaterEqual(len(project_map["files"]), self.file_count - 5)

    def test_incremental_reindex_over_the_large_tree_is_fast_and_consistent(self) -> None:
        # First pass (cold cache), then touch one file and re-run through
        # the same real CLI entry point -- proves the async-wired path
        # composes correctly with the existing incremental/freshness logic
        # (`_freshness_signature`/index lock), not only a fresh cold run.
        self.assertEqual(cli_main(["index", str(self.root)]), 0)
        (self.root / "pkg_0" / "module_0.py").write_text(
            '"""Synthetic module 0, touched."""\n\n\ndef touched():\n    return 1\n',
            encoding="utf-8",
        )
        out = StringIO()
        with redirect_stdout(out):
            code = cli_main(["index", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "updated")


class LowResourceProxyTest(unittest.TestCase):
    """Issue #235's "sistema sob baixa memória" required test.

    Honest limitation, documented rather than faked: this sandbox is
    Windows, where neither ``resource.setrlimit(RLIMIT_AS, ...)`` (POSIX
    only) nor cgroup memory limits are available, so there is no way from
    inside a unittest run to genuinely cap the process's memory and observe
    real OOM-recovery behavior. A true low-memory system test needs
    dedicated infra (a Linux cgroup-limited container or CI job) that does
    not exist for this repo today -- adding one is out of scope for this
    change and is called out explicitly in the ADR and PR instead of being
    silently skipped or faked with a trivial assertion.

    What this test *does* cover, as the closest honest proxy achievable
    here: the pipeline's own memory-footprint control knob
    (``max_concurrent`` / ``SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES``) driven
    down to its minimum (serialize to one file in flight at a time, the
    lowest peak-memory configuration the pipeline exposes) over the same
    large tree, proving the pipeline still completes correctly -- not that
    it survives a real OS-level memory ceiling.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "low-resource-repo"
        self.root.mkdir()
        self.file_count = _materialize_large_tree(self.root, 120)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pipeline_completes_correctly_with_minimum_concurrency(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_MAX_CONCURRENT_FILES": "1"}):
            artifacts = asyncio.run(build_artifacts_async(str(self.root)))
        self.assertGreaterEqual(len(artifacts["project_map"]["files"]), self.file_count - 5)
        self.assertEqual(artifacts["project_map"]["degraded"]["skipped_large_files"], [])


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
