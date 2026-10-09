"""The execution report records role, model and effort per agent (#1502)."""

from __future__ import annotations

import json

import pytest

from simplicio_loop import execution_report as er


def test_record_task_stores_the_agent(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(
        report, task_id="t1", title="x", issue="1502",
        agent={"role": "execution", "model": "claude-haiku-5-5", "effort": "high"},
    )
    assert report["tasks"][0]["agent"] == {"role": "execution", "model": "claude-haiku-5-5", "effort": "high"}


def test_task_without_agent_has_none(tmp_path):
    report = er.new_report(tmp_path)
    er.record_task(report, task_id="t1", title="x")
    assert report["tasks"][0]["agent"] is None


def test_unknown_role_or_effort_is_refused(tmp_path):
    report = er.new_report(tmp_path)
    with pytest.raises(ValueError):
        er.record_task(report, task_id="t", title="x", agent={"role": "boss", "model": "m", "effort": "high"})
    with pytest.raises(ValueError):
        er.record_task(report, task_id="t", title="x", agent={"role": "planning", "model": "m", "effort": "max"})
    with pytest.raises(ValueError):
        er.record_task(report, task_id="t", title="x", agent={"role": "planning", "model": "", "effort": "high"})


def test_consolidate_counts_tasks_per_role(tmp_path):
    report = er.new_report(tmp_path)
    for i, role in enumerate(("execution", "execution", "coordination")):
        er.record_task(report, task_id="t%d" % i, title="x", agent={"role": role, "model": "m", "effort": "high"})
    er.record_task(report, task_id="t9", title="no agent")
    assert er.consolidate(report)["tasks_by_role"] == {"coordination": 1, "execution": 2}


def test_cli_flags_record_the_agent(tmp_path, capsys):
    code = er.main([
        "record-task", "--repo", str(tmp_path), "--task-id", "t1", "--title", "x",
        "--role", "coordination", "--model", "claude-sonnet-5-5", "--effort", "high",
    ])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tasks"][0]["agent"] == {"role": "coordination", "model": "claude-sonnet-5-5", "effort": "high"}


def test_cli_rejects_a_partial_agent(tmp_path, capsys):
    code = er.main(["record-task", "--repo", str(tmp_path), "--task-id", "t1", "--title", "x", "--role", "planning"])
    assert code == 2
