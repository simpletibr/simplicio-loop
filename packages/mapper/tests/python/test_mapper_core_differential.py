"""Contract tests for the reusable Rust mapper core and shadow harness."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper import _native

ROOT = Path(__file__).resolve().parents[2]


class NativeCapabilitySelectionTest(unittest.TestCase):
    def test_native_defaults_are_selected_per_capability(self) -> None:
        saved = (_native.HAS_NATIVE, copy.deepcopy(_native.CAPABILITIES))
        try:
            _native.HAS_NATIVE = True
            _native.CAPABILITIES = {"features": ["sha256", "imports"]}
            self.assertTrue(_native.native_default("files"))
            self.assertTrue(_native.native_default("imports"))
            self.assertFalse(_native.native_default("symbols"))
        finally:
            _native.HAS_NATIVE, _native.CAPABILITIES = saved


class DifferentialHarnessTest(unittest.TestCase):
    def test_mismatch_contains_reproducible_diff_and_never_promotes(self) -> None:
        from scripts.mapper_differential import compare_semantic_outputs

        expected = {"coverage": {"status": "complete"}, "artifact": [{"x": 1}]}
        actual = {"coverage": {"status": "complete"}, "artifact": [{"x": 2}]}
        result = compare_semantic_outputs(expected, actual)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["diff"], [{"path": "$.artifact[0].x", "expected": 1, "actual": 2}])
        self.assertFalse(result["native_default"])

    def test_unsupported_adapter_is_not_a_match(self) -> None:
        from scripts.mapper_differential import unsupported_result

        result = unsupported_result("rust_adapter_unavailable")
        self.assertEqual(result["status"], "unsupported")
        self.assertFalse(result["native_default"])

    def test_match_without_native_default_cannot_build_native_parity(self) -> None:
        from scripts.mapper_capability_matrix import build_matrix

        report = {
            "results": [
                {
                    "language": "python",
                    "capability": "files",
                    "contract_version": "v1",
                    "status": "match",
                    "native_default": False,
                }
            ]
        }
        matrix = build_matrix(ROOT, report)
        row = next(
            item
            for item in matrix["capabilities"]
            if item["language"] == "python" and item["capability"] == "files"
        )
        self.assertEqual(row["status"], "MISSING")
        self.assertFalse(row["native_default"])

    def test_matrix_rejects_stale_mapper_fingerprint(self) -> None:
        from scripts.mapper_capability_matrix import load_matrix, validate_matrix

        matrix = load_matrix(ROOT / "contracts/mapper-core/v1/capability-matrix.json")
        matrix["behavior_fingerprint"] = "sha256:" + "0" * 64
        errors = validate_matrix(matrix, ROOT)
        self.assertIn("behavior_fingerprint_stale", errors)

    def test_report_round_trip_is_byte_stable(self) -> None:
        from scripts.mapper_differential import write_report

        payload = {
            "schema": "simplicio.mapper-differential/v1",
            "status": "match",
            "results": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = write_report(Path(directory), payload)
            first = path.read_bytes()
            write_report(Path(directory), payload)
            self.assertEqual(first, path.read_bytes())
            decoded = json.loads(first)
            self.assertEqual(decoded["report_digest"], "sha256:" + hashlib.sha256(
                json.dumps(
                    {key: value for key, value in decoded.items() if key != "report_digest"},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest())


if __name__ == "__main__":
    unittest.main()
