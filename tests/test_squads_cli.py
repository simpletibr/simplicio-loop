"""`simplicio-loop squads plan|gate` (#1502)."""

from __future__ import annotations

import io
import json
import subprocess

from simplicio_loop import cli_impl, squads

ISSUES = [
    {"number": 1, "title": "a", "area": "api"},
    {"number": 2, "title": "b", "area": "api", "body": "depends on #1"},
]


def _run(capsys, *argv):
    code = cli_impl.main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_plan_from_literal_json(capsys):
    code, out = _run(capsys, "squads", "plan", "--issues", json.dumps(ISSUES), "--json")
    assert code == 0
    assert out["schema"] == "simplicio.squad-plan/v1"
    assert out["general_coordinator"]["model"] == "claude-opus-5-5"
    assert [m["issue"] for m in out["merge_order"]] == [1, 2]


def test_plan_from_stdin_with_family_and_max_workers(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"issues": ISSUES})))
    code, out = _run(capsys, "squads", "plan", "--issues", "-", "--family", "codex", "--max-workers", "1", "--json")
    assert code == 0
    assert len(out["squads"]) == 2
    assert out["general_coordinator"]["model"] == "gpt-6-astra"


def test_plan_blocks_on_cycle_and_bad_input(capsys):
    cyclic = [{"number": 1, "body": "depends on #2"}, {"number": 2, "body": "depends on #1"}]
    code, out = _run(capsys, "squads", "plan", "--issues", json.dumps(cyclic), "--json")
    assert code == 2 and out["status"] == "BLOCKED" and out["error"] == "SquadCycleError"
    code, out = _run(capsys, "squads", "plan", "--issues", "not json", "--json")
    assert code == 2 and out["status"] == "BLOCKED"
    code, out = _run(capsys, "squads", "plan", "--issues", "[]", "--family", "nope", "--json")
    assert code == 2 and out["error"] == "ModelRoleError"


def _fake_gh(commit_date, approval_date):
    payload = {
        "commits": [{"oid": "a", "messageHeadline": "feat: x", "messageBody": "", "committedDate": commit_date}],
        "comments": [{"id": "c1", "body": "APROVADO PELO SQUAD", "createdAt": approval_date}],
    }
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload), "")

    return run, calls


def test_gate_approved_and_not_approved_exit_codes(capsys, monkeypatch):
    run, calls = _fake_gh("2026-10-09T01:00:00Z", "2026-10-09T02:00:00Z")
    monkeypatch.setattr(squads.subprocess, "run", run)
    code, out = _run(capsys, "squads", "gate", "--pr", "7", "--repo", "o/r", "--json")
    assert code == 0 and out["approved"] is True
    assert calls[0][:6] == ["gh", "pr", "view", "7", "--repo", "o/r"]

    run, _ = _fake_gh("2026-10-09T03:00:00Z", "2026-10-09T02:00:00Z")
    monkeypatch.setattr(squads.subprocess, "run", run)
    code, out = _run(capsys, "squads", "gate", "--pr", "7", "--repo", "o/r", "--json")
    assert code == 1 and out["approved"] is False


def test_gate_gh_failure_is_blocked(capsys, monkeypatch):
    monkeypatch.setattr(
        squads.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no such pr")
    )
    code, out = _run(capsys, "squads", "gate", "--pr", "7", "--json")
    assert code == 2 and out["status"] == "BLOCKED" and "no such pr" in out["reason"]
