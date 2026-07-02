"""Wire scripts/toon_contract_runner.py into the unit suite (issue #149).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from toon_contract_runner import (  # noqa: E402
    _load_manifest,
    check_invalid_case,
    check_valid_case,
)


class ToonContractConformanceTest(unittest.TestCase):
    """Every case in fixtures/toon-golden/ must pass against this repo's codec."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = _load_manifest()

    def test_manifest_lists_at_least_one_case_of_each_kind(self) -> None:
        self.assertGreater(len(self.manifest.get("valid", [])), 0)
        self.assertGreater(len(self.manifest.get("invalid", [])), 0)

    def test_all_valid_cases_conform(self) -> None:
        for case in self.manifest.get("valid", []):
            with self.subTest(case=case["id"]):
                failures = check_valid_case(case["id"])
                self.assertEqual(failures, [], "\n".join(failures))

    def test_all_invalid_cases_conform(self) -> None:
        for case in self.manifest.get("invalid", []):
            with self.subTest(case=case["id"]):
                failures = check_invalid_case(case["id"])
                self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
