from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
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
REQUIRED_FIELDS = {
    "meta": {"format", "kind", "purpose", "language", "not_a_contract"},
    "project": {
        "name",
        "package_version",
        "commit",
        "branch",
        "default_branch",
        "module_entrypoint",
    },
    "source_of_truth": {"authoritative", "source"},
    "skills": {"skill"},
    "commands": {"entrypoint", "top_level", "command", "nested"},
    "contracts": {"component", "format"},
    "receipts": {"owner", "formats", "rule"},
    "governors": {"limits", "freshness", "effects"},
    "tests": {"focused", "native"},
    "workflow": {"sequence"},
    "handoff": {"loop_standalone", "runtime_backed"},
    "forbidden": {"authority", "access", "secret_material"},
    "known_limits": {"binary", "integration", "availability"},
    "freshness": {"captured_at", "index", "recheck"},
}
TOP_LEVEL_COMMANDS = {
    "build",
    "refresh",
    "ingest",
    "query",
    "search",
    "context",
    "navigate",
    "impact",
    "stats",
    "query-plan",
    "segments",
    "understand",
    "plan",
    "delivery",
    "apply",
    "changeset",
    "doctor",
    "rollout",
    "serve",
    "base",
    "overlay",
    "delta",
    "handoff",
    "merge",
    "semantic-score",
    "capabilities",
    "parser-payload",
    "pin",
    "release",
    "gc",
    "watch",
}
CHANGESET_ACTIONS = {
    "prepare",
    "validate",
    "seal",
    "inspect",
    "export-json",
    "materialize",
    "reconcile",
    "recover",
}
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|ghp|github_pat|xox[baprs])-[a-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[a-z0-9._~+/=-]{16,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|"
        r"secret(?:[_-]?material)?)\s*[:=]\s*"
        r"(?!none\b|absent\b|unavailable\b|redacted\b|not_present\b|no_provider_credentials_or_tokens\b)"
        r"[^\s|]+"
    ),
)


def parse_pack(text: str) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line or line != line.rstrip() or "\t" in line:
            raise AssertionError(f"invalid line {line_number}")
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            if current in sections or current not in SECTIONS:
                raise AssertionError(f"invalid section {current!r}")
            sections[current] = []
            continue
        if current is None:
            raise AssertionError(f"entry before section at {line_number}")
        key, separator, value = line.partition("=")
        if not separator or not key or not value:
            raise AssertionError(f"invalid entry at {line_number}")
        sections[current].append((key, value))
    if tuple(sections) != SECTIONS:
        raise AssertionError(f"section order mismatch: {tuple(sections)}")
    return sections


def values(entries: Iterable[tuple[str, str]], key: str) -> list[str]:
    return [value for entry_key, value in entries if entry_key == key]


def assert_no_secret_material(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            raise AssertionError(f"secret-like material at {match.start()}")


def command_help(command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    source_path = str(ROOT / "src")
    env["PYTHONPATH"] = source_path + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "simplicio_fast.cli", command, "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class LlmOrientationPackTest(unittest.TestCase):
    def test_pack_is_deterministic_and_has_required_structure(self) -> None:
        first = PACK.read_text(encoding="utf-8")
        second = PACK.read_text(encoding="utf-8")
        self.assertEqual(first, second)
        parsed = parse_pack(first)
        self.assertEqual(set(parsed), set(SECTIONS))
        for section, required in REQUIRED_FIELDS.items():
            self.assertTrue(
                required.issubset({key for key, _ in parsed[section]}),
                section,
            )
        self.assertEqual(values(parsed["meta"], "not_a_contract"), ["true"])
        self.assertEqual(values(parsed["project"], "default_branch"), ["master"])

    def test_sources_and_skills_are_hash_anchored(self) -> None:
        parsed = parse_pack(PACK.read_text(encoding="utf-8"))
        source_items = values(parsed["source_of_truth"], "source")
        self.assertGreaterEqual(len(source_items), 6)
        for item in source_items:
            path, digest = item.split("|", 1)
            self.assertTrue((ROOT / path).is_file(), path)
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            self.assertEqual(digest, f"sha256:{actual}", path)
        for item in values(parsed["skills"], "skill"):
            name, path, digest = item.split("|", 2)
            self.assertTrue(name)
            self.assertTrue((ROOT / path).is_file(), path)
            self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")
            actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            self.assertEqual(digest, f"sha256:{actual}", path)

    def test_commands_are_help_proven_and_complete(self) -> None:
        parsed = parse_pack(PACK.read_text(encoding="utf-8"))
        command_items = values(parsed["commands"], "command")
        names = {item.split("|", 1)[0] for item in command_items}
        self.assertEqual(names, TOP_LEVEL_COMMANDS)
        for item in command_items:
            name, help_field, role = item.split("|", 2)
            self.assertEqual(help_field, f"help=simplicio-fast {name} --help")
            self.assertTrue(role.startswith("role="))
        self.assertIn("plan|help=simplicio-fast plan --help|role=compile_plandag", command_items)
        self.assertIn("doctor|help=simplicio-fast doctor --help|role=readiness_fail_closed", command_items)
        nested = values(parsed["commands"], "nested")
        self.assertTrue(
            any(
                item.startswith("changeset:") and item.endswith("help=simplicio-fast changeset <action> --help")
                for item in nested
            )
        )
        changeset_item = next(item for item in nested if item.startswith("changeset:"))
        self.assertEqual(set(changeset_item.split(":", 1)[1].split("|", 1)[0].split(",")), CHANGESET_ACTIONS)
        self.assertEqual(values(parsed["commands"], "status"), ["absent;use=doctor,stats"])
        self.assertEqual(values(parsed["commands"], "plandag"), ["absent;use=plan"])

    def test_real_cli_help_matches_the_documented_surface(self) -> None:
        top = command_help("--help")
        self.assertEqual(top.returncode, 0, top.stderr)
        for command in TOP_LEVEL_COMMANDS | {"changeset"}:
            result = command_help(command)
            self.assertEqual(result.returncode, 0, f"{command}: {result.stderr}")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        cross_repo = subprocess.run(
            [sys.executable, "-m", "simplicio_fast.cross_repo_cli", "validate", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(cross_repo.returncode, 0, cross_repo.stderr)

    def test_secret_rejection_and_fail_closed_statements(self) -> None:
        parsed = parse_pack(PACK.read_text(encoding="utf-8"))
        pack_text = PACK.read_text(encoding="utf-8")
        assert_no_secret_material(pack_text)
        self.assertTrue(any(value.startswith("source_truth=authoritative") for value in values(parsed["forbidden"], "authority")))
        self.assertTrue(any(value.startswith("raw_snapshot_offsets=forbidden") for value in values(parsed["forbidden"], "access")))
        self.assertIn("no_provider_credentials_or_tokens", values(parsed["forbidden"], "secret_material"))
        synthetic_key = "api" + "_key=" + "x" * 32
        with self.assertRaises(AssertionError):
            assert_no_secret_material(synthetic_key)
        with self.assertRaises(AssertionError):
            assert_no_secret_material("Bearer " + "A" * 32)


if __name__ == "__main__":
    unittest.main()
