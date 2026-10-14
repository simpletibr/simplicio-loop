"""verify.py: the turbo argv and the pr/retry/dead decision. The command itself comes from loop.toml (test_verify_config.py)."""
from __future__ import annotations

import pytest

from simplicio_loop.watcher247 import verify

PYTEST = "python3 -m pytest -q"


# --- turbo argv ---

def test_argv_includes_verify_when_a_test_command_exists(tmp_path):
    argv = verify.turbo_argv(tmp_path, "do it", PYTEST)
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--verify") + 1] == PYTEST
    assert argv[argv.index("--task") + 1] == "do it"
    assert argv[argv.index("--provider") + 1] == "openrouter"


def test_argv_has_no_verify_without_a_test_command(tmp_path):
    assert "--verify" not in verify.turbo_argv(tmp_path, "do it", None)


# --- decision ---

OK = {"status": "ok"}


def ok_with(passed, tail=""):
    return {"status": "ok", "verify": {"passed": passed, "output_tail": tail}}


def test_verified_pass_opens_a_pr():
    decision = verify.decide(ok_with(True), PYTEST, 1, 3)
    assert decision.action == "pr"
    assert decision.label == f"MEASURED|verify_passed: `{PYTEST}`"


def test_no_test_command_opens_a_pr_marked_unverified():
    decision = verify.decide(OK, None, 1, 3)
    assert decision.action == "pr"
    assert decision.label == "UNVERIFIED|no_test_command"


@pytest.mark.parametrize("attempts,action", [(1, "retry"), (2, "retry"), (3, "dead")])
def test_verify_failure_never_opens_a_pr(attempts, action):
    decision = verify.decide(ok_with(False, "1 failed"), PYTEST, attempts, 3)
    assert decision.action == action
    assert "1 failed" in decision.reason
    assert decision.label != f"MEASURED|verify_passed: `{PYTEST}`"


def test_missing_verify_report_fails_closed():
    decision = verify.decide(OK, PYTEST, 1, 3)
    assert decision.action == "retry"
    assert "verify" in decision.reason


def test_turbo_failure_retries_with_its_detail():
    decision = verify.decide({"status": "failed", "detail": "boom"}, None, 1, 3)
    assert decision.action == "retry" and decision.reason == "boom"


def test_retry_or_dead_threshold():
    assert verify.retry_or_dead(2, 3) == "retry"
    assert verify.retry_or_dead(3, 3) == "dead"
