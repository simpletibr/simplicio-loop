"""Contract tests for the human-authored, line-oriented LLM orientation cache."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest


REPO = Path(__file__).parents[1]
PACK = REPO / "docs" / "LLM_ORIENTATION.toon"
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
RECORD = re.compile(r"^(?P<kind>[a-z][a-z0-9_-]*) (?P<key>[a-z][a-z0-9_.-]*)=(?P<value>\S.*)$")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|authorization|bearer)\s*[:=]\s*"
    r"(?!none\b|absent\b|unavailable\b|redacted\b)\S+"
)
FORBIDDEN_FLAGS = tuple("--" + name for name in ("serial", "max-workers", "retry-budget", "fan-out"))


def parse_pack(text: str) -> dict[str, dict[str, str]]:
    """Parse the deliberately small TOON-like grammar used by the orientation cache."""
    if not text or not text.endswith("\n"):
        raise ValueError("pack must be non-empty and end with a newline")
    if SECRET_ASSIGNMENT.search(text):
        raise ValueError("secret-looking assignment in orientation pack")

    parsed: dict[str, dict[str, str]] = {}
    section: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line or line != line.rstrip():
            raise ValueError(f"invalid blank/trailing-whitespace line {line_number}")
        if line.startswith("section "):
            section = line.removeprefix("section ")
            if section not in SECTIONS or section in parsed:
                raise ValueError(f"invalid or duplicate section at line {line_number}: {section}")
            parsed[section] = {}
            continue
        if section is None:
            raise ValueError(f"record before section at line {line_number}")
        match = RECORD.fullmatch(line)
        if not match:
            raise ValueError(f"invalid record at line {line_number}")
        key = match.group("key")
        if key in parsed[section]:
            raise ValueError(f"duplicate key at line {line_number}: {key}")
        parsed[section][key] = match.group("value")

    if tuple(parsed) != SECTIONS:
        raise ValueError(f"sections must be ordered exactly as {SECTIONS}")
    return parsed


def _values(records: dict[str, str], prefix: str) -> set[str]:
    return {value for key, value in records.items() if key.startswith(prefix)}


def test_pack_is_parseable_and_has_the_frozen_section_order():
    parsed = parse_pack(PACK.read_text(encoding="utf-8"))
    assert tuple(parsed) == SECTIONS
    assert parsed["meta"]["format"] == "toon-like-line-v1"
    assert parsed["meta"]["authority"] == "orientation-cache-only"


def test_pack_has_project_identity_and_authoritative_sources_with_sha256():
    parsed = parse_pack(PACK.read_text(encoding="utf-8"))
    project = parsed["project"]
    assert project["name"] == "simplicio-loop"
    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"])
    assert re.fullmatch(r"[0-9a-f]{40}", project["baseline_commit"])
    assert project["default_branch"] == "main"
    assert project["branch"] == "docs/llm-orientation-loop-20260913"

    required_paths = {
        "AGENTS.md",
        "docs/LLM_OPERATING_INSTRUCTIONS.md",
        "docs/LLM_MAX_SPEED_ORIENTATION.md",
        ".claude/skills/simplicio-loop/SKILL.md",
        ".claude/skills/simplicio-prism/SKILL.md",
        "contracts/loop-execution/v1/schema.json",
        "contracts/loop-execution/v1/receipt.schema.json",
        "contracts/loop-execution/v1/SCHEMA.md",
    }
    source_paths = {
        value for key, value in parsed["source_of_truth"].items() if key.endswith(".path")
    }
    assert required_paths <= source_paths
    for path in required_paths:
        source_key = next(key for key, value in parsed["source_of_truth"].items() if value == path)
        digest_key = source_key.removesuffix(".path") + ".sha256"
        expected = hashlib.sha256((REPO / path).read_bytes()).hexdigest()
        assert parsed["source_of_truth"][digest_key] == expected


def test_pack_lists_relevant_skills_and_real_observed_commands():
    parsed = parse_pack(PACK.read_text(encoding="utf-8"))
    skill_paths = {
        value for key, value in parsed["skills"].items() if key.endswith(".path")
    }
    required_skills = {
        ".claude/skills/simplicio-loop/SKILL.md",
        ".claude/skills/simplicio-prism/SKILL.md",
        ".claude/skills/simplicio-mapper/SKILL.md",
        ".claude/skills/simplicio-dev-cli/SKILL.md",
        ".claude/skills/simplicio-orient/SKILL.md",
    }
    assert required_skills <= skill_paths
    for path in required_skills:
        skill_key = next(key for key, value in parsed["skills"].items() if value == path)
        digest_key = skill_key.removesuffix(".path") + ".sha256"
        expected = hashlib.sha256((REPO / path).read_bytes()).hexdigest()
        assert parsed["skills"][digest_key] == expected

    observed_commands = _values(parsed["commands"], "observed.")
    assert parsed["commands"]["entrypoints"] == (
        "simplicio-loop; simplicio-mapper; simplicio-dev-cli"
    )
    assert {
        "simplicio-loop --help",
        "simplicio-loop orient --help",
        "simplicio-loop preflight --help",
        "simplicio-loop map --help",
        "simplicio-loop decide --help",
        "simplicio-loop economy apply --help",
        "simplicio-loop verify --help",
        "simplicio-mapper --help",
        "simplicio-dev-cli --help",
    } <= observed_commands


def test_pack_preserves_v1_contract_authority_and_receipt_semantics():
    parsed = parse_pack(PACK.read_text(encoding="utf-8"))
    contracts = parsed["contracts"]
    assert "simplicio.loop-execution/v1" in contracts.values()
    assert "contracts/loop-execution/v1/schema.json" in contracts.values()
    assert "contracts/loop-execution/v1/receipt.schema.json" in contracts.values()
    assert any("simplicio-loop" in value for key, value in contracts.items() if key.endswith(".owner"))
    forbidden_contract = "simplicio.loop-execution/" + "v2"
    assert not any(forbidden_contract in value for value in contracts.values())

    receipts = parsed["receipts"]
    assert receipts["schema"] == "simplicio.loop-execution/v1"
    assert receipts["source"] == "contracts/loop-execution/v1/receipt.schema.json"
    assert receipts["completion"] == "watcher+delivery+quality-matrix+completion-oracle"
    assert receipts["unknown_effect"] == "preserve-lock-and-reconcile"
    assert receipts["fallback"] == "fail-closed; no fabricated receipt"


def test_pack_covers_tdd_validation_handoff_governors_and_limits():
    parsed = parse_pack(PACK.read_text(encoding="utf-8"))
    assert parsed["governors"]["truth"] == "MEASURED|receipt-backed; otherwise UNVERIFIED|"
    assert parsed["governors"]["writes"] == "serialized; physical capacity governed"
    assert parsed["governors"]["prohibitions"] == "no provider, API key, token, secret, or unobserved command"

    tests = parsed["tests"]
    assert tests["red"] == "write focused tests first; run pytest and require RED"
    assert tests["green"] == "implement pack; run focused pytest and require GREEN"
    assert "tests/test_llm_orientation_pack.py" in tests["focused"]
    assert "python3 scripts/check.py" in tests["public_gate"]
    assert "python3 scripts/check_loop_contract.py" in tests["contract_gate"]

    assert parsed["workflow"]["sequence"] == "map -> memory -> skills -> gate/checkpoint -> TDD -> validate -> evidence"
    for component in ("mapper", "dev_cli", "runtime"):
        assert component in parsed["handoff"]
    assert parsed["known_limits"]["mcp_architecture_map"] == "BLOCKED|MAP_OPERATION_DECLARED_ONLY"


def test_pack_parser_rejects_secret_looking_assignments():
    key_name = "api" + "_key"
    unsafe = "section meta\nfact format=toon-like-line-v1\nfact credential=" + key_name + "=live-value\n"
    with pytest.raises(ValueError, match="secret"):
        parse_pack(unsafe)


def test_pack_contains_no_prohibited_parallelism_flags_or_secret_values():
    text = PACK.read_text(encoding="utf-8")
    assert not any(flag in text for flag in FORBIDDEN_FLAGS)
    credential_prefixes = (
        "s" + "k-",
        "p" + "k-",
        "gh" + "p-",
        "github" + "_pat",
        "xo" + "x",
    )
    assert not any(prefix in text.lower() for prefix in credential_prefixes)
