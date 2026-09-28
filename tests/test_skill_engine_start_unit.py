"""Issue #1353: invoking the skill starts the pre-monorepo flow inside this repo."""
from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"

REQUIRED = (
    "simplicio-loop orient --repo <path> --task",
    "simplicio-loop prepare --task tasks.md --repo <path>",
    "simplicio-loop wave <run_id> --repo <path>",
    "simplicio-loop tick <run_id> --repo <path> --task-index 1",
    "simplicio-loop verify <run_id> --repo <path>",
    "exactly one task",
    "more than one task",
)


def test_skill_defines_one_task_and_many_task_flows() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, missing


def test_skill_does_not_hand_the_host_a_mapper_scan() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "simplicio-mapper scan . --json" not in text
    assert "Do not install those as external projects." in text


def test_skill_turbo_keeps_the_mapper_map_as_the_cached_header() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "header and stays byte-identical" in text
    assert "sent back once" in text
    assert "call runs alone" in text
