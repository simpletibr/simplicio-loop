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


def _diff(path):
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            "",
            "TEST:",
            "assert True",
        ]
    )


def _true_cmd():
    return f'"{sys.executable}" -c "raise SystemExit(0)"'


def _event_records(root: Path) -> list[dict]:
    path = root / ".simplicio" / "events.jsonl"
    assert path.is_file(), f"expected durable Dev CLI event receipt at {path}"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_task_dry_run_json_does_not_touch_worktree(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: _diff("frontend/app.ts"))
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"files": [{"path": "frontend/app.ts"}]}},
    )
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
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "frontend/app.ts"
    assert payload["applied"] is False
    assert payload["files_changed"] == ["frontend/app.ts"]
    assert payload["tokens_used"]["prompt"] > 0
    assert payload["tokens_used"]["completion"] > 0
    assert payload["cost_usd"] == 0.0
    assert payload["warnings"] == []
    assert not (tmp_path / ".simplicio" / "last_output.txt").exists()
    assert (tmp_path / "frontend" / "app.ts").read_text(encoding="utf-8") == "old\n"


def test_standalone_preflight_skips_provider_after_context_gate(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "README.md", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_STANDALONE_PREFLIGHT", "1")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"files": [{"path": "README.md"}]}},
    )
    called = {"generate": 0}

    def fail_if_called(*_args, **_kwargs):
        called["generate"] += 1
        raise AssertionError("standalone preflight must not invoke a provider")

    monkeypatch.setattr("simplicio.pipeline.generate", fail_if_called)

    code = cli.main(
        [
            "task",
            "verify README",
            "--root",
            str(tmp_path),
            "--target",
            "README.md",
            "--mode",
            "standalone",
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["warnings"] == ["standalone_preflight_provider_skipped"]
    assert called["generate"] == 0


def test_task_json_reports_normal_run(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", _true_cmd())
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: _diff("frontend/app.ts"))
    monkeypatch.setattr(
        "simplicio.pipeline._run_impact_tests",
        lambda *_args, **_kwargs: {
            "result": "no_impact_tests",
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
        },
    )
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

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["files_changed"] == ["frontend/app.ts"]
    assert "frontend/app.ts" in payload["diff_summary"]
    assert payload["warnings"] == []
    assert (tmp_path / ".simplicio" / "last_output.txt").exists()


def test_task_bound_paths_refuses_out_of_scope_diff(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    _write(tmp_path / "backend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", _true_cmd())
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: _diff("backend/app.ts"))

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
            "--bound-paths",
            "frontend/**",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["files_changed"] == ["backend/app.ts"]
    assert any("outside bound paths" in warning for warning in payload["warnings"])


def test_task_non_json_propagates_failed_pipeline_exit_code(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    # Non-dry-run task execution fails closed with "verification command
    # missing" before it ever calls generate() unless a real test command is
    # configured — set one (as the sibling tests in this file do) so this
    # test actually exercises the generate/validate-output failure path it
    # targets, rather than the earlier fail-closed precondition.
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", _true_cmd())
    monkeypatch.setattr("simplicio.pipeline.MAX_ATTEMPTS", 1)
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: "TEST:\nassert True\n")

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
    assert code == 1
    assert "FAILED:" in captured.out
    assert "include a unified diff" in captured.err


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


def test_task_dry_run_records_its_own_durable_receipt(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "app.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"files": [{"path": "app.py"}]}},
    )
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *_args, **_kwargs: _diff("app.py"))

    code = cli.main(
        [
            "task",
            "preview app",
            "--root",
            str(tmp_path),
            "--target",
            "app.py",
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    events = _event_records(tmp_path)
    receipt = events[-1]
    assert receipt["schema"] == "simplicio.dev-cli-event/v1"
    assert receipt["event"] == "task_terminal"
    assert receipt["payload"] == {"target": "app.py", "status": "dry_run", "applied": False}


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


def test_task_dry_run_json_fails_closed_with_structured_blocked_preconditions(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "frontend" / "app.ts", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {
            "project_map": {"present": False},
            "precedent_index": {"present": False},
        },
    )
    monkeypatch.setattr("simplicio.pipeline_task_result.map_handoff", lambda _root: None)
    called = {"generate": 0}

    def fail_if_called(*_args, **_kwargs):
        called["generate"] += 1
        raise AssertionError("generate must not run when dry-run preconditions are blocked")

    monkeypatch.setattr("simplicio.pipeline.generate", fail_if_called)

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
            "--dry-run-task",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    payload = json.loads(captured.out)
    assert payload["schema"] == "simplicio.dev-cli.task-result/v1"
    assert payload["status"] == "blocked"
    assert payload["applied"] is False
    assert payload["model_invoked"] is False
    assert payload["next_surface"] == "mapper_artifacts"
    assert payload["execution_profile"] == {
        "requested_mode": "auto",
        "effective_mode": "blocked",
        "reason_code": "artifacts_missing",
    }
    expected_keys = {
        "schema",
        "code",
        "reason",
        "message",
        "next_surface",
        "next_action",
        "retryable",
        "details",
    }
    assert all(set(item) == expected_keys for item in payload["blocked_preconditions"])
    reasons = {item["reason"] for item in payload["blocked_preconditions"]}
    assert "artifacts_missing" in reasons
    assert "no_handoff_targets" in reasons
    assert "BLOCKED[artifacts_missing]" in captured.err
    assert called["generate"] == 0


def test_task_dry_run_subprocess_emits_single_actionable_json_receipt(tmp_path):
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

    payload = json.loads(completed.stdout)
    assert completed.returncode == 1
    assert completed.stdout.count("\n") == 1
    assert payload["schema"] == "simplicio.dev-cli.task-result/v1"
    assert payload["status"] == "blocked"
    assert payload["applied"] is False
    assert payload["model_invoked"] is False
    assert payload["next_surface"] == "mapper_artifacts"
    assert payload["execution_profile"]["effective_mode"] == "blocked"
    assert {item["reason"] for item in payload["blocked_preconditions"]} == {
        "artifacts_missing",
        "no_handoff_targets",
    }
    assert "BLOCKED[artifacts_missing]" in completed.stderr
    assert "BLOCKED[no_handoff_targets]" in completed.stderr


def test_task_dry_run_json_serializes_provider_block_with_context_reason(tmp_path, monkeypatch, capsys):
    from simplicio.providers import ProviderExecutionError

    _write(tmp_path / "app.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr("simplicio.pipeline._dry_run_preconditions", lambda *a, **k: [])

    def blocked_provider(*_args, **_kwargs):
        raise ProviderExecutionError(
            {
                "schema": "simplicio.provider-terminal/v1",
                "status": "blocked",
                "reason_code": "llm_execution_disabled",
                "provider": "disabled",
                "surface": "generate",
                "message": "provider is disabled for this deterministic test",
                "next_action": "use an external orchestrator",
            }
        )

    monkeypatch.setattr("simplicio.pipeline.generate", blocked_provider)
    code = cli.main(
        [
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--target",
            "app.py",
            "--mode",
            "integrated",
            "--dry-run-task",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    reasons = {item["reason"] for item in payload["blocked_preconditions"]}
    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["applied"] is False
    assert payload["model_invoked"] is False
    assert payload["next_surface"] == "context_pack"
    assert payload["execution_profile"]["requested_mode"] == "integrated"
    assert payload["execution_profile"]["effective_mode"] == "blocked"
    assert payload["execution_profile"]["reason_code"] == "CONTEXT_REQUIRED"
    assert {"CONTEXT_REQUIRED", "llm_execution_disabled"} <= reasons
    assert payload["provider_terminal"]["reason_code"] == "llm_execution_disabled"
    assert "provider is disabled" in captured.err


def test_task_dry_run_json_accepts_new_file_under_existing_parent(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "src" / "existing.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {
            "project_map": {"present": True},
            "precedent_index": {"present": True},
        },
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"files": [{"path": "src/existing.py"}]}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline.generate", lambda *a, **k: "diff --git a/src/new.py b/src/new.py\n"
    )

    code = cli.main(
        [
            "task",
            "create module",
            "--root",
            str(tmp_path),
            "--target",
            "src/new.py",
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["target_kind"] == "new_file"


def test_task_dry_run_json_rejects_new_file_outside_root(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {
            "project_map": {"present": True},
            "precedent_index": {"present": True},
        },
    )
    monkeypatch.setattr("simplicio.pipeline_task_result.map_handoff", lambda _root: None)

    code = cli.main(
        [
            "task",
            "create module",
            "--root",
            str(tmp_path),
            "--target",
            "../escape.py",
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert any(item["reason"] == "target_outside_root" for item in payload["blocked_preconditions"])


def test_task_dry_run_json_distinguishes_broader_context_and_target_resolution(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {
            "project_map": {"present": True},
            "precedent_index": {"present": True},
            "inspection": {"warnings": ["deep pass stale"]},
        },
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {
            "context_pack": {
                "needs_broader_context": True,
                "files": [{"path": "frontend/other.ts"}],
            }
        },
    )
    monkeypatch.setattr(
        "simplicio.pipeline.generate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("generate must not run when dry-run is blocked")
        ),
    )

    code = cli.main(
        [
            "task",
            "update app",
            "--root",
            str(tmp_path),
            "--stack",
            "angular",
            "--target",
            "frontend/missing.ts",
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    reasons = {item["reason"] for item in payload["blocked_preconditions"]}
    assert "artifacts_stale" in reasons
    assert "broader_context_required" in reasons
    assert "target_resolution_failed" in reasons


def test_cli_entrypoint_propagates_cli_exit_code(capsys, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    code = cli.main(["scratch"])
    captured = capsys.readouterr()
    assert code == 2
    assert "provide a goal" in captured.err
