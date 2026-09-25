"""Tests for the default-async sync/async pipeline dispatch in
``simplicio_mapper.mapper.emit.build_artifacts``.  Normal ``auto`` runs use
the bounded async pipeline regardless of repository size; synchronous
execution remains an explicit diagnostic/rollback path.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import emit as emit_module  # noqa: E402
from simplicio_mapper.mapper.emit import (  # noqa: E402
    _async_pipeline_min_files,
    _build_artifacts_sync,
    _fast_file_count,
    build_artifacts,
)
from simplicio_mapper.mapper.parse import SKIP_DIRS  # noqa: E402


def _write(base: Path, rel: str, content: str = "") -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _make_tree(root: Path, count: int) -> None:
    for i in range(count):
        _write(root, f"src/mod_{i:04d}.py", f"def f_{i}():\n    return {i}\n")


class ThresholdEnvTest(unittest.TestCase):
    """Unit coverage for the threshold-selection logic in isolation."""

    def test_default_matches_measured_value(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
            self.assertEqual(_async_pipeline_min_files(), 600)

    def test_env_override_controls_the_threshold(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "42"}):
            self.assertEqual(_async_pipeline_min_files(), 42)

    def test_non_positive_or_garbage_override_falls_back_to_default(self) -> None:
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "0"}):
            self.assertEqual(_async_pipeline_min_files(), 600)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "-5"}):
            self.assertEqual(_async_pipeline_min_files(), 600)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "not-a-number"}):
            self.assertEqual(_async_pipeline_min_files(), 600)


class FastFileCountTest(unittest.TestCase):
    """Unit + integration coverage for the cheap file-count probe."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_counts_only_text_extensions(self) -> None:
        _make_tree(self.dir, 5)
        _write(self.dir, "assets/logo.png", "binary-ish-not-really")
        _write(self.dir, "assets/data.bin", "binary-ish-not-really")
        self.assertEqual(_fast_file_count(str(self.dir), cap=1000), 5)

    def test_honors_skip_dirs_like_the_real_walk(self) -> None:
        _make_tree(self.dir, 3)
        skip_dir = next(iter(SKIP_DIRS))
        _write(self.dir, f"{skip_dir}/generated.py", "x = 1\n")
        self.assertEqual(_fast_file_count(str(self.dir), cap=1000), 3)

    def test_honors_worktree_exclusion(self) -> None:
        _make_tree(self.dir, 2)
        _write(self.dir, ".claude/worktrees/agent-x/src/extra.py", "x = 1\n")
        _write(self.dir, ".claude/settings.json", "{}")
        # Legitimate root-level .claude config counts; the nested worktree
        # checkout must not (issue #234's exclusion, reused here).
        self.assertEqual(_fast_file_count(str(self.dir), cap=1000), 3)

    def test_early_exit_stops_at_cap_before_walking_the_whole_tree(self) -> None:
        _make_tree(self.dir, 50)
        # A cap below the real file count must return exactly the cap,
        # proving the probe stopped early rather than counting everything
        # then truncating the result.
        self.assertEqual(_fast_file_count(str(self.dir), cap=10), 10)

    def test_never_reads_file_contents(self) -> None:
        _make_tree(self.dir, 5)
        with mock.patch("builtins.open", side_effect=AssertionError("probe must not open files")):
            _fast_file_count(str(self.dir), cap=1000)


