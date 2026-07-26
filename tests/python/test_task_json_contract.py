import json
import sys

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

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["blocked_preconditions"][0]["next_surface"]
    reasons = {item["reason"] for item in payload["blocked_preconditions"]}
    assert "artifacts_missing" in reasons
    assert "no_handoff_targets" in reasons
    assert called["generate"] == 0


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
