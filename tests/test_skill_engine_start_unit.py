"""Invoking the skill runs exactly two commands: the model plans in a heredoc, dev-cli applies. No provider, no key."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "simplicio-loop" / "SKILL.md"
FULL_FLOW = ROOT / ".claude" / "skills" / "simplicio-loop" / "references" / "full-flow.md"
BEGIN = "<!-- SIMPLICIO-LLM-ORIENTATION:BEGIN -->"
END = "<!-- SIMPLICIO-LLM-ORIENTATION:END -->"
TWO_COMMANDS = (
    'simplicio-loop "<task>"',
    'simplicio-loop turbo --repo <path> --task "<task>"',
    'simplicio-loop turbo --repo <path> --apply - --verify "<test command>" <<\'PLAN\'',
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
# What a model reads while it runs the skill. A provider flag or a plan file there sends it down a detour: the model
# used `--provider` on its own in the 3.45.1 benchmark, and wrote plan.json as a separate tool call.
MODEL_FACING = (
    ".claude/skills/simplicio-loop/SKILL.md",
    ".claude/skills/simplicio-loop/references/full-flow.md",
    "docs/LLM_MAX_SPEED_ORIENTATION.md",
    "docs/ECOSYSTEM_LLM_GUIDE.md",
    "llms.txt",
    "AGENTS.md",
    "packaging/host-rules/simplicio-loop-operator-flow.md",
    "adapters/opencode/README.md",
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _orientation_block(text: str) -> str:
    assert text.count(BEGIN) == 1 and text.count(END) == 1
    return text.split(BEGIN, 1)[1].split(END, 1)[0]


def _body_head(text: str) -> str:
    """The hot path: everything between the title and the first section."""
    return text.split("# /simplicio-loop\n", 1)[1].split("\n## ", 1)[0]


def test_skill_runs_exactly_two_commands_with_the_plan_on_stdin() -> None:
    head = _flat(_body_head(SKILL.read_text(encoding="utf-8")))
    missing = [needle for needle in (*TWO_COMMANDS, "exactly two commands", "needs_plan", "`apply` command",
                                     "There is no provider call and no API key.") if needle not in head]
    assert not missing, missing
    assert head.index('simplicio-loop "<task>"') < head.index("--apply -")  # the request first, then the apply


def test_skill_says_what_not_to_do() -> None:
    body = _flat(_body_head(SKILL.read_text(encoding="utf-8")))
    nothing_else = body.split("Nothing else.", 1)[1].split("Goal over a queue", 1)[0]
    for rule in ("Do not explore, list or read files", "Do not run tests yourself", "`--verify` does", "Never hand-edit",
                 "`--help`", "simplicio-mapper", "simplicio-dev-cli", "plan file", "scratchpad", "journal",
                 "turn header"):
        assert rule in nothing_else, rule


def test_skill_has_no_forbidden_old_flow_and_no_provider_or_key() -> None:
    text = SKILL.read_text(encoding="utf-8")
    left_over = [needle for needle in FORBIDDEN if needle in text]
    assert not left_over, left_over
    for gone in ("--provider", "OPENROUTER_API_KEY", "turbo_provider_key_missing", "headless"):
        assert gone not in text, gone


@pytest.mark.parametrize("rel", MODEL_FACING)
def test_model_facing_surfaces_name_no_provider_flag_key_or_plan_file(rel: str) -> None:
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "--provider" not in text, rel
    assert "OPENROUTER_API_KEY" not in text, rel
    assert not re.search(r"plan_path(?!_)", text) and "turbo/plan.json" not in text, rel


STATE_DIR_LINE = ("`.simplicio-loop/` is local run state: keep it in `.gitignore` (the engine adds it when the file "
                  "exists) and never commit it.")


def test_skill_and_orientation_say_the_state_directory_is_gitignored_and_never_committed() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert _flat(text.split(BEGIN, 1)[0]).count(STATE_DIR_LINE) == 1  # the body
    assert _flat(_orientation_block(text)).count(STATE_DIR_LINE) == 1  # and the block the stop hook re-feeds


def test_skill_description_says_invoking_it_runs_turbo() -> None:
    frontmatter = SKILL.read_text(encoding="utf-8").split("\n---\n", 1)[0]
    assert "Invoking it runs simplicio-loop turbo." in frontmatter
    assert "Host writes the edit plan." not in frontmatter
    assert "GitHub is SoT for issues/PRs." in frontmatter


def test_skill_orientation_block_is_the_two_command_contract() -> None:
    block = _flat(_orientation_block(SKILL.read_text(encoding="utf-8")))
    for needle in ('simplicio-loop "<task>"', 'simplicio-loop turbo --repo <path> --task "<task>"', "needs_plan",
                   "exactly two commands", "<<'PLAN'", "`apply` command", "Do not explore, list or read files",
                   "do not run tests yourself", "status ok", "verify", "End: DONE | NEXT | BLOCKED"):
        assert needle in block, needle
    for gone in ("OPENROUTER_API_KEY", "turbo_provider_key_missing", "--provider", "plan_path", "plan.json"):
        assert gone not in block, gone
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
    body = _flat(text.split(BEGIN, 1)[0])
    assert "name the files when the item names them" in body and "plus a passing verify" in body
    assert "then the printed `apply`" in body


def test_skill_short_form_is_documented_next_to_the_long_form() -> None:
    head = _flat(_body_head(SKILL.read_text(encoding="utf-8")))
    assert 'the short form of `simplicio-loop turbo --repo <path> --task "<task>"' in head
    assert head.index('simplicio-loop "<task>"') < head.index('simplicio-loop turbo --repo <path> --task "<task>"')


def test_skill_done_means_status_ok_and_verify_passed() -> None:
    text = SKILL.read_text(encoding="utf-8")
    done = text.split("\n## Done\n", 1)[1].split("\n## ", 1)[0]
    assert '`status: "ok"`' in done and "`verify.passed: true`" in done
    assert "<promise>" in done


def test_the_loop_machinery_is_for_queues_and_re_fed_goals_only() -> None:
    """The scratchpad, the journal and the turn header cost the 3.45.1 sessions 2-4 tool calls each on a one-file task."""
    text = SKILL.read_text(encoding="utf-8")
    assert "render --turn-header" in text  # the progress contract stays for armed loops
    loop = _flat(text.split("\n## Loop", 1)[1].split("\n## ", 1)[0])
    assert "Queue goals" in loop and "re-fed goals" in loop and "a task run needs none of it" in loop
    assert "skip it when the script is missing" in _flat(text.split("## Drive", 1)[1].split("\n## ", 1)[0])
    delivery = _flat(text.split("\n## Bounded delivery\n", 1)[1].split("\n## ", 1)[0])
    assert delivery.startswith("For queue goals:")  # a one-file task opens no issue and no PR
    assert "a task run never needs it" in _flat(text.split("\n## Guardrails\n", 1)[1].split("\n## ", 1)[0])


def test_skill_does_not_hand_the_host_a_mapper_scan() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "simplicio-mapper scan . --json" not in text
    assert "Do not install those as external projects." in _flat(text)


def test_full_flow_describes_the_compact_request_and_the_stdin_apply() -> None:
    text = _flat(FULL_FLOW.read_text(encoding="utf-8"))
    for needle in ("`tasks`, `map`, `files`, `format`, `rules` and `apply`", "--apply -", "<<'PLAN'",
                   "turbo_plan_missing", "turbo_plan_malformed", "exactly two commands"):
        assert needle in text, needle


def test_the_provider_engine_facts_live_with_the_benchmark_not_the_skill() -> None:
    text = _flat((ROOT / "bench" / "llm_ab" / "STANDARD.md").read_text(encoding="utf-8"))
    for needle in ("header and stays byte-identical", "sent back once", "call runs alone", "turbo_provider_key_missing",
                   "--provider openrouter", "headless automation only"):
        assert needle in text, needle
