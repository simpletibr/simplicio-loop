"""Keep ContextSnapshot schema identifiers under their canonical owners."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "simplicio_mapper"
SCHEMA_IDS = {"simplicio.context-snapshot/v1", "simplicio.context-graph/v1"}
CANONICAL_OWNERS = {
    "cli/_snapshot.py",
    "context_contract.py",
    "context_snapshot.py",
    "contract.py",
    "release_manifest.py",
}


def schema_id_violations(package: Path) -> list[Path]:
    violations: list[Path] = []
    for source in package.rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        relative = source.relative_to(package).as_posix()
        if SCHEMA_IDS.intersection(literals) and relative not in CANONICAL_OWNERS:
            violations.append(source)
    return violations


class ContextContractOwnershipTests(unittest.TestCase):
    def test_schema_identifiers_only_appear_in_canonical_owners(self) -> None:
        self.assertEqual(schema_id_violations(PACKAGE), [])

    def test_scanner_rejects_a_shadow_schema_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary)
            shadow = package / "shadow_model.py"
            shadow.write_text('SCHEMA = "simplicio.context-snapshot/v1"\n', encoding="utf-8")
            self.assertEqual(schema_id_violations(package), [shadow])
