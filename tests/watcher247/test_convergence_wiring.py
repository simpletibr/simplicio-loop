"""convergence_policy on the failed-verify path of host mode (#1509): its decision changes what the run does."""
from __future__ import annotations

from simplicio_loop import escalation
from simplicio_loop.watcher247 import config, host_mode
from simplicio_loop.watcher247.points import convergence_policy

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
    monkeypatch.setattr(convergence_policy, "assess",
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


def test_a_retry_decision_keeps_the_existing_role_order(env, cli_dir, monkeypatch):
    repeated = []
    real = host_mode.next_role
    monkeypatch.setattr(host_mode, "next_role", lambda ladder: repeated.append(1) or real(ladder))
    env(HostRun({REPO: [issue(1)]}, [BAD]))
    baseline()
    checkout()
    run_tick()
    assert repeated
