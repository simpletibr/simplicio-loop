"""Executable ownership checks for Fast V3 issue #38."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "ADR-0001-fast-v3-ownership.md"
MATRIX = ROOT / "docs" / "fast-v3-contract-matrix.md"


class FastV3ArchitectureContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adr = ADR.read_text(encoding="utf-8")
        cls.matrix = MATRIX.read_text(encoding="utf-8")

    def test_documents_exist_and_name_the_issue(self):
        self.assertIn(
            "issue: https://github.com/wesleysimplicio/simplicio-fast/issues/38",
            self.adr,
        )
        self.assertIn("issue #38", self.matrix)

    def test_single_owners_are_declared(self):
        required = (
            "Mapper remains the only public ContextGraph producer",
            "Fast is the only owner of its compiled snapshot",
            "Dev CLI is the only owner of mechanical source editing",
            "Loop is the only owner of attempt progression",
            "Runtime is the only effect/policy authority in Full mode",
        )
        for statement in required:
            self.assertIn(statement, self.matrix)

    def test_profiles_and_engine_selection_are_explicit(self):
        for value in ("Full", "Loop standalone", "auto|rust|python|off"):
            self.assertIn(value, self.adr)
        for value in (
            "requested_engine",
            "selected_engine",
            "conformance_digest",
            "python_loaded",
            "rust_loaded",
        ):
            self.assertIn(value, self.matrix)

    def test_forbidden_boundaries_are_explicit(self):
        for document in (self.adr, self.matrix):
            self.assertIn("mmap offsets", document)
            self.assertIn("JSON", document)
            self.assertIn("source hashes", document)

    def test_failure_and_rollback_rules_are_present(self):
        for value in ("fail closed", "stale", "rolled_back", "rollback"):
            self.assertIn(value, self.adr + self.matrix)


if __name__ == "__main__":
    unittest.main()
