from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "docs" / "LLM_ORIENTATION.toon"
REQUIRED_SECTIONS = (
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
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
SECTION_PATTERN = re.compile(r"^\[([a-z][a-z0-9_]*)\]$")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_ -]?key|access[_ -]?token)\s*[:=]\s*[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:sk|ghp|github_pat|xoxb)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]+ KEY-----"),
)


def _parse_pack() -> tuple[str, dict[str, list[dict[str, str]]]]:
    text = PACK.read_text(encoding="utf-8")
    sections: dict[str, list[dict[str, str]]] = {}
    current: str | None = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        section_match = SECTION_PATTERN.fullmatch(stripped)
        if section_match:
            current = section_match.group(1)
            assert current not in sections, f"duplicate section at line {line_number}"
            sections[current] = []
            continue
        assert current is not None, f"record outside a section at line {line_number}"
        key, separator, value = stripped.partition("=")
        assert separator and KEY_PATTERN.fullmatch(key), f"invalid key at line {line_number}"
        first_value, *fields = value.split("|")
        record: dict[str, str] = {"_key": key, "_value": value, key: first_value}
        for field in fields:
            field_key, field_separator, field_value = field.partition("=")
            assert field_separator and KEY_PATTERN.fullmatch(field_key), f"invalid field at line {line_number}"
            assert field_key not in record, f"duplicate field at line {line_number}"
            record[field_key] = field_value
        sections[current].append(record)

    return text, sections


def _first(sections: dict[str, list[dict[str, str]]], section: str) -> dict[str, str]:
    assert sections[section]
    return sections[section][0]


def _has(sections: dict[str, list[dict[str, str]]], section: str, **expected: str) -> bool:
    return any(all(record.get(key) == value for key, value in expected.items()) for record in sections[section])


def _field(records: list[dict[str, str]], key: str) -> str:
    for record in records:
        if key in record:
            return record[key]
    pytest.fail(f"missing field: {key}")


def test_orientation_pack_is_deterministic_and_complete() -> None:
    text, sections = _parse_pack()

    assert tuple(sections) == REQUIRED_SECTIONS
    assert all(sections.values())
    assert _first(sections, "meta")["kind"] == "simplicio-dev-cli-llm-orientation"
    assert _first(sections, "meta")["purpose"] == "cache_only"
    assert _first(sections, "meta")["execution_contract"] == "not_a_contract"
    assert text.endswith("\n")
    assert all("\t" not in line for line in text.splitlines())
    assert "orientation/v2" not in text


def test_orientation_pack_binds_authoritative_paths_to_current_bytes() -> None:
    _, sections = _parse_pack()
    records = sections["source_of_truth"]

    assert len(records) >= 6
    for record in records:
        relative_path = record["path"]
        assert not Path(relative_path).is_absolute()
        source = ROOT / relative_path
        assert source.is_file(), relative_path
        assert record["authority"] == "canonical"
        assert record["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()

    project = sections["project"]
    assert _field(project, "name") == "simplicio-dev-cli"
    assert _field(project, "checkout_commit") == "6fe1e00b3fc4b30557cde21b3f8b3c601115b594"
    assert _field(project, "worker_branch") == "docs/llm-orientation-dev-cli-20260913"
    assert _field(project, "default_branch") == "main"


def test_orientation_pack_records_observed_commands_and_alias_rejections() -> None:
    _, sections = _parse_pack()

    assert _has(sections, "commands", command="simplicio-dev-cli --help", exit="0")
    assert _has(sections, "commands", command="simplicio-dev-cli task --help", exit="0")
    assert _has(sections, "commands", command="simplicio-dev-cli intake --help", exit="0")
    assert _has(sections, "commands", command="simplicio-dev-cli task <goal> --target <path> --dry-run-task --json")
    assert _has(sections, "commands", command="simplicio-dev-cli task <goal> --verify-only --json")
    assert _has(sections, "commands", command="simplicio-dev-cli verify-only --help", exit="2", status="unknown_command")
    assert _has(sections, "commands", command="simplicio-dev-cli dry-run --help", exit="2", status="unknown_command")
    assert _has(sections, "commands", command="simplicio-py", status="not_on_path")
    assert _has(sections, "commands", command="python3 -m simplicio.cli --help", exit="0")


def test_orientation_pack_rejects_secret_material_and_preserves_fail_closed_states() -> None:
    text, sections = _parse_pack()

    assert not any(pattern.search(text) for pattern in SECRET_PATTERNS)
    assert "status=blocked" in text
    assert "status=partial" in text
    assert "status=UNVERIFIED" in text
    assert _has(sections, "forbidden", rule="do_not_add_provider_credentials")
    assert _has(sections, "known_limits", code="artifact_missing", status="blocked")
