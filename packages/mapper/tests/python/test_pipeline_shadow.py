"""Tests for `simplicio_mapper.mapper.pipeline_shadow` (issue #279 plan
step 15: shadow rollout comparing the sync/async pipeline profiles without
ever auto-promoting the candidate, ADR-011).

Covers: diff-path helper edge cases, volatile-key stripping,
`determine_configured_profile` matching `emit.py`'s real dispatch decision,
a real (small, fast) `run_shadow_comparison()` invocation exercising the
actual sync-vs-async comparison end to end (unit + integration), and the
atomic-write contract of `write_shadow_report` (mirroring
`pipeline_calibration.py::write_calibration`'s own test shape).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import emit as emit_module  # noqa: E402
from simplicio_mapper.mapper.pipeline_shadow import (  # noqa: E402
    SHADOW_REPORT_FILENAME,
    SHADOW_SCHEMA,
    _diff_paths,
    _strip_volatile,
    determine_configured_profile,
    run_shadow_comparison,
    write_shadow_report,
)


def _materialize_tiny_tree(root: Path, count: int) -> None:
    for i in range(count):
        (root / f"mod_{i}.py").write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")


class StripVolatileTest(unittest.TestCase):
    def test_drops_generated_at_at_every_depth(self) -> None:
        value = {
            "generated_at": "2026-01-01T00:00:00Z",
            "nested": {"generated_at": "later", "keep": 1},
            "items": [{"generated_at": "x", "keep": 2}],
        }
        stripped = _strip_volatile(value)
        self.assertNotIn("generated_at", stripped)
        self.assertNotIn("generated_at", stripped["nested"])
        self.assertEqual(stripped["nested"]["keep"], 1)
        self.assertNotIn("generated_at", stripped["items"][0])
        self.assertEqual(stripped["items"][0]["keep"], 2)

    def test_passes_through_scalars_unchanged(self) -> None:
        self.assertEqual(_strip_volatile(5), 5)
        self.assertEqual(_strip_volatile("x"), "x")
        self.assertIsNone(_strip_volatile(None))


class DiffPathsTest(unittest.TestCase):
    def test_identical_values_have_no_diffs(self) -> None:
        a = {"x": [1, 2, {"y": "z"}]}
        b = {"x": [1, 2, {"y": "z"}]}
        self.assertEqual(_diff_paths(a, b), [])

    def test_reports_scalar_mismatch_path(self) -> None:
        diffs = _diff_paths({"a": 1}, {"a": 2})
        self.assertEqual(diffs, ["$.a"])

    def test_reports_key_present_only_on_one_side(self) -> None:
        diffs = _diff_paths({"a": 1}, {"a": 1, "b": 2})
        self.assertIn("$.b (present on only one side)", diffs)

    def test_reports_list_length_mismatch_without_recursing(self) -> None:
        diffs = _diff_paths({"a": [1, 2]}, {"a": [1, 2, 3]})
        self.assertEqual(diffs, ["$.a (length 2 != 3)"])

    def test_respects_limit(self) -> None:
        a = {str(i): i for i in range(50)}
        b = {str(i): i + 1 for i in range(50)}
        diffs = _diff_paths(a, b, limit=5)
        self.assertEqual(len(diffs), 5)


class DetermineConfiguredProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_matches_emit_dispatch_at_small_size(self) -> None:
        _materialize_tiny_tree(self.root, 3)
        # Issue #279 Phase-0 (execution_planner.plan_execution) made `auto`
        # promote to async only from a compatible, p95-calibrated profile
        # set; with none configured here, both this helper and the real
        # `build_artifacts()` dispatch it mirrors conservatively fall back
        # to sync, regardless of the (here irrelevant, since uncalibrated)
        # file-count threshold.
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES": "600"}):
            self.assertEqual(determine_configured_profile(str(self.root)), "sync")

    def test_explicit_sync_matches_emit_dispatch(self) -> None:
        _materialize_tiny_tree(self.root, 3)
        with mock.patch.dict(os.environ, {"SIMPLICIO_MAPPER_EXECUTION_PROFILE": "sync"}):
            self.assertEqual(determine_configured_profile(str(self.root)), "sync")


class RunShadowComparisonTest(unittest.TestCase):
    """Exercises the real comparison path end to end with a tiny tree so the
    unit-test suite stays fast -- this is the shadow-rollout mode itself
    acting as its own system-level test.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _materialize_tiny_tree(self.root, 4)

    def test_payload_is_well_formed_and_never_promotes(self) -> None:
        payload = run_shadow_comparison(str(self.root))
        self.assertEqual(payload["schema"], SHADOW_SCHEMA)
        self.assertIn(payload["configured_profile"], ("sync", "async"))
        self.assertIn(payload["candidate_profile"], ("sync", "async"))
        self.assertNotEqual(payload["configured_profile"], payload["candidate_profile"])
        self.assertIn("configured_wall_s", payload)
        self.assertIn("candidate_wall_s", payload)
        self.assertIn(payload["faster_profile"], (payload["configured_profile"], payload["candidate_profile"]))
        # Load-bearing acceptance criterion: never auto-promotes.
        self.assertFalse(payload["promoted"])
        self.assertEqual(payload["returned_profile"], payload["configured_profile"])

    def test_sync_and_async_outputs_are_equivalent_on_the_same_tiny_tree(self) -> None:
        # Same source tree, only dispatch differs -- content must match
        # (ADR-009's own byte-identical-output requirement), so a real
        # shadow run over a real (if tiny) tree should report equivalence.
        payload = run_shadow_comparison(str(self.root))
        self.assertTrue(payload["equivalent_output"], msg=payload["diffs"])
        self.assertEqual(payload["diffs"], {})

    def test_configured_run_does_not_write_into_a_throwaway_shadow_dir(self) -> None:
        # The candidate profile's isolated temp output dir must never leak
        # into the real `<root>/.simplicio` tree.
        before = set(os.listdir(self.root)) if self.root.exists() else set()
        run_shadow_comparison(str(self.root))
        after_dirs = {p for p in os.listdir(self.root) if os.path.isdir(self.root / p)}
        self.assertEqual(after_dirs - before, {".simplicio"})

    def test_candidate_forcing_env_var_is_restored(self) -> None:
        os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
        run_shadow_comparison(str(self.root))
        self.assertNotIn("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", os.environ)

    def test_restores_a_pre_existing_env_var_override(self) -> None:
        os.environ["SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES"] = "42"
        try:
            run_shadow_comparison(str(self.root))
            self.assertEqual(os.environ["SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES"], "42")
        finally:
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)

    def test_configured_profile_is_never_run_twice_via_build_artifacts_sync_spy(self) -> None:
        # Regression guard: whichever profile is "configured", the shadow
        # comparison must invoke each of sync/async exactly once (one real
        # + one forced-candidate run), not repeatedly.
        with mock.patch.object(
            emit_module, "_build_artifacts_sync", wraps=emit_module._build_artifacts_sync
        ) as spy_sync:
            run_shadow_comparison(str(self.root))
            # Tiny tree -> configured profile is sync (default threshold
            # 600 not overridden here) and candidate is forced async, so
            # `_build_artifacts_sync` is called exactly once (for the real
            # configured run); the candidate run is forced through the
            # async path.
            self.assertEqual(spy_sync.call_count, 1)


