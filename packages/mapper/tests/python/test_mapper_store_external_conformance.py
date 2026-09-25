from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.mapper_store_external_conformance import (
    SCHEMA,
    _host_platform,
    _platform_for_scenario,
    _receipt,
    _runtime_backed,
    canonical_hash,
)
from simplicio_mapper.contract import validate_instance


class ExternalConformanceProducerTest(unittest.TestCase):
    def test_receipt_hash_excludes_only_self_hash(self) -> None:
        receipt = _receipt(
            scenario="fresh standalone",
            repositories={name: {"revision": "a" * 40} for name in ("mapper", "loop", "dev-cli", "runtime")},
            working_tree_clean=True,
            status="pass",
            ok=True,
            reason="measured",
            platform_name="macOS",
        )
        self.assertEqual(receipt["schema"], SCHEMA)
        self.assertEqual(receipt["evidence_hash"], canonical_hash(receipt))

    def test_receipt_matches_published_contract(self) -> None:
        receipt = _receipt(
            scenario="fresh standalone",
            repositories={name: {"revision": "a" * 40} for name in ("mapper", "loop", "dev-cli", "runtime")},
            working_tree_clean=True,
            status="pass",
            ok=True,
            reason="measured",
            platform_name="macOS",
        )
        schema_path = Path(__file__).parents[2] / "contracts/mapper-store/v1/schemas/conformance-evidence.schema.json"
        errors = validate_instance(receipt, json.loads(schema_path.read_text(encoding="utf-8")))
        self.assertEqual(errors, [])

    def test_unsupported_scenario_is_explicitly_unverified(self) -> None:
        receipt = _receipt(
            scenario="Windows",
            repositories={name: {"revision": "b" * 40} for name in ("mapper", "loop", "dev-cli", "runtime")},
            working_tree_clean=True,
            status="unverified",
            ok=False,
            reason="scenario requires Windows",
            platform_name=_host_platform(),
        )
        self.assertEqual(receipt["status"], "unverified")
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["evidence_hash"], canonical_hash(receipt))

    def test_platform_mapping_is_not_a_simulation(self) -> None:
        self.assertEqual(_platform_for_scenario("Windows"), "Windows")
        self.assertIsNone(_platform_for_scenario("fresh standalone"))

    def test_runtime_lane_requires_an_installed_binary(self) -> None:
        ok, reason, observations = _runtime_backed(
            mapper_root=Path("."),
            runtime_binary=None,
            legacy_memory_dir=None,
            upgrade=False,
            timeout=1.0,
        )
        self.assertFalse(ok)
        self.assertIn("--runtime-binary", reason)
        self.assertEqual(observations, {})
