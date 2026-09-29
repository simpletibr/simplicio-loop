"""The plan a host pipes into `simplicio-loop turbo --apply -` is data for dev-cli that no shell executes.

The fail-closed gate reads the whole Bash command, so a plan that merely contains `DROP TABLE` (a migration, a
runbook) would be blocked for what it says. The gate drops that one heredoc body before it classifies, and the
exemption never lets a command through: it needs the canonical shape (a first line that is one plain
`simplicio-loop turbo` command ending in a quoted heredoc introducer, a body, the terminator as the last line)
and a body without the terminator.
"""
from __future__ import annotations

import json

import pytest

import action_gate as ag

HEAD = "simplicio-loop turbo --repo /r --apply -"


def _plan(text: str) -> str:
    return json.dumps({"operations": [{"path": "docs/ops.md", "find": "", "replace": text}]})


def _command(body: str, head: str = HEAD, tag: str = "PLAN") -> str:
    return f"{head} <<'{tag}'\n{body}\n{tag}"


@pytest.fixture(autouse=True)
def no_runtime_escalation(monkeypatch):
    monkeypatch.setattr(ag, "_runtime_gate_escalation", lambda cmd: None)  # a `simplicio` binary may be installed


BLOCKED_IF_SHELL = [
    "DROP TABLE users;",
    "TRUNCATE TABLE audit_log",
    "git push --force origin main",
    "git filter-branch --tree-filter x HEAD",
    "rm -rf / ",
    "terraform destroy -auto-approve",
    "kubectl delete namespace prod",
]


@pytest.mark.parametrize("text", BLOCKED_IF_SHELL)
def test_a_plan_that_says_something_destructive_is_allowed_but_the_same_text_as_a_command_is_not(text):
    assert ag.gate_command(_command(_plan(text)))["action"] == "allow"
    assert ag.gate_command(f"cat <<'PLAN'\n{_plan(text)}\nPLAN")["action"] == "block"  # any other reader keeps the gate


def test_a_verify_with_shell_operators_inside_quotes_keeps_the_exemption():
    command = _command(_plan("DROP TABLE users;"), head=HEAD + " --verify 'pytest -q && echo ok; echo | cat'")
    assert ag.gate_command(command)["action"] == "allow"


def test_a_plan_that_mentions_git_commit_does_not_start_the_staged_diff_scan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a git repository: a real `git commit` here is refused, fail-closed
    assert ag.gate_command("git commit -m x")["action"] == "block"
    assert ag.gate_command(_command(_plan("run git commit, then git push")))["action"] == "allow"


NOT_EXEMPT = [
    # bash ends the heredoc at the FIRST `PLAN` line and runs what follows
    "simplicio-loop turbo --repo /r --apply - <<'PLAN'\n{}\nPLAN\nrm -rf /\nPLAN",
    "simplicio-loop turbo --repo /r --apply - <<'PLAN'\n{}\nPLAN\nDROP TABLE x\nPLAN",
    # a chained or piped first line: another command may read the heredoc
    "simplicio-loop turbo --repo /r --apply - ; rm -rf / <<'PLAN'\n{}\nPLAN",
    "simplicio-loop turbo --repo /r --apply - && rm -rf / <<'PLAN'\n{}\nPLAN",
    "simplicio-loop turbo --repo /r --apply - | sh <<'PLAN'\nrm -rf /\nPLAN",
    "simplicio-loop turbo --repo /r --apply - <<'EOF' <<'PLAN'\nrm -rf /\nPLAN",
    # another program reads the heredoc
    "sh <<'PLAN'\nrm -rf /\nPLAN",
    "bash - <<'PLAN'\nDROP TABLE x\nPLAN",
    "simplicio-loop-tool turbo --repo /r --apply - <<'PLAN'\nrm -rf /\nPLAN",
    "cd /r && simplicio-loop turbo --apply - <<'PLAN'\nDROP TABLE x\nPLAN",
    # an unquoted delimiter lets the shell expand `$(...)` in the body
    "simplicio-loop turbo --repo /r --apply - <<PLAN\n$(rm -rf / )\nPLAN",
    'simplicio-loop turbo --repo /r --apply - <<"PLAN"\n$(rm -rf / )\nPLAN',
    # a body that does not close with the delimiter
    "simplicio-loop turbo --repo /r --apply - <<'PLAN'\nrm -rf / \nPLAN ",
    "simplicio-loop turbo --repo /r --apply - <<'PLAN'\nrm -rf / \nEOF",
]


@pytest.mark.parametrize("command", NOT_EXEMPT)
def test_the_exemption_never_hides_a_command(command):
    assert ag.strip_plan_heredoc(command) == command
    assert ag.gate_command(command)["action"] == "block"


def test_the_helper_keeps_only_the_first_line_of_the_canonical_form():
    command = _command(_plan("DROP TABLE users;"), head=HEAD + " --verify 'pytest -q'")
    assert ag.strip_plan_heredoc(command) == HEAD + " --verify 'pytest -q' <<'PLAN'"
    assert ag.strip_plan_heredoc(command + "\n") == HEAD + " --verify 'pytest -q' <<'PLAN'"
    assert ag.strip_plan_heredoc("git status") == "git status" and ag.strip_plan_heredoc("") == ""