class DispatchRoutingTest(unittest.TestCase):
    """Confirms build_artifacts() uses conservative sync without evidence.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_routes_to_sync_below_threshold_without_calibration(self) -> None:
        _make_tree(self.dir, 3)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "5"}), \
                mock.patch.object(emit_module, "_build_artifacts_sync", wraps=_build_artifacts_sync) as spy_sync, \
                mock.patch("simplicio_mapper.mapper.async_pipeline.build_artifacts_async") as spy_async:
            build_artifacts(str(self.dir))
        spy_sync.assert_called_once()
        spy_async.assert_not_called()

    def test_routes_to_sync_at_or_above_threshold_without_calibration(self) -> None:
        _make_tree(self.dir, 6)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "5"}), \
                mock.patch.object(emit_module, "_build_artifacts_sync") as spy_sync:
            build_artifacts(str(self.dir))
        spy_sync.assert_called_once()

    def test_boundary_threshold_minus_one_goes_sync(self) -> None:
        _make_tree(self.dir, 4)  # threshold(5) - 1 files
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "5"}), \
                mock.patch.object(emit_module, "_build_artifacts_sync", wraps=_build_artifacts_sync) as spy_sync:
            build_artifacts(str(self.dir))
        spy_sync.assert_called_once()

    def test_boundary_exactly_at_threshold_goes_sync(self) -> None:
        _make_tree(self.dir, 5)  # exactly threshold
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "5"}), \
                mock.patch.object(emit_module, "_build_artifacts_sync") as spy_sync:
            build_artifacts(str(self.dir))
        spy_sync.assert_called_once()


class ByteIdenticalAcrossDispatchTest(unittest.TestCase):
    """Regression gate: whichever path the dispatcher picks, the resulting
    JSON-shaped artifacts must be identical (modulo generated_at
    timestamps) -- extends the existing sync-vs-async OutputEquivalenceTest
    (tests/python/test_async_pipeline.py) to the dispatcher itself, at
    exactly threshold-1, threshold, and threshold+1 files.
    """

    def _tree(self, count: int) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _make_tree(root, count)
        return root

    @staticmethod
    def _normalize(artifacts: dict) -> dict:
        out = {}
        for key in ("project_map", "precedent_index", "architecture_inventory", "symbol_index", "call_graph"):
            section = dict(artifacts[key])
            section.pop("generated_at", None)
            out[key] = section
        return out

    def _assert_dispatch_matches_forced_paths(self, count: int, threshold: int) -> None:
        root = self._tree(count)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": str(threshold)}):
            dispatched = build_artifacts(str(root), output_dir=".simplicio-dispatch")
        sync_direct = _build_artifacts_sync(str(root), output_dir=".simplicio-sync-direct")
        from simplicio_mapper.mapper.async_pipeline import build_artifacts_async
        async_direct = asyncio.run(
            build_artifacts_async(str(root), output_dir=".simplicio-async-direct")
        )
        self.assertEqual(self._normalize(dispatched), self._normalize(sync_direct))
        self.assertEqual(self._normalize(dispatched), self._normalize(async_direct))

    def test_threshold_minus_one_files(self) -> None:
        self._assert_dispatch_matches_forced_paths(count=4, threshold=5)

    def test_exactly_threshold_files(self) -> None:
        self._assert_dispatch_matches_forced_paths(count=5, threshold=5)

    def test_threshold_plus_one_files(self) -> None:
        self._assert_dispatch_matches_forced_paths(count=6, threshold=5)


class CalibrationOverrideTest(unittest.TestCase):
    """Integration coverage for issue #279 Phase-0: a cached
    ``pipeline-calibration.json`` overrides the hardcoded default, an env
    var override still wins over it, and its total absence leaves today's
    behavior (the hardcoded 600 default) completely unchanged.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_no_calibration_file_keeps_hardcoded_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
            self.assertEqual(_async_pipeline_min_files(str(self.dir)), 600)

    def test_valid_calibration_file_overrides_hardcoded_default(self) -> None:
        from simplicio_mapper.mapper.pipeline_calibration import write_calibration

        payload = {
            "schema": "simplicio.pipeline-calibration/v1",
            "recommended_threshold": 42,
        }
        write_calibration(str(self.dir), payload)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
            self.assertEqual(_async_pipeline_min_files(str(self.dir)), 42)

    def test_env_override_still_wins_over_calibration_file(self) -> None:
        from simplicio_mapper.mapper.pipeline_calibration import write_calibration

        payload = {
            "schema": "simplicio.pipeline-calibration/v1",
            "recommended_threshold": 42,
        }
        write_calibration(str(self.dir), payload)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "99"}):
            self.assertEqual(_async_pipeline_min_files(str(self.dir)), 99)

    def test_build_artifacts_does_not_promote_threshold_only_calibration(self) -> None:
        from simplicio_mapper.mapper.pipeline_calibration import write_calibration

        _make_tree(self.dir, 6)
        payload = {
            "schema": "simplicio.pipeline-calibration/v1",
            "recommended_threshold": 5,
        }
        write_calibration(str(self.dir), payload)
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(emit_module, "_build_artifacts_sync") as spy_sync:
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
            build_artifacts(str(self.dir))
        # A threshold-only legacy file is not p95 evidence and cannot promote async.
        spy_sync.assert_called_once()


if __name__ == "__main__":
    unittest.main()
