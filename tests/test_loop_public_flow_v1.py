from __future__ import annotations

import json

from simplicio_loop import cli_impl, intake_planner


def test_tick_does_not_report_completed_without_a_v1_publication(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_impl,
        "execute_operator",
        lambda *args, **kwargs: {"status": "completed", "run_id": "run-1"},
    )

    assert cli_impl.tick("missing-repo", "run-1", 1) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"].lower() in {"blocked", "partial"}
    assert payload["schema"] == "simplicio.loop-execution/v1"
    assert payload["verified"] is False


def test_single_task_fast_completed_result_is_blocked_without_v1_artifacts(monkeypatch, tmp_path, capsys):
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps({"goal": "bounded task"}), encoding="utf-8")
    monkeypatch.setattr(
        intake_planner,
        "dispatch_single_task_fast",
        lambda tasks: {"status": "COMPLETED", "route": "single-task-fast"},
    )

    assert cli_impl.main(["single-task-fast", "--task-file", str(task_file)]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in {"BLOCKED", "PARTIAL"}
    assert payload["schema"] == "simplicio.loop-execution/v1"
    assert payload["verified"] is False
