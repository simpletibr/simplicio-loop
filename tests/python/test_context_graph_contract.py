from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "contracts" / "context-graph" / "v1" / "fixtures" / "parity.json"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.context_graph_contract import (  # noqa: E402
    CONTRACT_SCHEMA,
    build_public_contract,
    validate_public_contract,
)


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

    def test_node_runner_matches_python_public_projection(self) -> None:
        result = subprocess.run(
            ["node", "bin/context-graph-contract.js", str(FIXTURE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        node_report = json.loads(result.stdout)
        self.assertEqual(node_report["schema"], "simplicio.context-graph-parity/v1")
        self.assertEqual(node_report["channels"]["node"]["status"], "pass")
        self.assertEqual(node_report["channels"]["python"]["status"], "pass")
        self.assertIn(node_report["channels"]["rust"]["status"], {"pass", "skipped"})
        self.assertEqual(node_report["divergences"], [])


if __name__ == "__main__":
    unittest.main()
