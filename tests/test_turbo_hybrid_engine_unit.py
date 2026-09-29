"""3.47.0 hybrid mode, the engine: dependency components, one model call each, all at the same time.

Tasks that depend on each other (a file they share, ``depends_on``) are ONE component and ONE model call. Components that
do not depend on each other are asked at the same time (asyncio), so a run costs about one call's wall time, not the sum.
There is no warm-up call and no wave.

A reply marked ``fatal`` (the host CLI is missing, not logged in, timed out, the budget is spent) is not a bad plan, so
the engine does not send it back to the model as a dev-cli rejection. It keeps what the other components applied and
reports the cause, so the caller can hand the rest to the host.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading

import pytest

from simplicio_loop import turbo
from simplicio_loop.turbo import repair_with_test_output, run_turbo

pytestmark = pytest.mark.usefixtures("hermetic_hybrid_detection")
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
    """The plan a model would write: one page for every "N. Create pageN" line of the latest task message."""
    text = next(m["content"] for m in reversed(messages) if m["role"] == "user" and "Tasks:" in m["content"])
    numbers = re.findall(r"^(\d+)\. Create page", text, flags=re.M)
    return json.dumps({"operations": [{"path": f"page{n}.html", "find": "", "replace": f"page {n}\n"} for n in numbers]})


def _asked(messages) -> list[int]:
    text = next(m["content"] for m in reversed(messages) if m["role"] == "user" and "Tasks:" in m["content"])
    return [int(n) for n in re.findall(r"^(\d+)\. Create page", text, flags=re.M)]


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


def test_a_chain_of_ten_tasks_is_one_model_call(repo):
    seen = []

    def complete(arm, messages, **kwargs):
        seen.append(_asked(messages))
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(10, chained=True), complete)
    assert seen == [list(range(1, 11))]  # every task of the chain in the one message
    assert result["turns"] == 1 and result["applied_all"] is True and result["outcomes"][0]["tasks"] == list(range(1, 11))
    assert all((repo / f"page{i}.html").is_file() for i in range(1, 11))


def test_tasks_joined_by_depends_on_are_one_component_and_the_rest_stand_alone(repo):
    seen = []
    tasks = [{"index": 1, "text": "Create page1", "target": "page1.html", "depends_on": []},
             {"index": 2, "text": "Create page2", "target": "page2.html", "depends_on": []},
             {"index": 3, "text": "Create page3", "target": "page3.html", "depends_on": [1]}]

    def complete(arm, messages, **kwargs):
        seen.append(_asked(messages))
        return {"ok": True, "content": _plan_for(messages)}

    run_turbo(repo, tasks, complete)
    assert sorted(seen) == [[1, 3], [2]]  # 3 depends on 1, so they go together; 2 is on its own


def test_independent_tasks_are_asked_at_the_same_time(repo):
    barrier = threading.Barrier(3, timeout=10)  # all three calls must be in flight together, or the barrier breaks

    def complete(arm, messages, **kwargs):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            return {"ok": False, "error": "the calls did not overlap"}
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(3), complete)
    assert result["turns"] == 3 and result["applied_all"] is True and result["stopped"] is None
    assert [o["tasks"] for o in result["outcomes"]] == [[1], [2], [3]]  # component order, not completion order


def test_a_chain_of_two_and_two_independent_tasks_are_three_calls(repo):
    seen, lock = [], threading.Lock()
    tasks = [*_tasks(2, chained=True), *_tasks(2, start=3)]

    def complete(arm, messages, **kwargs):
        with lock:
            seen.append(_asked(messages))
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, tasks, complete)
    assert sorted(seen) == [[1, 2], [3], [4]] and result["turns"] == 3 and result["applied_all"] is True
    assert [c["turn"] for c in result["llm_calls"]] == [1, 2, 3]


def test_there_is_no_warm_up_call_and_no_wave(repo):
    seen, lock = [], threading.Lock()

    def complete(arm, messages, **kwargs):
        with lock:
            seen.append((kwargs, len(messages)))
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(6), complete)
    assert len(seen) == 6 and all(kw == {} and count == 2 for kw, count in seen)  # header + tasks; no 1-token call
    assert "wave" not in result and not any("warm" in call for call in result["llm_calls"])
    assert not hasattr(turbo, "WAVE_TURBO_ABOVE")


def test_a_fatal_reply_in_one_component_keeps_the_others_that_answered(repo):
    def complete(arm, messages, **kwargs):
        if _asked(messages) == [3]:
            return dict(FATAL)
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, [*_tasks(2, chained=True), *_tasks(2, start=3)], complete)
    by_task = {o["tasks"][0]: o for o in result["outcomes"]}
    assert [by_task[i]["applied"] for i in (1, 3, 4)] == [True, False, True]
    assert by_task[3]["fatal"]["reason_code"] == "host_timeout" and result["stopped"]["reason_code"] == "host_timeout"
    assert result["applied_all"] is False and result["turns"] == 3  # nothing was retried
    assert all((repo / f"page{i}.html").is_file() for i in (1, 2, 4)) and not (repo / "page3.html").exists()


def test_a_component_dev_cli_refuses_does_not_stop_the_others(repo):
    def complete(arm, messages, **kwargs):
        if _asked(messages) == [2]:
            return {"ok": True, "content": json.dumps({"operations": [{"path": "README.md", "find": "NOPE", "replace": "x"}]})}
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(3), complete)
    assert [o["applied"] for o in result["outcomes"]] == [True, False, True]
    assert result["stopped"] is None and result["turns"] == 4  # component 2 asked twice: the one retry with dev-cli's error
    assert (repo / "page1.html").is_file() and (repo / "page3.html").is_file() and not (repo / "page2.html").exists()


def test_a_deadline_already_spent_asks_nothing_and_names_the_budget(repo, monkeypatch):
    monkeypatch.setattr(turbo, "_clock", lambda: 1000.0)
    calls = []

    def complete(arm, messages, **kwargs):
        calls.append(1)
        return {"ok": True, "content": _plan_for(messages)}

    result = run_turbo(repo, _tasks(4), complete, deadline=1000.0)
    assert calls == [] and result["turns"] == 0 and result["applied_all"] is False
    assert result["stopped"]["reason_code"] == "budget"
    assert [o["tasks"] for o in result["outcomes"]] == [[1], [2], [3], [4]]
    assert all(o["skipped"] and "not attempted" in o["reason"] and "budget" in o["reason"] for o in result["outcomes"])


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
