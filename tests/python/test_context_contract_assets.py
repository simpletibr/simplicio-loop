from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from simplicio_mapper.context_contract import validate_context_graph, validate_context_payload

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "context-snapshot" / "v1"


class ContextContractAssetsTest(unittest.TestCase):
    def load(self, name: str) -> dict:
        return json.loads((CONTRACT / "fixtures" / name / "context-snapshot.json").read_text())

    def test_manifest_is_deterministic_and_declares_governance(self):
        manifest = json.loads((CONTRACT / "contract-manifest.json").read_text())
        self.assertEqual(manifest["owner"], "wesleysimplicio/simplicio-mapper")
        self.assertEqual(
            manifest["schema_ids"], ["simplicio.context-snapshot/v1", "simplicio.context-graph/v1"]
        )
        self.assertEqual(manifest["compatibility"]["future"], "fail-closed")
        self.assertEqual(manifest["limits"]["source_set"], 4096)
        proc = subprocess.run(
            [sys.executable, "scripts/check_context_contract_assets.py"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_fixture_categories_exist(self):
        for name in ("minimal", "full", "graph-multi-scale", "delta-revision"):
            self.assertTrue((CONTRACT / "fixtures" / "valid" / name / "context-snapshot.json").is_file())
        for name in (
            "missing-required",
            "future-schema",
            "hash-mismatch",
            "source-traversal",
            "unknown-property",
            "dev-cli-incompatible",
        ):
            self.assertTrue((CONTRACT / "fixtures" / "invalid" / name).exists())
        self.assertTrue((CONTRACT / "fixtures" / "invalid" / "oversized-representable.json").is_file())

    def test_api_accepts_valid_and_rejects_negative_fixtures(self):
        for name in (
            "valid/minimal",
            "valid/full",
            "valid/graph-multi-scale",
            "valid/delta-revision",
            "minimum",
            "latest",
        ):
            self.assertTrue(validate_context_payload(self.load(name))["valid"], name)
        expected = {
            "hash-mismatch": "SNAPSHOT_HASH_MISMATCH",
            "missing-required": "SNAPSHOT_SCHEMA_INVALID",
            "future-schema": "UNSUPPORTED_SCHEMA",
            "unknown-property": "SNAPSHOT_SCHEMA_INVALID",
            "dev-cli-incompatible": "UNSUPPORTED_SCHEMA",
        }
        for name, code in expected.items():
            report = validate_context_payload(self.load(f"invalid/{name}"))
            self.assertIn(code, {item["code"] for item in report["reason_codes"]}, name)
        graph = json.loads(
            (CONTRACT / "fixtures" / "invalid" / "source-traversal" / "context-graph.json").read_text()
        )
        self.assertIn(
            "SOURCE_HANDLE_TRAVERSAL",
            {item["code"] for item in validate_context_graph(graph)["reason_codes"]},
        )

    def test_oversized_declarative_fixture_materializes_limit_failure(self):
        payload = copy.deepcopy(self.load("valid/minimal"))
        payload["source_set"] = [f"src/{index}.py" for index in range(4097)]
        codes = {item["code"] for item in validate_context_payload(payload)["reason_codes"]}
        self.assertTrue(codes & {"SNAPSHOT_SCHEMA_INVALID", "PAYLOAD_TOO_LARGE"})

    def test_fixture_semantics(self):
        minimal, multi, full, delta = (
            self.load(name)
            for name in ("valid/minimal", "valid/graph-multi-scale", "valid/full", "valid/delta-revision")
        )
        self.assertEqual((minimal["graph"]["counts"]["nodes"], minimal["graph"]["counts"]["edges"]), (1, 0))
        self.assertTrue(all(multi["graph"]["counts"][scale] >= 1 for scale in ("micro", "meso", "macro")))
        self.assertGreaterEqual(multi["graph"]["counts"]["edges"], 1)
        self.assertGreaterEqual(len(full["source_set"]), 2)
        self.assertEqual(full["task"]["omissions"], [])
        self.assertNotEqual(
            (delta["source_set"], delta["snapshot_id"]), (minimal["source_set"], minimal["snapshot_id"])
        )
        self.assertEqual(self.load("latest"), full)
        self.assertEqual(self.load("minimum"), minimal)
