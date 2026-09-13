"""Structure tests for the checked-in LLM orientation cache."""

from __future__ import annotations

import hashlib
import re
import subprocess
import unittest
from pathlib import Path

from simplicio_mapper.toon import decode_toon


ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "docs" / "LLM_ORIENTATION.toon"
SECTIONS = (
    "meta",
    "project",
    "source_of_truth",
    "skills",
    "commands",
    "contracts",
    "receipts",
    "governors",
    "tests",
    "workflow",
    "handoff",
    "forbidden",
    "known_limits",
    "freshness",
)
REQUIRED_COMMANDS = {
    "index",
    "scan",
    "inspect",
    "handoff",
    "orient",
    "contract-validate",
    "init",
    "store",
    "receipts",
}
REQUIRED_CONTRACTS = {
    "simplicio.mapper-artifact-set/v1",
    "simplicio.mapper-index/v1",
    "simplicio.context-snapshot/v1",
    "simplicio.context-graph/v1",
    "simplicio.task-context/v1",
    "simplicio.task-intent/v1",
    "simplicio.mapper-fast-handoff/v1",
    "simplicio.mapper-store-status/v1",
    "simplicio.io/v1",
}
REQUIRED_SOURCES = {
    "AGENTS.md",
    "docs/LLM_OPERATING_INSTRUCTIONS.md",
    "docs/CLI_COMMANDS.md",
    "docs/contract-registry.md",
    "docs/WORKER_ARTIFACT_CONTRACT.md",
    "contracts/mapper-artifacts/v1/README.md",
    "contracts/context-snapshot/v1/CONTRACT.md",
    "contracts/task-orientation/v1/README.md",
    "contracts/mapper-fast-handoff/v1/schema.json",
    "contracts/io/v1/README.md",
}

REQUIRED_HANDOFF_OWNERS = {"mapper", "fast", "dev-cli", "runtime", "loop"}


def load_pack() -> dict:
    return decode_toon(PACK.read_text(encoding="utf-8"))


class LlmOrientationPackTest(unittest.TestCase):
    def test_pack_has_deterministic_required_sections(self) -> None:
        pack = load_pack()
        self.assertEqual(tuple(pack), SECTIONS)
        self.assertEqual(pack["meta"]["schema"], "simplicio.llm-orientation/v1")
        self.assertEqual(pack["meta"]["role"], "orientation-cache")
        self.assertEqual(pack["meta"]["execution_contract"], "none")
        self.assertTrue(pack["meta"]["source_of_truth_only"])

    def test_pack_lists_authoritative_sources_with_current_digests(self) -> None:
        entries = {entry["path"]: entry for entry in load_pack()["source_of_truth"]}
        self.assertTrue(REQUIRED_SOURCES.issubset(entries))
        for path, entry in entries.items():
            source = ROOT / path
            self.assertTrue(source.is_file(), path)
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$", path)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(entry["sha256"], digest, path)
            self.assertIn(
                entry["authority"],
                {"normative", "canonical", "discovery", "generated-mirror", "operational", "reference-template"},
            )

    def test_pack_records_real_and_unavailable_commands(self) -> None:
        commands = {entry["id"]: entry for entry in load_pack()["commands"]}
        self.assertTrue(REQUIRED_COMMANDS.issubset(commands))
        for command_id in ("index", "scan", "inspect", "handoff", "orient", "contract-validate"):
            entry = commands[command_id]
            self.assertEqual(entry["status"], "available", command_id)
            self.assertIn("--help", entry["verified_by"], command_id)
            self.assertTrue(entry["usage"].startswith("simplicio-mapper"), command_id)
        for command_id in ("init", "store", "receipts"):
            entry = commands[command_id]
            self.assertEqual(entry["status"], "unavailable", command_id)
            self.assertIn("simplicio-mapper --help", entry["verified_by"], command_id)
            self.assertEqual(entry["usage"], "unavailable")

        help_result = subprocess.run(
            ["simplicio-mapper", "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("index <path>", help_result.stdout)
        self.assertIn("scan <path>", help_result.stdout)
        self.assertIn("inspect <path>", help_result.stdout)
        self.assertIn("handoff <path>", help_result.stdout)

    def test_pack_records_contract_owners_and_formats(self) -> None:
        contracts = {entry["id"]: entry for entry in load_pack()["contracts"]}
        self.assertTrue(REQUIRED_CONTRACTS.issubset(contracts))
        for contract_id, entry in contracts.items():
            self.assertEqual(entry["version"], "v1", contract_id)
            self.assertTrue(entry["path"].startswith("contracts/"), contract_id)
            self.assertIn(entry["owner"], {"mapper", "mapper-store", "runtime", "shared"})
            self.assertIn(entry["format"], {"json", "json-schema", "registry"})
        self.assertEqual(contracts["simplicio.mapper-artifact-set/v1"]["format"], "json")
        self.assertEqual(contracts["simplicio.context-snapshot/v1"]["format"], "json")

    def test_pack_records_receipts_governors_and_handoff(self) -> None:
        receipts = {entry["id"]: entry for entry in load_pack()["receipts"]}
        self.assertIn("mapper-artifact-set", receipts)
        self.assertIn("fast-handoff", receipts)
        self.assertIn("yool", receipts)
        for entry in receipts.values():
            self.assertIn(entry["owner"], {"mapper", "mapper-store", "fast", "runtime", "yool"})
            self.assertTrue(entry["format"])
        governors = load_pack()["governors"]
        self.assertIn("fail_closed", governors)
        self.assertIn("partial", governors)
        self.assertIn("blocked", governors)
        self.assertIn("cpu", governors)
        self.assertIn("disk", governors)
        self.assertEqual(
            {entry["owner"] for entry in load_pack()["handoff"]},
            REQUIRED_HANDOFF_OWNERS,
        )

    def test_pack_rejects_secret_values_and_prohibited_flags(self) -> None:
        raw = PACK.read_text(encoding="utf-8")
        for pattern in (
            r"\bsk-[A-Za-z0-9]{20,}\b",
            r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
            r"(?i)(?:api[_ -]?key|password|secret)\s*[:=]\s*[^<>{}\s]+",
        ):
            self.assertIsNone(re.search(pattern, raw), pattern)
        for flag_name in ("serial", "max-workers", "retry-budget", "fan-out"):
            self.assertNotIn(f"--{flag_name}", raw)
        forbidden = load_pack()["forbidden"]
        self.assertTrue(any("secret" in item.lower() for item in forbidden))
        self.assertTrue(any("provider" in item.lower() for item in forbidden))

    def test_pack_freshness_points_to_observed_revision(self) -> None:
        pack = load_pack()
        freshness = pack["freshness"]
        self.assertEqual(freshness["observed_revision"], pack["project"]["commit"])
        self.assertEqual(freshness["default_branch"], "main")
        self.assertIn("refresh", freshness["refresh_when"].lower())


if __name__ == "__main__":
    unittest.main()
