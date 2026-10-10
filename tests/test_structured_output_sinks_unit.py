"""#1612 PR C: the sinks hold a model answer to the closed plan contract and to the task scope.

Provider mode (`turbo._parse_operations` / `_apply_operations` through `run_turbo`), host mode
(`turbo_cli._apply_plan_async`, `_plan_failures`) and the CLI planners (`exec_planner._extract_plan_json`) refuse an
answer outside the scope with a deterministic reason; the first refusal is a retry (`retry_scheduled`), the second is
`needs_human`. Output tokens per task are reported MEASURED only from provider usage.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from simplicio_loop import dashboard_events, exec_planner, plan_scope, structured_output, turbo, turbo_cli, turbo_provider

GOOD = {"operations": [{"path": "hello.txt", "find": "", "replace": "hi\n"}]}
OUT = {"operations": [{"path": "evil.py", "find": "", "replace": "x\n"}]}
RECEIPT = {"schema": "simplicio.dev-cli.edit-receipt/v1", "applied": True, "receipt_digest": "deadbeef"}


def _scope(*paths: str) -> plan_scope.TaskScope:
    return plan_scope.TaskScope(paths=frozenset(paths))


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=root, check=True)
    (root / "hello.txt").write_text("", encoding="utf-8")
    state = root / ".simplicio-loop"
    state.mkdir()
    (state / "project-map.json").write_text(
        json.dumps({"schema": "simplicio.project-map/v1", "files": [{"path": "hello.txt", "symbols": []}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    return root


def _stub_dev_cli(tmp_path: Path) -> str:
    path = tmp_path / "stub-dev-cli"
    path.write_text(f"#!/bin/sh\ncase \"$*\" in *--apply*)\n  printf '%s\\n' '{json.dumps(RECEIPT)}' ;;\nesac\nexit 0\n",
                    encoding="utf-8")
    path.chmod(0o755)
    return str(path)


def _doc(capsys) -> dict:
    return json.loads([line for line in capsys.readouterr().out.splitlines() if line.startswith("{")][-1])


def _events(repo: Path, run_id: str) -> list[dict]:
    return dashboard_events.read_events(repo / ".simplicio-loop" / "orchestrator" / "runs" / run_id)


def _provider(repo, tmp_path, monkeypatch, capsys, answers: list[str]):
    """`turbo --provider openrouter` with a model that answers `answers` in order (usage reported: 4 output tokens)."""
    monkeypatch.setattr(turbo, "_dev_cli_bin", lambda: _stub_dev_cli(tmp_path))
    monkeypatch.setattr(turbo_provider, "require_key", lambda api_key=None: "sk-test")
    asked: list[list[dict]] = []

    async def fake_complete(arm, messages, *, session_id, **kwargs):
        asked.append(messages)
        return {"ok": True, "content": answers[min(len(asked), len(answers)) - 1], "hedged": False, "latency_s": 0.01,
                "provider": "test", "session_id": session_id, "cost": None, "usage_reported": True,
                "prompt_tokens": 10, "completion_tokens": 4, "cached_tokens": 0, "reasoning_tokens": 0}

    monkeypatch.setattr(turbo_provider, "complete", fake_complete)
    rc = turbo_cli.run(str(repo), ["write hello.txt"], provider="openrouter")
    return rc, _doc(capsys), asked


# --- provider mode: _parse_operations / _apply_operations ------------------------------------------------------

def test_parse_operations_without_scope_stays_tolerant():
    assert turbo._parse_operations("here: " + json.dumps(OUT))[0]["path"] == "evil.py"


def test_parse_operations_with_scope_refuses_a_file_outside_it(tmp_path):
    with pytest.raises(turbo.PlanRejected) as raised:
        turbo._parse_operations(json.dumps(OUT), _scope("hello.txt"), tmp_path)
    assert raised.value.violations == ["out_of_scope:evil.py"]


def test_parse_operations_with_scope_refuses_prose_and_extra_field(tmp_path):
    with pytest.raises(turbo.PlanRejected) as prose:
        turbo._parse_operations("Sure! " + json.dumps(GOOD), _scope("hello.txt"), tmp_path)
    assert [v.split(":", 1)[0] for v in prose.value.violations] == ["extra_prose"]
    extra = {"operations": GOOD["operations"], "why": "because"}
    with pytest.raises(turbo.PlanRejected) as field:
        turbo._parse_operations(json.dumps(extra), _scope("hello.txt"), tmp_path)
    assert field.value.violations == ["extra_field:/why"]


def test_parse_operations_with_scope_returns_the_operations(tmp_path):
    assert turbo._parse_operations(json.dumps(GOOD), _scope("hello.txt"), tmp_path) == GOOD["operations"]


def test_apply_operations_refuses_before_dev_cli_runs(tmp_path):
    commands = asyncio.run(turbo._apply_operations(
        tmp_path, OUT["operations"], "/nonexistent/dev-cli", "t", asyncio.Lock(), _scope("hello.txt")))
    assert len(commands) == 1 and commands[0]["command"] == "plan_scope" and commands[0]["returncode"] == 1
    assert commands[0]["violations"] == ["out_of_scope:evil.py"]


def test_provider_run_retries_once_then_applies_and_reports_it(repo, tmp_path, monkeypatch, capsys):
    rc, doc, asked = _provider(repo, tmp_path, monkeypatch, capsys, [json.dumps(OUT), json.dumps(GOOD)])

    assert rc == 0 and doc["status"] == "ok" and len(asked) == 2
    assert "out_of_scope:evil.py" in asked[1][-1]["content"]  # the planner gets the violations, nothing else
    retries = [e for e in _events(repo, doc["run_id"]) if e["kind"] == "retry_scheduled"]
    assert len(retries) == 1
    assert retries[0]["payload"]["reason"] == "out_of_scope" and "evil.py" in retries[0]["payload"]["blocker"]
    metrics = doc["structured_metrics"]
    assert metrics["rejected"] == {"out_of_scope": 1, "extra_field": 0, "extra_prose": 0, "other": 0}
    assert metrics["output_tokens_by_task"] == [{"tasks": [1], "calls": 2, "basis": "MEASURED", "output_tokens": 8}]


def test_provider_run_ends_needs_human_after_the_second_refusal(repo, tmp_path, monkeypatch, capsys):
    rc, doc, asked = _provider(repo, tmp_path, monkeypatch, capsys, [json.dumps(OUT)])

    assert rc == 1 and doc["status"] == "failed" and len(asked) == 2  # one new attempt, not more
    (failed,) = doc["failed"]
    assert failed["needs_human"] is True and failed["reason"] == "needs_human: out_of_scope:evil.py"
    events = _events(repo, doc["run_id"])
    assert [e["kind"] for e in events if e["kind"] in ("retry_scheduled", "decision_requested")] == [
        "retry_scheduled", "decision_requested"]
    assert doc["structured_metrics"]["rejected"]["out_of_scope"] == 2
    assert not (repo / "evil.py").exists()


# --- host mode: the plan applied against the request's scope -----------------------------------------------------

def _request(repo, capsys) -> str:
    assert turbo_cli.run(str(repo), ["write hello.txt"]) == 0
    return _doc(capsys)["run_id"]


def _apply(repo, tmp_path, run_id: str, plan: dict, capsys) -> tuple[int, dict]:
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan), encoding="utf-8")
    rc = turbo_cli.run(str(repo), [], apply=str(plan_file), run_id=run_id)
    return rc, _doc(capsys)


def test_host_apply_refuses_a_file_outside_the_scope_then_needs_human(repo, tmp_path, capsys):
    run_id = _request(repo, capsys)

    rc, first = _apply(repo, tmp_path, run_id, OUT, capsys)
    assert rc == 1 and first["status"] == "failed" and first["reason_code"] == "turbo_plan_refused"
    assert first["next_action"] == "retry" and first["failed"] == [
        {"path": "evil.py", "reason": "out_of_scope:evil.py", "excerpt": ""}]
    assert first["rejected"]["out_of_scope"] == 1 and "out_of_scope:evil.py" in first["detail"]
    assert [e["kind"] for e in _events(repo, run_id) if e["kind"] == "retry_scheduled"] == ["retry_scheduled"]

    rc, second = _apply(repo, tmp_path, run_id, OUT, capsys)
    assert rc == 1 and second["reason_code"] == "needs_human" and second["next_action"] == "needs_human"
    assert second["cause"] == ["out_of_scope:evil.py"]
    assert any(e["kind"] == "decision_requested" for e in _events(repo, run_id))
    assert not (repo / "evil.py").exists()


def test_host_apply_refuses_prose_around_the_plan(repo, tmp_path, capsys):
    run_id = _request(repo, capsys)
    plan_file = tmp_path / "plan.json"
    plan_file.write_text("Here is the plan:\n" + json.dumps(GOOD), encoding="utf-8")

    rc = turbo_cli.run(str(repo), [], apply=str(plan_file), run_id=run_id)
    doc = _doc(capsys)

    assert rc == 1 and doc["rejected"]["extra_prose"] == 1
    assert doc["failed"][0]["reason"].startswith("extra_prose:")


def test_plan_failures_lists_one_entry_per_violation(tmp_path):
    failures = turbo_cli._plan_failures(
        tmp_path, [], "plan_refused", ["out_of_scope:a.py", "lines_over_limit:b.py:9001", "extra_field:/why"])
    assert failures == [
        {"path": "a.py", "reason": "out_of_scope:a.py", "excerpt": ""},
        {"path": "b.py", "reason": "lines_over_limit:b.py:9001", "excerpt": ""},
        {"path": None, "reason": "extra_field:/why", "excerpt": ""},
    ]


def test_a_task_that_names_no_file_has_an_unbounded_scope(tmp_path):
    scope = turbo_cli.task_scope(tmp_path, turbo_cli.build_tasks(tmp_path, ["make it faster"]))
    assert scope.unbounded and scope.contains("anything.py")
    named = turbo_cli.task_scope(tmp_path, turbo_cli.build_tasks(tmp_path, ["create a.py\n- [ ] it works"]))
    assert not named.unbounded and named.paths == {"a.py"} and named.criteria == ("it works",)


# --- CLI planners: _extract_plan_json --------------------------------------------------------------------------

NEED = {"operations": [], "need": [{"path": "big.py", "start": 10, "end": 20}]}


def test_extract_plan_json_with_scope_accepts_a_need_only_plan(tmp_path):
    assert exec_planner._extract_plan_json(json.dumps(NEED), _scope("big.py"), tmp_path) == NEED


def test_extract_plan_json_with_scope_refuses_a_file_outside_it_and_prose(tmp_path):
    with pytest.raises(ValueError, match="out_of_scope:evil.py"):
        exec_planner._extract_plan_json(json.dumps(OUT), _scope("hello.txt"), tmp_path)
    with pytest.raises(ValueError, match="extra_prose"):
        exec_planner._extract_plan_json("pre " + json.dumps(GOOD), _scope("hello.txt"), tmp_path)


def test_extract_plan_json_judges_the_object_of_a_schema_flag_envelope(tmp_path):
    envelope = {"type": "result", "result": "done", "structured_output": GOOD}
    assert exec_planner._extract_plan_json(json.dumps(envelope), _scope("hello.txt"), tmp_path) == GOOD
    with pytest.raises(ValueError, match="out_of_scope"):
        exec_planner._extract_plan_json(json.dumps({"structured_output": OUT}), _scope("hello.txt"), tmp_path)


def test_run_planner_reports_bad_plan_with_the_violations(tmp_path, monkeypatch):
    async def fake_run(argv, **kwargs):
        return json.dumps(OUT), "", 0

    monkeypatch.setattr(exec_planner, "_find_cli", lambda name: "/bin/claude")
    monkeypatch.setattr(exec_planner, "_run_subprocess", fake_run)
    result = asyncio.run(exec_planner.run_planner("claude", "planning", "x", cwd=str(tmp_path), scope=_scope("hello.txt")))
    assert result.reason_code == "bad_plan" and "out_of_scope:evil.py" in result.error


# --- metrics ------------------------------------------------------------------------------------------------------

def test_output_tokens_are_measured_only_when_the_provider_reported_usage():
    calls = [
        {"tasks": [1], "ok": True, "usage_reported": True, "completion_tokens": 7},
        {"tasks": [2], "ok": True, "usage_reported": False, "completion_tokens": 99},
        {"ok": True, "usage_reported": True, "completion_tokens": 1},  # the cache warm-up belongs to no task
    ]
    assert structured_output.output_tokens_by_task(calls) == [
        {"tasks": [1], "calls": 1, "basis": "MEASURED", "output_tokens": 7},
        {"tasks": [2], "calls": 1, "basis": "UNVERIFIED", "output_tokens": None},
    ]