class RunShadowComparisonMismatchTest(unittest.TestCase):
    """Forces a real (synthetic) mismatch between the configured and
    candidate profile's output by stubbing `emit.build_artifacts`, so the
    non-equivalent branch (`diffs` populated, `equivalent_output` False) is
    exercised deterministically rather than relying on the sync/async
    pipelines happening to diverge on some future input.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _materialize_tiny_tree(self.root, 3)

    def test_reports_diffs_when_profiles_disagree(self) -> None:
        calls = {"n": 0}

        def fake_build_artifacts(cwd, meta=None, incremental=False, output_dir=".simplicio"):
            calls["n"] += 1
            # First call is the real, configured-profile run; second call
            # is the forced candidate run into an isolated temp dir.
            value = "configured" if calls["n"] == 1 else "candidate"
            return {"project_map": {"generated_at": "irrelevant", "product": {"name": value}}}

        with mock.patch.object(emit_module, "build_artifacts", side_effect=fake_build_artifacts):
            payload = run_shadow_comparison(str(self.root))

        self.assertFalse(payload["equivalent_output"])
        self.assertIn("project_map", payload["diffs"])
        self.assertIn("$project_map.product.name", payload["diffs"]["project_map"])


class WriteShadowReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_writes_valid_json_atomically_no_stray_tmp_file(self) -> None:
        path = write_shadow_report(
            str(self.dir), {"schema": SHADOW_SCHEMA, "equivalent_output": True}
        )
        self.assertTrue(path.replace("\\", "/").endswith(".simplicio/" + SHADOW_REPORT_FILENAME))
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertTrue(payload["equivalent_output"])
        leftovers = [p for p in os.listdir(os.path.dirname(path)) if ".tmp-" in p]
        self.assertEqual(leftovers, [])

    def test_creates_output_dir_if_missing(self) -> None:
        target_out = self.dir / "nested" / "out"
        path = write_shadow_report(
            str(self.dir),
            {"schema": SHADOW_SCHEMA},
            output_dir=str(Path("nested") / "out"),
        )
        self.assertTrue(os.path.isdir(target_out))
        self.assertTrue(os.path.exists(path))

    def test_does_not_mutate_caller_payload(self) -> None:
        payload = {"schema": SHADOW_SCHEMA, "diffs": {"a": ["x"]}}
        write_shadow_report(str(self.dir), payload)
        self.assertEqual(payload, {"schema": SHADOW_SCHEMA, "diffs": {"a": ["x"]}})


if __name__ == "__main__":
    unittest.main()
