"""Invoking the skill runs the turbo engine: the skill text names the one command and its key."""
from __future__ import annotations

from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"

BEGIN = "<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->"
END = "<!-- SIMPLICIO-LLM-ORIENTATION:END -->"

REQUIRED = (
    'simplicio-loop turbo --repo <path> --task "<task>"',
    "--verify",
    "OPENROUTER_API_KEY",
    "turbo_provider_key_missing",
    "Never fall back to hand edits.",
    "Do not hand-edit source. Run simplicio-loop turbo.",
)
# The host-writes-the-plan flow is gone: none of it may survive next to the turbo command.
FORBIDDEN = (
    "simplicio-loop prepare --task tasks.md",
    "edit-plan-<N>.json",
    "simplicio-loop tick <run_id>",
    "simplicio-loop wave <run_id>",
    "simplicio-dev-cli edit --plan",
    "The host LLM writes find/replace text",
    "Host writes the edit plan.",
    "Exactly one task uses `tick`",
)


def _orientation_block(text: str) -> str:
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


def test_skill_runs_the_turbo_command_and_needs_the_key() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, missing
    left_over = [needle for needle in FORBIDDEN if needle in text]
    assert not left_over, left_over


def test_skill_description_says_invoking_it_runs_turbo() -> None:
    frontmatter = SKILL.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "Invoking it runs simplicio-loop turbo." in frontmatter
    assert "Host writes the edit plan." not in frontmatter
    assert "GitHub is SoT for issues/PRs." in frontmatter


def test_skill_orientation_block_is_the_turbo_contract() -> None:
    block = _orientation_block(SKILL.read_text(encoding="utf-8"))
    for needle in ('simplicio-loop turbo --repo <path> --task "<task>"', "OPENROUTER_API_KEY",
                   "status ok", "verify", "End: DONE | NEXT | BLOCKED"):
        assert needle in block, needle
    for old in ("prepare", "tick", "wave", "edit-plan", "edit --plan"):
        assert old not in block, old


def test_skill_done_means_status_ok_and_verify_passed() -> None:
    text = SKILL.read_text(encoding="utf-8")
    done = text.split("\n## Done\n", 1)[1].split("\n## ", 1)[0]
    assert '`status: "ok"`' in done and "`verify.passed: true`" in done
    assert "<promise>" in done


def test_skill_does_not_hand_the_host_a_mapper_scan() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "simplicio-mapper scan . --json" not in text
    assert "Do not install those as external projects." in text


def test_skill_turbo_keeps_the_mapper_map_as_the_cached_header() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "header and stays byte-identical" in text
    assert "sent back once" in text
    assert "call runs alone" in text
