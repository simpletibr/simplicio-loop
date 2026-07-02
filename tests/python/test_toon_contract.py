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
    strict_equal,
)


class StrictEqualTest(unittest.TestCase):
    """strict_equal must NOT treat bool and int as interchangeable, unlike
    plain ``==`` (autoresearch pilot finding, issue #151 iteration 1)."""

    def test_bool_and_equal_int_are_not_strict_equal(self) -> None:
        # Guards against the exact Python quirk found in issue #151
        # iteration 1: plain ``==`` treats True/1 and False/0 as equal;
        # strict_equal must not.
        self.assertFalse(strict_equal(True, 1))
        self.assertFalse(strict_equal(1, True))
        self.assertFalse(strict_equal(False, 0))

    def test_matching_bools_and_ints_are_strict_equal(self) -> None:
        self.assertTrue(strict_equal(True, True))
        self.assertTrue(strict_equal(1, 1))
        self.assertTrue(strict_equal(False, False))

    def test_nested_bool_int_mismatch_detected_in_dict_and_list(self) -> None:
        self.assertFalse(strict_equal({"active": True}, {"active": 1}))
        self.assertFalse(strict_equal([True, 2], [1, 2]))
        self.assertTrue(strict_equal({"active": True, "n": 1}, {"active": True, "n": 1}))

    def test_non_bool_scalars_use_plain_equality(self) -> None:
        self.assertTrue(strict_equal("a", "a"))
        self.assertTrue(strict_equal(1.5, 1.5))
        self.assertTrue(strict_equal(None, None))


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
