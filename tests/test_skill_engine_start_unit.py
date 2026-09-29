"""Invoking the skill runs the turbo engine in host mode: no provider, no key; the model plans, dev-cli applies."""
from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
FULL_FLOW = ROOT / ".claude" / "skills" / "simplicio-loop" / "references" / "full-flow.md"
BEGIN = "<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->"
END = "<!-- SIMPLICIO-LLM-ORIENTATION:END -->"
REQUIRED = (
    'simplicio-loop "<task>"',
    'simplicio-loop turbo --repo <path> --task "<task>"',
    "--verify",
    "needs_plan",
    "plan_path",
    "`apply` command",
    "Never edit files by hand",
    "There is no\nprovider call and no API key.",
    "Do not hand-edit source: write the plan, `simplicio-loop turbo --apply` lets dev-cli edit.",
)
# The old host-writes-the-plan flow (prepare/tick/wave, edit-plan files) is gone, and so is the key rule.
FORBIDDEN = (
    "simplicio-loop prepare --task tasks.md",
    "edit-plan-<N>.json",
    "simplicio-loop tick <run_id>",
    "simplicio-loop wave <run_id>",
    "simplicio-dev-cli edit --plan",
    "The host LLM writes find/replace text",
    "Host writes the edit plan.",
    "Exactly one task uses `tick`",
    "Never fall back to hand edits.",
    "It needs `OPENROUTER_API_KEY`",
)


def _orientation_block(text: str) -> str:
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


def test_skill_runs_the_host_mode_commands_without_a_key_requirement() -> None:
    text = SKILL.read_text(encoding="utf-8")
    missing = [needle for needle in REQUIRED if needle not in text]
    assert not missing, missing
    left_over = [needle for needle in FORBIDDEN if needle in text]
    assert not left_over, left_over
    # The key is named once, only as the explicit headless opt-in.
    assert text.count("OPENROUTER_API_KEY") == 1
    assert "--provider openrouter" in text and "Only when the user asks for headless mode" in text


def test_skill_description_says_invoking_it_runs_turbo() -> None:
    frontmatter = SKILL.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "Invoking it runs simplicio-loop turbo." in frontmatter
    assert "Host writes the edit plan." not in frontmatter
    assert "GitHub is SoT for issues/PRs." in frontmatter


def test_skill_orientation_block_is_the_host_mode_contract() -> None:
    block = _orientation_block(SKILL.read_text(encoding="utf-8"))
    for needle in ('simplicio-loop "<task>"', 'simplicio-loop turbo --repo <path> --task "<task>"', "needs_plan",
                   "plan_path", "printed `apply` command", "status ok", "verify", "End: DONE | NEXT | BLOCKED"):
        assert needle in block, needle
    assert "OPENROUTER_API_KEY" not in block and "turbo_provider_key_missing" not in block
    for old in ("prepare", "tick ", "wave", "edit-plan", "edit --plan"):
        assert old not in block, old


def test_skill_says_how_to_drain_a_queue_with_two_commands_per_item() -> None:
    text = SKILL.read_text(encoding="utf-8")
    block = _orientation_block(text)
    queue = 'gh issue list --state open --json number,title,body'
    per_item = 'simplicio-loop turbo --repo <path> --task "<title>: <body>" --verify "<tests>"'
    for surface in (text, block):
        assert queue in surface and per_item in surface
        assert "one CLAIMED issue" in surface and "one PR" in surface
    assert "in order" in block and "the printed `apply`" in block
    body = text.split(BEGIN, 1)[0]
    assert "name the\n  files when the item names them" in body and 'plus a passing verify' in body


def test_skill_short_form_is_documented_next_to_the_long_form() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert 'It is the short form of\n   `simplicio-loop turbo --repo <path> --task "<task>"' in text
    assert text.index('simplicio-loop "<task>"') < text.index('simplicio-loop turbo --repo <path> --task "<task>"')


def test_skill_done_means_status_ok_and_verify_passed() -> None:
    text = SKILL.read_text(encoding="utf-8")
    done = text.split("\n## Done\n", 1)[1].split("\n## ", 1)[0]
    assert '`status: "ok"`' in done and "`verify.passed: true`" in done
    assert "<promise>" in done


def test_skill_does_not_hand_the_host_a_mapper_scan() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "simplicio-mapper scan . --json" not in text
    assert "Do not install those as external projects." in text


def test_full_flow_keeps_the_provider_mode_facts() -> None:
    text = FULL_FLOW.read_text(encoding="utf-8")
    for needle in ("header and stays byte-identical", "sent back once", "call runs alone",
                   "turbo_provider_key_missing", "--provider openrouter", "turbo_plan_malformed"):
        assert needle in text, needle
