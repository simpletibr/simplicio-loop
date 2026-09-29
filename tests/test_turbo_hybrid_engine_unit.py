"""3.47.0 hybrid mode, the engine: a model call that fails for a host reason stops the run cleanly.

A reply marked ``fatal`` (the host CLI is missing, not logged in, timed out, the budget is spent) is not a bad plan, so
the engine does not send it back to the model as a dev-cli rejection. It stops dispatching lanes, keeps what it applied
and reports the cause, so the caller can hand the rest to the host.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from simplicio_loop import turbo
from simplicio_loop.turbo import repair_with_test_output, run_turbo

FATAL = {"ok": False, "fatal": True, "reason_code": "host_timeout", "error": "opencode did not answer within 90s"}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda root, **kwargs: None)
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "project-map.json").write_text('{"mark":"MAP"}', encoding="utf-8")
    return tmp_path


def _tasks(count: int, chained: bool = False, start: int = 1) -> list[dict]:
    return [{"index": i, "text": f"Create page{i}", "target": f"page{i}.html",
             "depends_on": [i - 1] if chained and i > start else []} for i in range(start, start + count)]


def _plan_for(messages) -> str:
    """The plan a model would write: the task number in the latest task message names the page."""
    text = next(m["content"] for m in reversed(messages) if m["role"] == "user" and "Tasks:" in m["content"])
    number = text.split("Tasks:", 1)[1].strip().split(".", 1)[0].strip()
    return json.dumps({"operations": [{"path": f"page{number}.html", "find": "", "replace": f"page {number}\n"}]})


def test_a_fatal_reply_is_not_retried_and_the_run_reports_the_cause(repo):
    calls = []

    def complete(arm, messages, **kwargs):
        calls.append(messages)
        return dict(FATAL)

    result = run_turbo(repo, _tasks(1), complete)
    assert len(calls) == 1  # the engine does not ask the model to "correct" a host failure
    assert result["applied_all"] is False and result["outcomes"][0]["applied"] is False
    assert result["stopped"] == {"reason_code": "host_timeout", "detail": "opencode did not answer within 90s"}
    assert result["outcomes"][0]["fatal"] == result["stopped"] and result["llm_calls"][0]["ok"] is False


def test_a_finished_run_reports_no_stop(repo):
    result = run_turbo(repo, _tasks(1), lambda arm, messages, **kw: {"ok": True, "content": _plan_for(messages)})
    assert result["stopped"] is None and result["applied_all"] is True


def test_a_fatal_reply_in_a_chain_keeps_the_applied_lanes_and_skips_the_rest(repo):
    seen = []

    def complete(arm, messages, **kwargs):
        seen.append(1)
        if len(seen) == 3:
            return dict(FATAL)
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(5, chained=True), complete)
    assert len(seen) == 3  # lanes 4 and 5 were never asked
    by_task = {o["tasks"][0]: o for o in result["outcomes"]}
    assert [by_task[i]["applied"] for i in (1, 2, 3, 4, 5)] == [True, True, False, False, False]
    assert by_task[4]["skipped"] is True and "not attempted" in by_task[4]["reason"] and "host_timeout" in by_task[4]["reason"]
    assert result["stopped"]["reason_code"] == "host_timeout"
    assert (repo / "page1.html").is_file() and (repo / "page2.html").is_file() and not (repo / "page3.html").exists()


def test_a_fatal_reply_in_a_fan_out_keeps_the_lanes_that_answered(repo):
    def complete(arm, messages, **kwargs):
        if "Tasks:\n3." in messages[-1]["content"]:
            return dict(FATAL)
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(4), complete, warm=False)
    by_task = {o["tasks"][0]: o for o in result["outcomes"]}
    assert [by_task[i]["applied"] for i in (1, 2, 3, 4)] == [True, True, False, True]
    assert by_task[3]["fatal"]["reason_code"] == "host_timeout" and result["stopped"]["reason_code"] == "host_timeout"


def test_the_warm_up_call_is_skipped_for_a_host_backend(repo):
    seen = []

    def complete(arm, messages, **kwargs):
        seen.append(kwargs)
        if kwargs.get("max_tokens") == 1:  # the warm-up call
            return {"ok": True, "content": "OK"}
        return {"ok": True, "content": _plan_for(messages)}

    run_turbo(repo, _tasks(4), complete, warm=False)
    assert len(seen) == 4 and all("max_tokens" not in kw for kw in seen)
    seen.clear()
    run_turbo(repo, _tasks(4, start=5), complete)  # the provider default is unchanged: one warm call, then the lanes
    assert len(seen) == 5 and seen[0].get("max_tokens") == 1


def test_a_fatal_warm_up_stops_before_any_lane(repo):
    calls = []

    def complete(arm, messages, **kwargs):
        calls.append(kwargs)
        return dict(FATAL)

    result = run_turbo(repo, _tasks(4), complete)
    assert len(calls) == 1 and result["applied_all"] is False
    assert [o["applied"] for o in result["outcomes"]] == [False] * 4 and result["stopped"]["reason_code"] == "host_timeout"


def test_the_deadline_stops_new_lanes_and_names_the_budget(repo, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(turbo, "_clock", lambda: now[0])

    def complete(arm, messages, **kwargs):
        now[0] += 60  # every call takes a minute
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(4, chained=True), complete, deadline=1000.0 + 100)
    assert [o["applied"] for o in sorted(result["outcomes"], key=lambda o: o["tasks"][0])] == [True, True, False, False]
    assert result["stopped"]["reason_code"] == "budget"
    assert all("not attempted" in o["reason"] for o in result["outcomes"] if not o["applied"])


def test_a_bad_plan_is_still_retried_once_with_the_dev_cli_error(repo):
    seen = []

    def complete(arm, messages, **kwargs):
        seen.append([dict(m) for m in messages])  # a copy: the engine appends to the list afterwards
        if len(seen) == 1:
            return {"ok": True, "content": json.dumps({"operations": [{"path": "README.md", "find": "NOPE", "replace": "x"}]})}
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(1), complete)
    assert len(seen) == 2 and "dev-cli rejected the plan" in seen[1][-1]["content"]
    assert result["applied_all"] is True and result["stopped"] is None


def test_a_fatal_repair_is_reported_and_applies_nothing(repo):
    result = repair_with_test_output(repo, _tasks(1), lambda arm, messages, **kw: dict(FATAL), "FAIL: nope")
    assert result["applied"] is False and result["fatal"]["reason_code"] == "host_timeout" and result["commands"] == []
