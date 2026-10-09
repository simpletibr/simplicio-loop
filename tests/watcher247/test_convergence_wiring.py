"""convergence_policy on the failed-verify path of host mode (#1509): its decision changes what the run does."""
from __future__ import annotations

import subprocess
import sys

from simplicio_loop import escalation
from simplicio_loop.watcher247 import config, convergence, host_mode

from .fakes import baseline, issue, read_json, run_tick
from .test_host_mode import BAD, REPO, HostRun, checkout, cli_dir, planner_calls  # noqa: F401  (cli_dir is a fixture)


def test_a_stop_decision_ends_the_escalation_before_the_step_limit(env, cli_dir, monkeypatch):
    """With measured tokens the ladder alone would run all MAX_STEPS; the failed-attempt ceiling stops it at 2."""
    monkeypatch.setenv("SIMPLICIO_247_ATTEMPT_CEILING_ISSUE", "2")
    monkeypatch.setattr(escalation, "measured_tokens", lambda report: 10)
    fake = env(HostRun({REPO: [issue(1)]}, [BAD]))
    baseline()
    checkout()
    run_tick()
    assert len(planner_calls(cli_dir)) == 2 and len(fake.turbo_argv) == 2
    claim = read_json(config.CLAIMS)[f"{REPO}#1"]
    assert claim["status"] == "retry"  # a stop is a failed attempt: dead only through the attempt limit
    assert "convergence stop (budget_exhausted)" in claim["error"]
    assert fake.ran("gh", "pr", "create") == []


def test_an_escalate_decision_climbs_the_ladder_instead_of_repeating(env, cli_dir, monkeypatch):
    monkeypatch.setattr(convergence, "assess",
                        lambda ladder, **kw: {"action": "escalate", "reason": "oscillation_detected"})
    climbed = []
    real_next_step = escalation.EscalationState.next_step
    monkeypatch.setattr(escalation.EscalationState, "next_step",
                        lambda self: climbed.append(self.current_role()) or real_next_step(self))
    repeated = []
    monkeypatch.setattr(host_mode, "next_role", lambda ladder: repeated.append(1))
    env(HostRun({REPO: [issue(1)]}, [BAD]))
    baseline()
    checkout()
    run_tick()
    assert climbed and not repeated


def test_a_failing_point_import_does_not_break_host_mode():
    """host_mode never imports `points`: a point that fails to import cannot take the tick down."""
    script = ("import sys; sys.modules['simplicio_loop.watcher247.points'] = None; "
              "import simplicio_loop.watcher247.host_mode as h; "
              "assert h.convergence.assess and h.choose")
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_a_retry_decision_keeps_the_existing_role_order(env, cli_dir, monkeypatch):
    repeated = []
    real = host_mode.next_role
    monkeypatch.setattr(host_mode, "next_role", lambda ladder: repeated.append(1) or real(ladder))
    env(HostRun({REPO: [issue(1)]}, [BAD]))
    baseline()
    checkout()
    run_tick()
    assert repeated
