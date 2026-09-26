"""End-to-end CLI coverage for `simplicio-mapper benchmark pipeline-threshold`
and `simplicio-mapper benchmark shadow-rollout` (issue #279 Phase-0: local,
per-machine sync/async pipeline-dispatch calibration, ADR-011, plus the
shadow-rollout comparison mode from issue #279 plan step 15).

Drives the real `main()` entry point end to end -- argv dispatch
(`simplicio_mapper/cli/__init__.py` -> `_benchmark.py`), flag parsing, and
the integration with `pipeline_calibration.run_calibration`/
`write_calibration` and `pipeline_shadow.run_shadow_comparison`/
`write_shadow_report`, then confirms a subsequent `build_artifacts()` call
honors the freshly written calibration file (system-level: real CLI
invocation followed by a real dispatch decision).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.cli._benchmark import (  # noqa: E402
    _parse_benchmark_args,
    _parse_shadow_args,
)
from simplicio_mapper.mapper import emit as emit_module  # noqa: E402
from simplicio_mapper.mapper.pipeline_calibration import (  # noqa: E402
    CALIBRATION_FILENAME,
    load_calibrated_threshold,
)
from simplicio_mapper.mapper.pipeline_shadow import SHADOW_REPORT_FILENAME  # noqa: E402


class ParseBenchmarkArgsTest(unittest.TestCase):
    """Unit coverage for every argv error branch in `_parse_benchmark_args`
    (each calls `sys.exit(2)` after printing a usage-style error to
    stderr)."""

    def test_defaults_when_no_flags_given(self) -> None:
        opts = _parse_benchmark_args([])
        self.assertEqual(opts["root"], ".")
        self.assertEqual(opts["runs"], 1)
        self.assertFalse(opts["json"])

    def test_positional_sets_root(self) -> None:
        opts = _parse_benchmark_args(["/some/path"])
        self.assertEqual(opts["root"], "/some/path")

    def test_sizes_parses_and_dedupes(self) -> None:
        opts = _parse_benchmark_args(["--sizes", "600,200,200"])
        self.assertEqual(opts["sizes"], (200, 600))

    def test_sizes_missing_value_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--sizes"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--sizes requires a value", err.getvalue())

    def test_sizes_non_integer_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--sizes", "abc"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("comma-separated list of integers", err.getvalue())

    def test_runs_missing_value_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--runs"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--runs requires an integer value", err.getvalue())

    def test_runs_non_integer_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--runs", "abc"])
        self.assertEqual(ctx.exception.code, 2)

    def test_runs_clamped_to_minimum_one(self) -> None:
        opts = _parse_benchmark_args(["--runs", "0"])
        self.assertEqual(opts["runs"], 1)

    def test_out_missing_value_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--out"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--out requires a value", err.getvalue())

    def test_unknown_flag_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_benchmark_args(["--not-a-real-flag"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("unknown flag", err.getvalue())

    def test_json_flag_sets_json_true(self) -> None:
        opts = _parse_benchmark_args(["--json"])
        self.assertTrue(opts["json"])


class ParseShadowArgsTest(unittest.TestCase):
    def test_defaults_when_no_flags_given(self) -> None:
        opts = _parse_shadow_args([])
        self.assertEqual(opts["root"], ".")
        self.assertEqual(opts["out"], ".simplicio-loop")
        self.assertFalse(opts["json"])

    def test_positional_sets_root(self) -> None:
        opts = _parse_shadow_args(["/some/path"])
        self.assertEqual(opts["root"], "/some/path")

    def test_out_missing_value_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_shadow_args(["--out"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--out requires a value", err.getvalue())

    def test_unknown_flag_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            _parse_shadow_args(["--nope"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("unknown flag", err.getvalue())

    def test_json_flag_sets_json_true(self) -> None:
        opts = _parse_shadow_args(["--json"])
        self.assertTrue(opts["json"])


class BenchmarkCliUsageTest(unittest.TestCase):
    def test_unknown_verb_prints_usage_and_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["benchmark", "not-a-real-verb"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())

    def test_missing_verb_prints_usage_and_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err):
            code = main(["benchmark"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())


class BenchmarkPipelineThresholdCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_real_invocation_writes_calibration_file_json_mode(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(
                [
                    "benchmark",
                    "pipeline-threshold",
                    str(self.root),
                    "--sizes",
                    "3,6",
                    "--runs",
                    "1",
                    "--json",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.pipeline-calibration/v1")
        self.assertIn("recommended_threshold", payload)
        calibration_path = self.root / ".simplicio-loop" / CALIBRATION_FILENAME
        self.assertTrue(calibration_path.exists())
        with open(calibration_path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["recommended_threshold"], payload["recommended_threshold"])

    def test_real_invocation_human_readable_mode(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(
                ["benchmark", "pipeline-threshold", str(self.root), "--sizes", "3", "--runs", "1"]
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("recommended_threshold=", text)
        self.assertIn("calibration written to", text)

    def test_custom_out_dir_is_honored(self) -> None:
        code = main(
            [
                "benchmark",
                "pipeline-threshold",
                str(self.root),
                "--sizes",
                "3",
                "--runs",
                "1",
                "--out",
                ".custom-out",
            ]
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ".custom-out" / CALIBRATION_FILENAME).exists())
        self.assertFalse((self.root / ".simplicio-loop" / CALIBRATION_FILENAME).exists())

    def test_subsequent_build_artifacts_call_honors_the_written_calibration(self) -> None:
        # Materialize a tiny real tree, calibrate against it, force a known
        # recommended threshold into the file directly (bypassing the noisy
        # real timing so this assertion is deterministic), then confirm
        # build_artifacts()'s dispatch reads the calibrated threshold back
        # into its execution receipt.
        #
        # Issue #279 Phase-0 moved profile *selection* itself off this bare
        # ``recommended_threshold`` value: `auto` now only promotes to the
        # async pipeline from a compatible p95-calibrated profile set (see
        # ``execution_planner.plan_execution``/``_compatible_calibration_
        # profiles``); a threshold-only calibration file (no ``profiles``
        # key) is not "compatible calibration" and `auto` deliberately keeps
        # the conservative synchronous path -- missing evidence must not
        # promote a more complex executor. The threshold itself still flows
        # through to the receipt as calibration metadata.
        for i in range(6):
            target = self.root / f"mod_{i}.py"
            target.write_text(f"def f_{i}():\n    return {i}\n", encoding="utf-8")

        from simplicio_mapper.mapper.pipeline_calibration import write_calibration

        write_calibration(
            str(self.root),
            {"schema": "simplicio.pipeline-calibration/v1", "recommended_threshold": 5},
        )
        self.assertEqual(load_calibrated_threshold(str(self.root)), 5)

        from simplicio_mapper.mapper.emit import build_artifacts

        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(emit_module, "_build_artifacts_sync", wraps=emit_module._build_artifacts_sync) as spy_sync:
            os.environ.pop("SIMPLICIO_MAPPER_ASYNC_PIPELINE_MIN_FILES", None)
            # Same output_dir the calibration file was written under
            # (default ".simplicio-loop") -- the override is scoped per
            # output_dir, not global to the machine.
            artifacts = build_artifacts(str(self.root))
        # Threshold calibration is honored in the receipt...
        self.assertEqual(artifacts["execution_plan"]["threshold"], 5)
        # ...but a threshold-only calibration file is not a "compatible
        # calibration" for profile selection, so `auto` still takes the
        # conservative sync path (no p95-calibrated profiles available).
        spy_sync.assert_called_once()
        self.assertEqual(artifacts["execution_plan"]["selected_profile"], "sync")


class BenchmarkShadowRolloutCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for i in range(4):
            (self.root / f"mod_{i}.py").write_text(
                f"def f_{i}():\n    return {i}\n", encoding="utf-8"
            )

    def test_real_invocation_writes_shadow_report_json_mode(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["benchmark", "shadow-rollout", str(self.root), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.pipeline-shadow/v1")
        self.assertIn("configured_profile", payload)
        self.assertIn("candidate_profile", payload)
        self.assertFalse(payload["promoted"])
        report_path = self.root / ".simplicio-loop" / SHADOW_REPORT_FILENAME
        self.assertTrue(report_path.exists())
        with open(report_path, encoding="utf-8") as handle:
            on_disk = json.load(handle)
        self.assertEqual(on_disk["configured_profile"], payload["configured_profile"])

    def test_real_invocation_human_readable_mode(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["benchmark", "shadow-rollout", str(self.root)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("shadow-rollout report written to", text)
        self.assertIn("configured_profile=", text)
        self.assertIn("equivalent_output=", text)

    def test_custom_out_dir_is_honored(self) -> None:
        code = main(
            ["benchmark", "shadow-rollout", str(self.root), "--out", ".custom-out"]
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.root / ".custom-out" / SHADOW_REPORT_FILENAME).exists())
        self.assertFalse((self.root / ".simplicio-loop" / SHADOW_REPORT_FILENAME).exists())

    def test_missing_out_value_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            main(["benchmark", "shadow-rollout", str(self.root), "--out"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--out requires a value", err.getvalue())

    def test_unknown_flag_exits_2(self) -> None:
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            main(["benchmark", "shadow-rollout", str(self.root), "--not-real"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("unknown flag", err.getvalue())

    def test_human_readable_mode_prints_diffs_when_not_equivalent(self) -> None:
        from simplicio_mapper.cli import _benchmark as benchmark_module

        fake_payload = {
            "shadow_report_file": "unused",
            "schema": "simplicio.pipeline-shadow/v1",
            "configured_profile": "sync",
            "candidate_profile": "async",
            "configured_wall_s": 0.01,
            "candidate_wall_s": 0.02,
            "faster_profile": "sync",
            "equivalent_output": False,
            "diffs": {"project_map": ["$project_map.product.name"]},
            "returned_profile": "sync",
            "promoted": False,
        }
        out = StringIO()
        with mock.patch.object(
            benchmark_module, "run_shadow_comparison", return_value=fake_payload
        ), mock.patch.object(
            benchmark_module, "write_shadow_report", return_value="/tmp/fake-path.json"
        ), redirect_stdout(out):
            code = main(["benchmark", "shadow-rollout", str(self.root)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("equivalent_output=False", text)
        self.assertIn("project_map: 1 differing path(s)", text)

    def test_never_promotes_the_candidate_real_index_flow_is_unaffected(self) -> None:
        # System-level proof of the "never auto-promotes" acceptance
        # criterion: running shadow-rollout must not change what a real
        # `index`-style build_artifacts() call returns/dispatches to next.
        from simplicio_mapper.mapper.emit import _async_pipeline_min_files, build_artifacts

        threshold_before = _async_pipeline_min_files(str(self.root))
        main(["benchmark", "shadow-rollout", str(self.root), "--json"])
        threshold_after = _async_pipeline_min_files(str(self.root))
        self.assertEqual(threshold_before, threshold_after)
        # A real build_artifacts() call still succeeds and is dispatched by
        # the unchanged, unmodified threshold -- shadow-rollout never wrote
        # a pipeline-calibration.json (only pipeline-shadow.json).
        self.assertFalse((self.root / ".simplicio-loop" / "pipeline-calibration.json").exists())
        artifacts = build_artifacts(str(self.root))
        self.assertIn("project_map", artifacts)


if __name__ == "__main__":
    unittest.main()
