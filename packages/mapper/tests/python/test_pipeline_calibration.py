"""Tests for `simplicio_mapper.mapper.pipeline_calibration` (issue #279
Phase-0: opt-in, per-machine sync/async pipeline-dispatch calibration,
ADR-010).

Covers: calibration-file read/write round trip, every fail-safe rejection
path in `load_calibrated_threshold` (missing/corrupt/wrong-schema/invalid
threshold -- must return `None`, never raise), and a real (small,
fast-sized) `run_calibration()` invocation that exercises the actual
sync-vs-async measurement + crossover-selection logic end to end.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.pipeline_calibration import (  # noqa: E402
    CALIBRATION_FILENAME,
    CALIBRATION_SCHEMA,
    calibration_file_path,
    load_calibrated_threshold,
    run_calibration,
    write_calibration,
)


class CalibrationFilePathTest(unittest.TestCase):
    def test_path_is_under_output_dir(self) -> None:
        path = calibration_file_path("/repo", output_dir=".simplicio")
        self.assertTrue(path.replace("\\", "/").endswith(".simplicio/" + CALIBRATION_FILENAME))


class LoadCalibratedThresholdTest(unittest.TestCase):
    """Every branch must fail safe (return None), never raise."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_corrupt_json_returns_none(self) -> None:
        target = self.dir / ".simplicio" / CALIBRATION_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{not valid json", encoding="utf-8")
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_non_dict_json_returns_none(self) -> None:
        target = self.dir / ".simplicio" / CALIBRATION_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_wrong_schema_returns_none(self) -> None:
        write_calibration(
            str(self.dir), {"schema": "wrong/v1", "recommended_threshold": 10}
        )
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_missing_threshold_field_returns_none(self) -> None:
        write_calibration(str(self.dir), {"schema": CALIBRATION_SCHEMA})
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_non_integer_threshold_returns_none(self) -> None:
        write_calibration(
            str(self.dir),
            {"schema": CALIBRATION_SCHEMA, "recommended_threshold": "600"},
        )
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_boolean_threshold_returns_none(self) -> None:
        # bool is an int subclass in Python -- must be explicitly rejected.
        write_calibration(
            str(self.dir), {"schema": CALIBRATION_SCHEMA, "recommended_threshold": True}
        )
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_non_positive_threshold_returns_none(self) -> None:
        write_calibration(
            str(self.dir), {"schema": CALIBRATION_SCHEMA, "recommended_threshold": 0}
        )
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))
        write_calibration(
            str(self.dir), {"schema": CALIBRATION_SCHEMA, "recommended_threshold": -3}
        )
        self.assertIsNone(load_calibrated_threshold(str(self.dir)))

    def test_valid_payload_round_trips(self) -> None:
        path = write_calibration(
            str(self.dir), {"schema": CALIBRATION_SCHEMA, "recommended_threshold": 250}
        )
        self.assertTrue(os.path.exists(path))
        self.assertEqual(load_calibrated_threshold(str(self.dir)), 250)


class WriteCalibrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_writes_valid_json_atomically_no_stray_tmp_file(self) -> None:
        path = write_calibration(
            str(self.dir), {"schema": CALIBRATION_SCHEMA, "recommended_threshold": 99}
        )
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["recommended_threshold"], 99)
        leftovers = [p for p in os.listdir(os.path.dirname(path)) if ".tmp-" in p]
        self.assertEqual(leftovers, [])

    def test_creates_output_dir_if_missing(self) -> None:
        target_out = self.dir / "nested" / "out"
        path = write_calibration(
            str(self.dir),
            {"schema": CALIBRATION_SCHEMA, "recommended_threshold": 10},
            output_dir=str(Path("nested") / "out"),
        )
        self.assertTrue(os.path.isdir(target_out))
        self.assertTrue(os.path.exists(path))


class RunCalibrationTest(unittest.TestCase):
    """Exercises the real measurement path end to end with tiny sizes so the
    unit-test suite stays fast -- this is the calibration itself acting as
    its own perf benchmark, at a scale suited to CI rather than a full
    multi-minute local run (see `simplicio-mapper benchmark
    pipeline-threshold` / the ADR-010 write-up for the full-size default).
    """

    def test_produces_a_well_formed_payload(self) -> None:
        payload = run_calibration(sizes=(3, 6), runs=1, default_threshold=600)
        self.assertEqual(payload["schema"], CALIBRATION_SCHEMA)
        self.assertIn("recommended_threshold", payload)
        self.assertIn("calibrated", payload)
        self.assertEqual(payload["hardcoded_default_threshold"], 600)
        self.assertEqual(len(payload["sizes_measured"]), 2)
        for row in payload["sizes_measured"]:
            self.assertIn("sync_wall_median_s", row)
            self.assertIn("async_wall_median_s", row)
            self.assertIn("async_faster", row)
            self.assertGreaterEqual(row["actual_file_count"], row["requested_file_count"])

    def test_falls_back_to_default_when_async_never_wins_at_tiny_sizes(self) -> None:
        # At tiny sizes async scheduling overhead reliably dominates (this
        # is exactly ADR-009's own documented small-tree regression), so the
        # calibration should honestly report "not calibrated" and keep the
        # caller-supplied default rather than invent an unmeasured win.
        payload = run_calibration(sizes=(2,), runs=1, default_threshold=777)
        if not payload["calibrated"]:
            self.assertEqual(payload["recommended_threshold"], 777)

    def test_does_not_leak_the_env_var_override(self) -> None:
        os.environ.pop("SIMPLICIO_MAPPER_EXECUTION_PROFILE", None)
        run_calibration(sizes=(3,), runs=1)
        self.assertNotIn("SIMPLICIO_MAPPER_EXECUTION_PROFILE", os.environ)

    def test_restores_a_pre_existing_env_var_override(self) -> None:
        os.environ["SIMPLICIO_MAPPER_EXECUTION_PROFILE"] = "sync"
        try:
            run_calibration(sizes=(3,), runs=1)
            self.assertEqual(
                os.environ["SIMPLICIO_MAPPER_EXECUTION_PROFILE"], "sync"
            )
        finally:
            os.environ.pop("SIMPLICIO_MAPPER_EXECUTION_PROFILE", None)


if __name__ == "__main__":
    unittest.main()
