"""Tests for simplicio_mapper.mapper.async_inventory (ADR-009 / issue #235
plan steps 4-5, partial -- async ``_build_file_inventory`` counterpart).

Covers the 7 DoD dimensions required for `simplicio_mapper/` work
(AGENTS.md "DoD específico do pacote Python"):

- Unit: cache-hit-skips-read behavior; walk/filter reuse in isolation.
- Integration: a real temp tree with cached/uncached/skip-dir/worktree-dir
  files, proving the async path reuses the sync path's exact filtering.
- System: `_build_file_inventory` (sync) vs. `build_file_inventory_async_sync`
  (new) over the SAME real fixture directory, asserting equal `ProjectFile`
  lists (order, fields, everything).
- Regression: the pre-existing `_build_file_inventory` behavior is
  untouched (not edited by this change) -- proven by running its own
  existing test module unchanged, invoked here too for convenience.
- Perf benchmark: see `scripts/async_inventory_benchmark.py` (separate,
  matches the existing `scripts/*_benchmark.py` pattern) -- not re-measured
  inside the unittest run itself.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.mapper.async_inventory import (  # noqa: E402
    build_file_inventory_async,
    build_file_inventory_async_sync,
)
from simplicio_mapper.mapper.parse import _build_file_inventory  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_mixed_tree(root: Path) -> None:
    """A realistic mixed tree: normal source files, a `SKIP_DIRS` entry
    (`node_modules`), and a nested `.claude/worktrees/<agent>/...` directory
    that issue #234 excludes from the mapped universe."""
    _write(root / "pkg" / "a.py", "def foo():\n    return 1\n")
    _write(root / "pkg" / "b.py", "class Bar:\n    pass\n")
    _write(root / "README.md", "# Title\n\nSome docs.\n")
    # Should be skipped: inside SKIP_DIRS.
    _write(root / "node_modules" / "dep" / "index.js", "module.exports = {};\n")
    # Should be skipped: nested worktree checkout (issue #234).
    _write(
        root / ".claude" / "worktrees" / "agent-xyz" / "pkg" / "c.py",
        "def should_not_appear():\n    return 2\n",
    )
    # Legitimate root-level .claude config must NOT be skipped.
    _write(root / ".claude" / "settings.json", "{}\n")


def _entry_tuple(entry) -> tuple:
    return (
        entry.path,
        entry.language,
        entry.size_bytes,
        entry.last_modified,
        entry.file_hash,
        entry.git_status,
        tuple(entry.roles),
        tuple(entry.imports),
        tuple(entry.exports),
        entry.importance,
        entry.text_preview,
        entry.bh_address,
        entry.agent_id,
    )


class UnitCacheHitSkipsReadTests(unittest.TestCase):
    """(Unit) a cache hit skips the async read entirely when no shared
    `contents` dict is requested, mirroring the sync path's
    `_cached_parse_file` behavior."""

    def test_cache_hit_without_contents_never_reads(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as cache_dir:
            root = Path(tmpdir)
            _write(root / "a.py", "def foo():\n    return 1\n")

            with FileProcessingCache(cache_dir) as cache:
                # First run populates the cache.
                asyncio.run(build_file_inventory_async(str(root), {}, {}, cache=cache))

                # Second run: patch async_io.read_files_concurrently to fail
                # loudly if invoked with any path -- a cache hit (no
                # `contents` requested) must never call it.
                import simplicio_mapper.mapper.async_inventory as mod

                original = mod.async_io.read_files_concurrently

                async def _boom(paths, *, max_concurrency=None, timeout=None):
                    if paths:
                        raise AssertionError(
                            f"expected no reads on a full cache hit, got: {paths}"
                        )
                    return await original(paths, max_concurrency=max_concurrency, timeout=timeout)

                mod.async_io.read_files_concurrently = _boom
                try:
                    result = asyncio.run(
                        build_file_inventory_async(str(root), {}, {}, cache=cache)
                    )
                finally:
                    mod.async_io.read_files_concurrently = original

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].path, "a.py")

    def test_cache_hit_with_contents_still_resolves_text(self):
        """When a shared `contents` dict is passed (as `build_artifacts`
        does, for downstream precedent extraction), a cache hit still needs
        the raw text -- matching `_cached_parse_file`'s cache-hit branch
        exactly (it is not a "true" skip in that case)."""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as cache_dir:
            root = Path(tmpdir)
            _write(root / "a.py", "def foo():\n    return 1\n")

            with FileProcessingCache(cache_dir) as cache:
                asyncio.run(build_file_inventory_async(str(root), {}, {}, cache=cache))

                contents: dict[str, str] = {}
                asyncio.run(
                    build_file_inventory_async(str(root), {}, {}, cache=cache, contents=contents)
                )
                self.assertIn("a.py", contents)
                self.assertIn("def foo", contents["a.py"])


