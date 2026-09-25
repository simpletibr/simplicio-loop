from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "context-graph" / "v1" / "fixtures" / "parity.json"
COMPATIBILITY_FIXTURE = ROOT / "contracts" / "context-graph" / "v1" / "fixtures" / "compatibility.json"
SCHEMA = ROOT / "contracts" / "context-graph" / "v1" / "schema.json"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.context_graph_contract import (  # noqa: E402
    CONTRACT_SCHEMA,
    build_public_contract,
    validate_public_contract,
)
from simplicio_mapper.contract import validate_instance  # noqa: E402


class ContextGraphContractTest(unittest.TestCase):
    def test_contract_exposes_public_identity_and_stable_ids(self) -> None:
        case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][1]
        contract = build_public_contract(case["graph"], repository_id="fixture-repo", generation="g-1")
        self.assertEqual(contract["schema"], CONTRACT_SCHEMA)
        self.assertEqual(contract["version"], 1)
        self.assertEqual(contract["repository_id"], "fixture-repo")
        self.assertEqual(contract["generation"], "g-1")
        self.assertEqual(contract["stable_ids"]["nodes"], ["file:main.py", "symbol:main"])
        self.assertEqual(contract["stable_ids"]["edges"], ["edge:defines"])
        self.assertEqual(validate_public_contract(contract)["valid"], True)

    def test_invalid_public_contract_reports_actionable_reason(self) -> None:
        case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][2]
        contract = build_public_contract(case["graph"], repository_id="fixture-repo", generation="g-2")
        contract["digest"] = "0" * 64
        report = validate_public_contract(contract)
        self.assertFalse(report["valid"])
        self.assertEqual(report["reason"], "digest_mismatch")

    def test_published_schema_accepts_supported_major_and_minor_only(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        cases = json.loads(COMPATIBILITY_FIXTURE.read_text(encoding="utf-8"))["cases"]
        by_name = {case["name"]: case["contract"] for case in cases}
        self.assertEqual(validate_instance(by_name["supported-major-v1"], schema), [])
        self.assertEqual(validate_instance(by_name["compatible-minor-v1.1"], schema), [])
        self.assertTrue(validate_instance(by_name["unknown-major-v2"], schema))

    def test_versioned_compatibility_fixture_matches_python_diagnostics(self) -> None:
        fixture = json.loads(COMPATIBILITY_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["supported_schema_majors"], [1])
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                report = validate_public_contract(case["contract"])
                public_diagnostic = {
                    "valid": report["valid"],
                    "reason": report["reason"],
                    "path": report["path"],
                }
                self.assertEqual(public_diagnostic, case["expected"])
                if not report["valid"]:
                    self.assertTrue(report["message"])
                    self.assertNotIn("nodes", report)
                    self.assertNotIn("relations", report)

    def test_unknown_major_diagnostic_identifies_received_and_supported_schema(self) -> None:
        cases = json.loads(COMPATIBILITY_FIXTURE.read_text(encoding="utf-8"))["cases"]
        contract = next(case["contract"] for case in cases if case["name"] == "unknown-major-v2")
        report = validate_public_contract(contract)
        self.assertEqual(report["reason"], "schema_major_unsupported")
        self.assertEqual(report["received"], "simplicio.context-graph-contract/v2")
        self.assertEqual(report["supported"], [CONTRACT_SCHEMA])


if __name__ == "__main__":
    unittest.main()
