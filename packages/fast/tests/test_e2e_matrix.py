from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from benchmarks.e2e_matrix import SCHEMA, run_matrix


class E2EMatrixTest(unittest.TestCase):
    def test_python_matrix_freezes_identity_and_observes_s0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_matrix(
                files=2, functions=3, repetitions=10, repo_root=Path(directory)
            )

        self.assertEqual(SCHEMA, result["schema"])
        self.assertEqual("partial", result["status"])
        self.assertEqual(64, len(result["corpus"]["sha256"]))
        self.assertEqual(10, result["scenarios"]["S0_BASELINE"]["valid_repetitions"])
        self.assertEqual("complete", result["scenarios"]["S0_BASELINE"]["status"])
        self.assertEqual(
            "whitespace-v1-estimate",
            result["scenarios"]["S0_BASELINE"]["token_measurement"],
        )

    def test_unavailable_cells_are_null_with_reason_codes(self) -> None:
        result = run_matrix(files=2, functions=3, repetitions=10)

        for name in ("S1_RUNTIME", "S2_RUNTIME_LOOP", "S3_FULL_STACK"):
            scenario = result["scenarios"][name]
            self.assertEqual("blocked", scenario["status"])
            self.assertFalse(scenario["observed"])
            self.assertEqual(0, scenario["valid_repetitions"])
            self.assertTrue(
                all(value is None for value in scenario["metrics"].values())
            )
            self.assertTrue(scenario["reason_code"])

    def test_requires_ten_valid_repetitions(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least 10"):
            run_matrix(files=1, functions=1, repetitions=9)


if __name__ == "__main__":
    unittest.main()