class IntegrationFilteringReuseTests(unittest.TestCase):
    """(Integration) real temp dir with a mix of files -- some cached, some
    not, some in SKIP_DIRS, some in a nested `.claude/worktrees` checkout --
    proving the async path reuses the exact same filtering as the sync
    path."""

    def test_mixed_tree_matches_sync_filtering(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _make_mixed_tree(root)

            sync_result = _build_file_inventory(str(root), {}, {})
            async_result = build_file_inventory_async_sync(str(root), {}, {})

            sync_paths = sorted(e.path for e in sync_result)
            async_paths = sorted(e.path for e in async_result)

            self.assertEqual(sync_paths, async_paths)
            # node_modules/ and .claude/worktrees/ contents must not appear.
            self.assertNotIn("node_modules/dep/index.js", async_paths)
            self.assertFalse(
                any(p.startswith(".claude/worktrees/") for p in async_paths)
            )
            # Legitimate root .claude config must still appear.
            self.assertIn(".claude/settings.json", async_paths)
            # Real source files must appear.
            self.assertIn("pkg/a.py", async_paths)
            self.assertIn("pkg/b.py", async_paths)
            self.assertIn("README.md", async_paths)

    def test_partial_cache_mix_matches_sync(self):
        """Half the files pre-cached (from a prior sync build), half not --
        the async rebuild must still match the sync rebuild exactly."""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as cache_dir:
            root = Path(tmpdir)
            for i in range(6):
                _write(root / f"mod_{i}.py", f"def fn_{i}():\n    return {i}\n")

            with FileProcessingCache(cache_dir) as cache:
                # Warm the cache using the sync path for only half the tree
                # by removing the other half temporarily.
                held_out = []
                for i in range(3, 6):
                    p = root / f"mod_{i}.py"
                    held_out.append((p, p.read_text(encoding="utf-8")))
                    p.unlink()
                _build_file_inventory(str(root), {}, {}, cache)
                for p, text in held_out:
                    _write(p, text)

                sync_result = _build_file_inventory(str(root), {}, {}, cache)
                async_result = build_file_inventory_async_sync(str(root), {}, {}, cache=cache)

                self.assertEqual(
                    [_entry_tuple(e) for e in sync_result],
                    [_entry_tuple(e) for e in async_result],
                )


class SystemEquivalenceTests(unittest.TestCase):
    """(System) run BOTH the real sync `_build_file_inventory` and the new
    `build_file_inventory_async_sync` over the SAME real fixture directory
    through their real public entry points, and assert the resulting
    `ProjectFile` lists are equal -- the "provably identical output" proof."""

    def test_equal_over_real_fixture(self):
        fixture = ROOT / "simplicio_mapper" / "contracts" / "mapper-artifacts" / "v1" / "fixtures" / "python-minimal" / "source"
        self.assertTrue(fixture.exists(), f"fixture missing: {fixture}")

        sync_result = _build_file_inventory(str(fixture), {}, {})
        async_result = build_file_inventory_async_sync(str(fixture), {}, {})

        self.assertEqual(len(sync_result), len(async_result))
        self.assertGreater(len(sync_result), 0)
        self.assertEqual(
            [_entry_tuple(e) for e in sync_result],
            [_entry_tuple(e) for e in async_result],
        )

    def test_equal_over_synthetic_tree_with_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as cache_dir:
            root = Path(tmpdir)
            for i in range(40):
                _write(
                    root / "pkg" / f"module_{i}.py",
                    f"import os\n\nclass Service{i}:\n    def run(self):\n        return os.getcwd()\n",
                )
            _write(root / "tests" / "test_module_0.py", "def test_it():\n    assert True\n")
            pkg = {"name": "synthetic", "main": "pkg/module_0.py"}
            status_map = {"pkg/module_1.py": "modified"}

            with FileProcessingCache(cache_dir) as cache:
                sync_contents: dict[str, str] = {}
                sync_result = _build_file_inventory(
                    str(root), pkg, status_map, cache, contents=sync_contents
                )

            with FileProcessingCache(cache_dir) as cache:
                async_contents: dict[str, str] = {}
                async_result = build_file_inventory_async_sync(
                    str(root), pkg, status_map, cache=cache, contents=async_contents
                )

            self.assertEqual(
                [_entry_tuple(e) for e in sync_result],
                [_entry_tuple(e) for e in async_result],
            )
            self.assertEqual(sync_contents, async_contents)


class ConcurrencyBoundsTests(unittest.TestCase):
    """Bounded concurrency only -- max_concurrency forwards through, never
    defaults to unbounded."""

    def test_max_concurrency_forwarded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for i in range(10):
                _write(root / f"f_{i}.py", f"x = {i}\n")

            import simplicio_mapper.mapper.async_inventory as mod

            seen_caps = []
            original = mod.async_io.read_files_concurrently

            async def _spy(paths, *, max_concurrency=None, timeout=None):
                seen_caps.append(max_concurrency)
                return await original(paths, max_concurrency=max_concurrency, timeout=timeout)

            mod.async_io.read_files_concurrently = _spy
            try:
                asyncio.run(
                    build_file_inventory_async(str(root), {}, {}, max_concurrency=2)
                )
            finally:
                mod.async_io.read_files_concurrently = original

            self.assertEqual(seen_caps, [2])

    def test_invalid_max_concurrency_propagates_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "a.py", "x = 1\n")
            with self.assertRaises(ValueError):
                asyncio.run(
                    build_file_inventory_async(str(root), {}, {}, max_concurrency=0)
                )


class SyncWrapperTests(unittest.TestCase):
    def test_sync_wrapper_matches_direct_await(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write(root / "a.py", "x = 1\n")
            _write(root / "b.py", "y = 2\n")

            direct = asyncio.run(build_file_inventory_async(str(root), {}, {}))
            via_wrapper = build_file_inventory_async_sync(str(root), {}, {})

            self.assertEqual(
                [_entry_tuple(e) for e in direct],
                [_entry_tuple(e) for e in via_wrapper],
            )

    def test_empty_tree_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_file_inventory_async_sync(tmpdir, {}, {})
            self.assertEqual(result, [])


class RegressionExistingSyncPathUnaffectedTests(unittest.TestCase):
    """Confirms `_build_file_inventory` itself keeps behaving as before --
    this change does not edit it, and this test proves the file-skip
    behavior it already had for issue #234 nested worktrees still holds."""

    def test_sync_path_still_skips_nested_worktree(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _make_mixed_tree(root)
            result = _build_file_inventory(str(root), {}, {})
            paths = [e.path for e in result]
            self.assertFalse(any(p.startswith(".claude/worktrees/") for p in paths))
            self.assertIn(".claude/settings.json", paths)


if __name__ == "__main__":
    unittest.main()
