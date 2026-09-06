"""Tests for the in-repository Runtime adapter boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RuntimeAdapterBoundaryTest(unittest.TestCase):
    def test_core_has_no_runtime_authority_or_effect_dependency(self) -> None:
        core_source = (ROOT / "rust/mapper-core/src/lib.rs").read_text(encoding="utf-8")
        core_manifest = (ROOT / "rust/mapper-core/Cargo.toml").read_text(encoding="utf-8")
        for forbidden in ("EffectTransaction", "std::fs", "std::process", "simplicio-runtime"):
            self.assertNotIn(forbidden, core_source)
        self.assertNotIn("simplicio-native-mapper", core_manifest)

    def test_request_and_result_contract_are_versioned(self) -> None:
        from scripts.mapper_runtime_adapter import build_request, normalize_result

        request = build_request(
            "imports",
            "python",
            [("src/main.py", "import os\n")],
        )
        self.assertEqual(request["schema"], "simplicio.mapper-core-request/v1")
        self.assertEqual(request["contract_version"], "v1")

        result = normalize_result(
            {
                "schema": "simplicio.mapper-core-result/v1",
                "contract_version": "v1",
                "capability": "imports",
                "language": "python",
                "coverage": {"status": "complete"},
                "artifact": [{"path": "src/main.py", "imports": ["os"]}],
            }
        )
        self.assertEqual(result["artifact"][0]["imports"], ["os"])


if __name__ == "__main__":
    unittest.main()
