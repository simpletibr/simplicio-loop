"""Issue #1353: invoking the skill starts the monorepo engine."""
from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"

REQUIRED = (
    "simplicio-loop orient --brief",
    "simplicio-loop apply",
    "simplicio-loop wave",
    "simplicio-loop verify",
    "--repo <path>",
    "tee cache",
)


def test_skill_engine_start_commands_present() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, missing


def test_skill_does_not_hand_the_host_a_mapper_scan() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "simplicio-mapper scan . --json" not in text
