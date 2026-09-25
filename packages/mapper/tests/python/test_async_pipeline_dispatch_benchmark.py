"""Regression coverage for the issue #325 local profile benchmark."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import async_pipeline_dispatch_benchmark as benchmark  # noqa: E402


class ForcedProfileBenchmarkTest(unittest.TestCase):
    def test_forces_requested_profile_and_restores_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            benchmark, "build_artifacts", return_value={}
        ) as build:
            with mock.patch.dict(
                os.environ,
                {benchmark.ENV_PROFILE: "process", benchmark.ENV_KILL_SWITCH: "1"},
            ):
                benchmark._run_forced("sync", Path(tmp), Path(tmp) / "out")
                self.assertEqual(os.environ[benchmark.ENV_PROFILE], "process")
                self.assertEqual(os.environ[benchmark.ENV_KILL_SWITCH], "1")

        self.assertEqual(build.call_count, 1)
        # The environment is sampled by build_artifacts during the call, not
        # after _run_forced restores the caller's value.
        with tempfile.TemporaryDirectory() as tmp:
            seen: list[str | None] = []

            def capture(*_args: object, **_kwargs: object) -> dict:
                seen.append(os.environ.get(benchmark.ENV_PROFILE))
                return {}

            with mock.patch.object(benchmark, "build_artifacts", side_effect=capture):
                benchmark._run_forced("async", Path(tmp), Path(tmp) / "out")
        self.assertEqual(seen, ["async"])

    def test_auto_measurement_clears_override_and_records_selected_profile(self) -> None:
        receipt = {"execution_plan": {"selected_profile": "async"}}
        seen: list[str | None] = []

        def capture(*_args: object, **_kwargs: object) -> dict:
            seen.append(os.environ.get(benchmark.ENV_PROFILE))
            return receipt

        with tempfile.TemporaryDirectory(), mock.patch.object(
            benchmark, "_copy_real_fixture", return_value=3
        ), mock.patch.object(benchmark, "build_artifacts", side_effect=capture) as build:
            with mock.patch.dict(
                os.environ,
                {benchmark.ENV_PROFILE: "sync", benchmark.ENV_KILL_SWITCH: "1"},
            ):
                row = benchmark._dispatch_row("small", 0, True, runs=1)
                self.assertEqual(os.environ[benchmark.ENV_PROFILE], "sync")
                self.assertEqual(os.environ[benchmark.ENV_KILL_SWITCH], "1")

        self.assertEqual(build.call_count, 2)
        self.assertEqual(seen, [None, None])
        self.assertEqual(row["selected_profile"], "async")

    def test_report_identifies_explicit_profiles_and_auto_selection(self) -> None:
        crossover = [{
            "requested_file_count": 2,
            "actual_file_count": 2,
            "sync_wall_median_s": 0.2,
            "async_wall_median_s": 0.1,
            "sync_faster": False,
            "ratio_sync_over_async": 2.0,
        }]
        active = [{
            "size": "small",
            "file_count": 2,
            "selected_profile": "async",
            "cold_wall_median_s": 0.1,
            "cold_files_per_sec": 20.0,
            "warm_wall_median_s": 0.05,
        }]
        report = benchmark._render_markdown(
            crossover, active, 600, "2026-07-22T00:00:00Z", "3.12", None, None, 3
        )
        self.assertIn("SIMPLICIO_MAPPER_EXECUTION_PROFILE", report)
        self.assertIn("| small | 2 | async |", report)
        self.assertIn("Samples per profile/size: 3", report)

        historical = {"small": {"cold": {"wall_median_s": 0.3}}}
        contextual = benchmark._render_markdown(
            crossover,
            active,
            600,
            "2026-07-22T00:00:00Z",
            "3.12",
            historical,
            historical,
            3,
        )
        self.assertIn("Historical rows", contextual)

    def test_crossover_row_measures_both_explicit_profiles(self) -> None:
        with mock.patch.object(benchmark, "_make_tree", return_value=(Path("/source"), 2)), \
                mock.patch.object(benchmark, "_run_forced", side_effect=[0.2, 0.1]) as run:
            row = benchmark._crossover_row(2, runs=1)

        self.assertEqual([call.args[0] for call in run.call_args_list], ["sync", "async"])
        self.assertEqual(row["ratio_sync_over_async"], 2.0)
        self.assertFalse(row["sync_faster"])

    def test_main_writes_v2_machine_readable_receipt(self) -> None:
        active = {
            "size": "small",
            "file_count": 2,
            "selected_profile": "async",
            "cold_wall_median_s": 0.1,
            "cold_files_per_sec": 20.0,
            "warm_wall_median_s": 0.05,
        }
        crossover = {
            "requested_file_count": 2,
            "actual_file_count": 2,
            "sync_wall_median_s": 0.2,
            "async_wall_median_s": 0.1,
            "sync_faster": False,
            "ratio_sync_over_async": 2.0,
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            benchmark, "CROSSOVER_SIZES", [2]
        ), mock.patch.object(
            benchmark, "DISPATCH_SIZES", [("small", 0, True)]
        ), mock.patch.object(
            benchmark, "_crossover_row", return_value=crossover
        ), mock.patch.object(
            benchmark, "_dispatch_row", return_value=active
        ), mock.patch.object(
            benchmark, "MD_DOC_PATH", Path(tmp) / "report.md"
        ), mock.patch.object(
            benchmark, "JSON_DOC_PATH", Path(tmp) / "receipt.json"
        ), mock.patch.object(sys, "argv", ["benchmark", "--write", "--runs", "1"]), \
                redirect_stdout(StringIO()):
            self.assertEqual(benchmark.main(), 0)
            payload = json.loads(benchmark.JSON_DOC_PATH.read_text())

        self.assertEqual(payload["schema"], benchmark.SCHEMA)
        self.assertEqual(payload["dispatch_active"][0]["selected_profile"], "async")

    def test_committed_receipt_proves_auto_selected_async_at_every_size(self) -> None:
        payload = json.loads(benchmark.JSON_DOC_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], benchmark.SCHEMA)
        self.assertGreater(len(payload["dispatch_active"]), 0)
        self.assertEqual(
            {row["selected_profile"] for row in payload["dispatch_active"]}, {"async"}
        )


if __name__ == "__main__":
    unittest.main()
