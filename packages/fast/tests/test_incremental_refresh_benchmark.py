from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.incremental_refresh import SCHEMA, main, run


class IncrementalRefreshBenchmarkTest(unittest.TestCase):
    def test_receipt_has_raw_repeated_samples_and_phase_timings(self) -> None:
        receipt = run(files=24, repetitions=2)
        self.assertEqual(SCHEMA, receipt["schema"])
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(24, receipt["workload"]["files"])
        self.assertEqual(2, len(receipt["raw"]["full_hash_validation_wall_ms"]))
        self.assertEqual(2, len(receipt["raw"]["metadata_validation_wall_ms"]))
        self.assertEqual(2, len(receipt["raw"]["metadata_phase_timings_ms"]))
        self.assertGreater(receipt["totals"]["speedup"], 0)

    def test_validation_and_cli_json_output(self) -> None:
        with self.assertRaisesRegex(ValueError, "repetitions"):
            run(files=1, repetitions=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            argv = [
                "incremental_refresh.py",
                "--files",
                "12",
                "--repetitions",
                "2",
                "--json-out",
                str(output),
            ]
            with patch("sys.argv", argv), patch("builtins.print"):
                main()
            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(SCHEMA, receipt["schema"])
            self.assertEqual(12, receipt["workload"]["files"])


if __name__ == "__main__":
    unittest.main()
