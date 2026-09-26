"""Tests for simplicio_mapper.savings (issue #174 savings-event ledger).

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

from simplicio_mapper.savings import (  # noqa: E402
    SAVINGS_EVENT_SCHEMA,
    estimate_tokens,
    record_savings_event,
)


class EstimateTokensTest(unittest.TestCase):
    def test_heuristic_is_chars_div_4(self) -> None:
        self.assertEqual(estimate_tokens("abcd" * 10), 10)

    def test_empty_text_is_zero(self) -> None:
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_nonempty_short_text_is_at_least_one(self) -> None:
        self.assertEqual(estimate_tokens("a"), 1)


class RecordSavingsEventTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self._env_backup = dict(os.environ)
        os.environ.pop("SIMPLICIO_DISABLE_RUN_LOG", None)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        os.environ.clear()
        os.environ.update(self._env_backup)

    def _ledger_path(self) -> Path:
        return Path(self.root) / ".simplicio-loop" / "ledger" / "savings-events.jsonl"

    def test_writes_one_jsonl_record_with_expected_shape(self) -> None:
        path = record_savings_event(
            self.root,
            source="native-delegation:impact",
            baseline_tokens=1000,
            actual_tokens=100,
            proof_kind="estimated",
            note="test note",
        )
        self.assertEqual(path, self._ledger_path())
        lines = self._ledger_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["schema"], SAVINGS_EVENT_SCHEMA)
        self.assertEqual(event["source"], "native-delegation:impact")
        self.assertEqual(event["proof_kind"], "estimated")
        self.assertEqual(event["note"], "test note")
        self.assertEqual(event["tokens"]["baseline"], 1000)
        self.assertEqual(event["tokens"]["actual"], 100)
        self.assertEqual(event["tokens"]["saved"], 900)
        self.assertEqual(event["tokens"]["pct_saved"], 90.0)

    def test_appends_multiple_events(self) -> None:
        record_savings_event(self.root, source="a", baseline_tokens=10, actual_tokens=5)
        record_savings_event(self.root, source="b", baseline_tokens=20, actual_tokens=5)
        lines = self._ledger_path().read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_zero_baseline_reports_zero_pct_saved_without_dividing_by_zero(self) -> None:
        record_savings_event(self.root, source="edge", baseline_tokens=0, actual_tokens=0)
        event = json.loads(self._ledger_path().read_text(encoding="utf-8").strip())
        self.assertEqual(event["tokens"]["pct_saved"], 0.0)

    def test_disable_env_var_skips_write(self) -> None:
        os.environ["SIMPLICIO_DISABLE_RUN_LOG"] = "1"
        result = record_savings_event(self.root, source="x", baseline_tokens=1, actual_tokens=1)
        self.assertIsNone(result)
        self.assertFalse(self._ledger_path().exists())


if __name__ == "__main__":
    unittest.main()
