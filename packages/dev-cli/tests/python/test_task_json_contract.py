import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from simplicio import cli


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _true_cmd():
    return f'"{sys.executable}" -c "raise SystemExit(0)"'


def _event_records(root: Path) -> list[dict]:
    path = root / ".simplicio-loop" / "events.jsonl"
    assert path.is_file(), f"expected durable Dev CLI event receipt at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _assert_plan_required(code: int, stdout: str) -> dict:
    payload = json.loads(stdout)
    assert code == 2
    assert payload["schema"] == "simplicio.dev-cli.task-result/v1"
    assert payload["status"] == "blocked"
    assert payload["reason_code"] == "plan_required"
    assert payload["next_action"] == "use simplicio-dev-cli edit --plan <edit-plan.json> --apply"
    return payload


def test_task_prose_goal_without_plan_is_plan_required_json(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(
        [
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--stack",
            "angular",
            "--target",
            "frontend/app.ts",
            "--json",
        ]
    )
    _assert_plan_required(code, capsys.readouterr().out)
    assert (tmp_path / "frontend" / "app.ts").read_text(encoding="utf-8") == "old\n"


def test_task_prose_goal_without_plan_prints_blocked_reason(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(
        [
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--stack",
            "angular",
            "--target",
            "frontend/app.ts",
        ]
    )
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == "BLOCKED: plan_required"


def test_task_dry_run_without_plan_is_plan_required(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(
        [
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--target",
            "frontend/app.ts",
            "--dry-run-task",
            "--json",
        ]
    )
    _assert_plan_required(code, capsys.readouterr().out)
    assert not (tmp_path / ".simplicio-loop" / "last_output.txt").exists()


def test_task_verify_only_succeeds_without_model_or_mutation(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "marker.txt"
    marker.write_text("unchanged", encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", _true_cmd())

    code = cli.main(["task", "--root", str(tmp_path), "--verify-only", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema"] == "simplicio.dev-cli.verification-only/v1"
    assert payload["status"] == "verified"
    assert payload["model_invoked"] is False
    assert payload["applied"] is False
    assert payload["files_changed"] == []
    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_task_verify_only_blocks_before_process_when_command_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)

    code = cli.main(["task", "--root", str(tmp_path), "--verify-only", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["model_invoked"] is False
    assert payload["blocked_preconditions"][0]["retryable"] is True


def test_task_verify_only_uses_independent_file_validation_and_records_receipts(
    tmp_path, monkeypatch, capsys
):
    command_source = "import os,sys; sys.exit(0 if os.path.isfile('target.txt') else 1)"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(command_source)}"

    for present, expected_code, expected_event in (
        (False, 1, "validation_fail"),
        (True, 0, "validation_pass"),
    ):
        project = tmp_path / ("present" if present else "absent")
        project.mkdir()
        if present:
            (project / "target.txt").write_text("independent fixture\n", encoding="utf-8")
        monkeypatch.setenv("SIMPLICIO_TEST_CMD", command)
        monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

        code = cli.main(
            [
                "task",
                "--root",
                str(project),
                "--target",
                "target.txt",
                "--verify-only",
                "--json",
            ]
        )

        payload = json.loads(capsys.readouterr().out)
        assert code == expected_code
        assert payload["model_invoked"] is False
        assert payload["applied"] is False
        assert payload["verify"]["exit_code"] == expected_code
        receipt = _event_records(project)[-1]
        assert receipt["schema"] == "simplicio.dev-cli-event/v1"
        assert receipt["event"] == expected_event
        assert receipt["payload"]["target"] == "target.txt"
        assert receipt["payload"]["exit_code"] == expected_code


def test_task_dry_run_subprocess_emits_plan_required_json(tmp_path):
    _write(tmp_path / "app.py", "old\n")
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(repo_root),
            "SIMPLICIO_MAPPER_CLI": "0",
            "SIMPLICIO_SKIP_AUTO_INIT": "1",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "simplicio.cli",
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--target",
            "app.py",
            "--dry-run-task",
            "--json",
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    _assert_plan_required(completed.returncode, completed.stdout)
    assert completed.stdout.count("\n") == 1


def test_task_plan_flag_is_deprecated_edit_alias(tmp_path, monkeypatch, capsys):
    plan = {
        "schema": "simplicio.dev-cli.edit-plan/v1",
        "operations": [{"op": "create_file", "path": "hello.txt", "contents": "hi\n"}],
    }
    plan_path = tmp_path / "edit-plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(
        [
            "task",
            "--root",
            str(tmp_path),
            "--plan",
            str(plan_path),
            "--dry-run-task",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code != 2 or payload.get("reason_code") != "plan_required"
    assert payload.get("reason_code") != "plan_required"
    assert "schema" in payload


def test_cli_entrypoint_propagates_cli_exit_code(capsys, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(["scratch"])
    captured = capsys.readouterr()
    assert code == 2
    assert "provide a goal" in captured.err
