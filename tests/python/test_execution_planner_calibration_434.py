from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simplicio_mapper.mapper.execution_planner import AUTO_CALIBRATION_ENV, plan_execution


class CalibrationPlanner434Test(unittest.TestCase):
    def _plan(self, payload: dict, file_count: int = 100):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.dict(os.environ, {AUTO_CALIBRATION_ENV: str(path)}, clear=True):
                return plan_execution(file_count=file_count, threshold=600)

    def test_auto_selects_lowest_compatible_p95_and_records_candidates(self) -> None:
        plan = self._plan(
            {
                "profiles": {
                    "sync": {"p95_ms": 30, "file_count_min": 0},
                    "async": {"p95_ms": 20, "file_count_min": 0},
                }
            }
        )
        self.assertEqual(plan.selected_profile, "async")
        self.assertEqual(plan.candidates, {"async": 20.0, "sync": 30.0})
        self.assertEqual(plan.predicted_p95_ms, 20.0)

    def test_mismatched_fingerprint_falls_back_explicitly(self) -> None:
        plan = self._plan({"fingerprint": {"machine": "definitely-not-this-host"}, "profiles": {"sync": {"p95_ms": 1}}})
        self.assertEqual(plan.selected_profile, "sync")
        self.assertEqual(plan.source, "auto")
        self.assertIn("fingerprint mismatch", plan.fallback_reason or "")


if __name__ == "__main__":
    unittest.main()
