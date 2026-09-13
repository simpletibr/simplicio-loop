import json

from simplicio_loop import cli


def test_cli_blocked_is_nonzero_and_writes_stream_safe_result(tmp_path, monkeypatch, capsys):
    outcome = {"schema": "simplicio.run-outcome/v1", "outcome": "BLOCKED", "exit_code": 20}
    monkeypatch.setattr(cli, "conduct_run", lambda *a, **k: {"state": {"phase": "blocked"}, "outcome": outcome})
    target = tmp_path / "result.json"
    code = cli.run(str(tmp_path), "task.md", "verified", 1, "provider", "strict", str(target))
    assert code == 20
    assert json.loads(target.read_text()) == outcome
    public = json.loads(capsys.readouterr().out)
    assert public["schema"] == "simplicio.loop-execution/v1"
    assert public["status"] == "BLOCKED"
    assert public["dispatch"]["outcome"]["exit_code"] == 20


def test_cli_complete_without_v1_receipt_is_blocked(tmp_path, monkeypatch):
    outcome = {"schema": "simplicio.run-outcome/v1", "outcome": "COMPLETE", "exit_code": 0}
    monkeypatch.setattr(cli, "conduct_run", lambda *a, **k: {"state": {"phase": "done"}, "outcome": outcome})
    assert cli.run(str(tmp_path), "task.md", "verified", 1, "provider") == 2


def test_wrapper_never_mistakes_blocked_for_success(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "conduct_run", lambda *a, **k: {"outcome": {"schema": "simplicio.run-outcome/v1", "outcome": "BLOCKED", "exit_code": 20}})
    assert cli.run(str(tmp_path), "task.md", "verified", 1, "provider", result_file=str(tmp_path / "o.json")) != 0


def test_cli_infrastructure_failure_has_stable_payload_and_code(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "conduct_run", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    target = tmp_path / "failure.json"
    assert cli.run(str(tmp_path), "task.md", "verified", 1, "provider", result_file=str(target)) == 24
    assert json.loads(target.read_text())["outcome"] == "INFRASTRUCTURE_FAILURE"
