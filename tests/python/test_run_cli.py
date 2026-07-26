import argparse
import json
import os
import sys

import pytest

from simplicio import cli
from simplicio.commands._shared import force_local_if_requested
from simplicio.scratch.plan_schema import Plan, Task


@pytest.fixture(autouse=True)
def _explicit_standalone_mode(monkeypatch):
    """Legacy run-command cases must not depend on auto fallback.

    Issue #257 intentionally made ``auto`` fail closed when a compatible
    Runtime is unavailable.  These tests exercise the explicit local product
    path, so they must select it just like an installed caller would.
    """
    monkeypatch.setenv("SIMPLICIO_EXECUTION_MODE", "standalone")


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


def test_force_local_preserves_explicit_model_and_path(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")
    monkeypatch.setenv("SIMPLICIO_MODEL", "local-llama//models/qwen.gguf")
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", "/models/qwen.gguf")

    force_local_if_requested(argparse.Namespace(local=True))

    assert os.environ["SIMPLICIO_MODEL"] == "local-llama//models/qwen.gguf"
    assert os.environ["SIMPLICIO_LOCAL_MODEL_PATH"] == "/models/qwen.gguf"


def test_force_local_uses_explicit_model_path_when_model_is_unset(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")
    monkeypatch.delenv("SIMPLICIO_MODEL", raising=False)
    monkeypatch.setenv("SIMPLICIO_LOCAL_MODEL_PATH", "/models/qwen.gguf")

    force_local_if_requested(argparse.Namespace(local=True))

    assert os.environ["SIMPLICIO_MODEL"] == "local-llama//models/qwen.gguf"


def test_run_scope_task_preserves_task_json_contract(tmp_path, monkeypatch, capsys):
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
            "run",
            "update frontend/app.ts",
            "--scope",
            "task",
            "--root",
            str(tmp_path),
            "--target",
            "frontend/app.ts",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["files_changed"] == ["frontend/app.ts"]
    assert "scope" not in payload


def test_index_accepts_positional_root(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_index_repo(root, stack):
        seen["root"] = root
        seen["stack"] = stack

    monkeypatch.setattr("simplicio.precedent.index_repo", fake_index_repo)

    code = cli.main(["index", str(tmp_path), "--stack", "python"])

    assert code == 0
    assert seen == {"root": str(tmp_path), "stack": "python"}


def test_env_export_quotes_dotenv_values(tmp_path, monkeypatch, capsys):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "Database__ConnectionString=Host=localhost;Port=5432;Database=maturity_matrix;\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["env-export", str(env_file)])

    assert code == 0
    assert capsys.readouterr().out.strip() == (
        "export Database__ConnectionString='Host=localhost;Port=5432;Database=maturity_matrix;'"
    )


def test_doctor_command_delegates_to_local_model_preflight(monkeypatch):
    seen = {}
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_doctor_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("simplicio.doctor.main", fake_doctor_main)

    code = cli.main(["doctor", "--json"])

    assert code == 0
    assert seen["argv"] == ["--json"]


def test_run_auto_task_infers_target_from_goal(tmp_path, monkeypatch, capsys):
    _write(tmp_path / "src" / "auth.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: _diff("src/auth.py"))
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.artifact_status",
        lambda _root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(
        "simplicio.pipeline_task_result.map_handoff",
        lambda _root: {"context_pack": {"files": [{"path": "src/auth.py"}]}},
    )
    code = cli.main(
        [
            "run",
            "fix bug in src/auth.py",
            "--root",
            str(tmp_path),
            "--dry-run-task",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["task_id"] == "src/auth.py"


def test_run_ambiguous_goal_requires_scope(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["run", "maybe later"])

    assert code == 2
    assert "goal is ambiguous" in capsys.readouterr().err


def test_run_scope_scratch_forwards_to_scratch_cli(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    seen = {}

    def fake_scratch_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("simplicio.scratch.cli.main", fake_scratch_main)

    code = cli.main(
        [
            "run",
            "scaffold a new FastAPI project from scratch",
            "--scope",
            "scratch",
            "--stack",
            "py-fastapi",
            "--plan-only",
            "--json",
        ]
    )

    assert code == 0
    assert seen["argv"] == [
        "scaffold a new FastAPI project from scratch",
        "--stack",
        "py-fastapi",
        "--root",
        ".",
        "--dest",
        ".",
        "--plan-only",
        "--json",
    ]


def test_run_scope_scratch_forwards_existing_project_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    seen = {}

    def fake_scratch_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr("simplicio.scratch.cli.main", fake_scratch_main)

    code = cli.main(
        [
            "run",
            "analyze and align endpoints in this existing project",
            "--scope",
            "scratch",
            "--root",
            str(tmp_path),
            "--plan-only",
        ]
    )

    assert code == 0
    assert seen["argv"] == [
        "analyze and align endpoints in this existing project",
        "--root",
        str(tmp_path),
        "--dest",
        ".",
        "--plan-only",
    ]


def test_run_scope_feature_outputs_orchestrator_result(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def fake_run_feature(**kwargs):
        assert kwargs["stack_slug"] == "py-fastapi"
        return {
            "scope": "feature",
            "goal": kwargs["goal"],
            "stack": "py-fastapi",
            "applied": True,
            "tasks": [{"id": "T01-a", "passed": True}],
            "replans": 0,
            "warnings": [],
        }

    monkeypatch.setattr("simplicio.orchestrator.run_feature", fake_run_feature)

    code = cli.main(
        [
            "run",
            "implement JWT login flow",
            "--scope",
            "feature",
            "--stack",
            "py-fastapi",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "feature"
    assert payload["applied"] is True


def test_integrated_feature_runner_forwards_typed_task_to_runtime(monkeypatch):
    from types import SimpleNamespace

    from simplicio.commands.run import _integrated_feature_task_runner

    captured = {}

    def fake_run_task(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"applied": True, "status": "integrated_atomic"}

    monkeypatch.setattr("simplicio.pipeline.run_task", fake_run_task)
    args = SimpleNamespace(
        _execution_inputs=SimpleNamespace(
            effect_sink=object(),
            context_snapshot={"schema": "simplicio.context-snapshot/v1"},
            context_pack={"schema": "simplicio.context-pack/v1"},
            runtime_handshake={"verified": True},
            attempt=SimpleNamespace(attempt_id="attempt-1"),
        ),
        coordinator_kind="simplicio-agent",
        coordinator_id="agent-1",
    )
    runner = _integrated_feature_task_runner(args)
    task = Task(
        id="T01-api",
        goal="update API",
        target="src/app.py",
        criteria="- endpoint works",
        constraints="- no breaking change",
        verify="pytest -q",
    )

    passed, log = runner(task, None, SimpleNamespace(language="python", framework=None), quiet=True)

    assert passed is True
    assert "integrated_atomic" in log
    assert captured["kwargs"]["mode"] == "integrated"
    assert captured["kwargs"]["context_pack"] == {"schema": "simplicio.context-pack/v1"}
    assert captured["kwargs"]["task_spec"].task_id == "T01-api"


def test_run_scope_feature_json_suppresses_pipeline_logs(
    tmp_path,
    monkeypatch,
    capsys,
):
    _write(tmp_path / "src" / "app.py", "old\n")
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", _true_cmd())

    from simplicio.orchestrator import feature as feature_module

    def fake_planner(stack, goal, project_name):
        return Plan(
            version="1.0",
            stack=stack.slug,
            project_name=project_name,
            rationale="test",
            files_to_create=[],
            tasks=[
                Task(
                    id="T01-app",
                    goal="update app",
                    target="src/app.py",
                    criteria="- passes",
                    constraints="- minimal",
                    verify=_true_cmd(),
                    depends_on=[],
                )
            ],
            deps_to_install=[],
            deps_dev=[],
            test_command=_true_cmd(),
            lint_command=_true_cmd(),
            estimated_total_tasks=1,
        )

    monkeypatch.setattr(feature_module, "generate_plan", fake_planner)
    monkeypatch.setattr("simplicio.pipeline.generate", lambda *a, **k: _diff("src/app.py"))
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
            "run",
            "implement app update",
            "--scope",
            "feature",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["scope"] == "feature"
    assert payload["applied"] is True


def test_run_scope_feature_rejects_negative_max_cost(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(
        [
            "run",
            "implement JWT login flow",
            "--scope",
            "feature",
            "--stack",
            "py-fastapi",
            "--max-cost",
            "-1",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "max cost must be non-negative" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_run_scope_feature_rejects_non_decimal_max_cost(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(
        [
            "run",
            "implement JWT login flow",
            "--scope",
            "feature",
            "--stack",
            "py-fastapi",
            "--max-cost",
            "abc",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "max cost must be a finite decimal" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_run_scope_sprint_requires_max_cost(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--stack",
            "py-fastapi",
        ]
    )

    assert code == 2
    assert "requires --max-cost" in capsys.readouterr().err


def test_run_scope_sprint_rejects_negative_max_cost(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "-1",
        ]
    )

    assert code == 2
    assert "max cost must be non-negative" in capsys.readouterr().err


def test_run_scope_sprint_rejects_non_decimal_max_cost(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "abc",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "max cost must be a finite decimal" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_run_scope_sprint_writes_status_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "SPRINT.md").write_text("# Sprint 01\n", encoding="utf-8")
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )

    seen = {}

    def fake_run_feature(**kwargs):
        seen["max_cost"] = kwargs["max_cost"]
        return {
            "scope": "feature",
            "goal": kwargs["goal"],
            "stack": kwargs["stack_slug"],
            "applied": True,
            "tasks": [{"id": "T01-a", "passed": True}],
            "replans": 0,
            "warnings": [],
        }

    monkeypatch.setattr("simplicio.orchestrator.run_feature", fake_run_feature)

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["cost"]["budget_usd"] == "1"
    assert seen["max_cost"] is None

    status_code = cli.main(["status", "--root", str(tmp_path), "--json"])
    status = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status["sprint_name"] == "sprint-01"
    assert status["completed_features"] == 1
    assert status["complete"] is True
    assert status["cost"]["budget_usd"] == "1"


def test_status_reports_missing_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["status", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "none"
    assert payload["schema"] == "simplicio.dev-cli.status/v1"
    assert payload["artifacts"]["project_map"]["present"] is False
    assert payload["claims_gate"] == {
        "allow_fresh_verification_claim": False,
        "allow_repo_green_claim": False,
        "proof_scope": "none",
        "reason": "fresh passing verification evidence is not available",
    }


def test_status_json_includes_mapper_artifacts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    _write(
        tmp_path / ".simplicio" / "sprint_state.json",
        json.dumps(
            {
                "scope": "sprint",
                "state": "in-progress",
                "sprint": "Sprint 01",
                "completed_features": 1,
                "total_features": 2,
                "failed_features": [],
                "failed_dod_gates": [],
                "complete": False,
            }
        ),
    )
    _write(
        tmp_path / ".simplicio" / "project-map.json",
        json.dumps(
            {
                "schema": "project-map/v1",
                "entry_points": ["src/app.py"],
                "test_files": ["tests/test_app.py"],
                "recent_changes": [{"path": "src/app.py", "status": "modified"}],
            }
        ),
    )

    code = cli.main(["status", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.status/v1"
    assert payload["artifacts"]["project_map"]["present"] is True
    assert payload["artifacts"]["project_map"]["entry_points"] == ["src/app.py"]
    assert payload["claims_gate"]["allow_fresh_verification_claim"] is False
    assert payload["claims_gate"]["proof_scope"] == "none"


def test_status_json_reports_task_batch_when_present_without_sprint_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    _write(
        tmp_path / ".simplicio" / "task_batch.json",
        json.dumps(
            {
                "schema": "simplicio.dev-cli.task-batch/v1",
                "identity": {"source_hash": "source", "plan_hash": "plan", "base_sha": "base"},
                "tasks": [
                    {
                        "id": "TASK-LOGIN",
                        "depends_on": [],
                        "status": "passed",
                        "attempts": 1,
                        "receipt": None,
                    },
                    {
                        "id": "TASK-REPORTS",
                        "depends_on": ["TASK-LOGIN"],
                        "status": "pending",
                        "attempts": 0,
                        "receipt": None,
                    },
                ],
            }
        ),
    )

    code = cli.main(["status", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"] == "in-progress"
    assert payload["task_batch"]["counts"]["passed"] == 1
    assert payload["task_batch"]["ready"] == ["TASK-REPORTS"]
    assert payload["claims_gate"]["allow_fresh_verification_claim"] is False


def test_claims_command_is_public_via_argparse(monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    code = cli.main(["claims", "tag", "code shows improvement"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tag"] in {"MEASURED", "CANON", "UNVERIFIED"}


def test_inspect_command_returns_mapper_backed_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    _write(tmp_path / "src" / "app.py", "import os\n")
    _write(
        tmp_path / ".simplicio" / "project-map.json",
        json.dumps(
            {
                "schema": "project-map/v1",
                "files": [
                    {
                        "path": "src/app.py",
                        "language": "python",
                        "roles": ["entrypoint"],
                        "summary": "main app",
                    }
                ],
                "entry_points": ["src/app.py"],
            }
        ),
    )

    code = cli.main(["inspect", "src/app.py", "--root", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "simplicio.dev-cli.inspect/v1"
    assert payload["target"] == "src/app.py"
    assert payload["artifacts"]["project_map"]["present"] is True
    assert payload["relevant_files"][0]["path"] == "src/app.py"


def test_status_json_reports_invalid_state_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    _write(tmp_path / ".simplicio" / "sprint_state.json", "{invalid json")

    code = cli.main(["status", "--root", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "simplicio-py status: invalid state file:" in captured.err


def test_status_text_reports_state_and_cost(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")

    def write_state(root, **overrides):
        payload = {
            "scope": "sprint",
            "state": "in-progress",
            "sprint": "Sprint 01",
            "total_features": 2,
            "completed_features": 1,
            "failed_features": [],
            "failed_dod_gates": [],
            "complete": False,
            "cost": {"spent_usd": "0.25", "budget_usd": "1"},
        }
        payload.update(overrides)
        _write(root / ".simplicio" / "sprint_state.json", json.dumps(payload))

    complete_root = tmp_path / "complete"
    write_state(complete_root, state="complete", completed_features=2, complete=True)
    assert cli.main(["status", "--root", str(complete_root)]) == 0
    assert capsys.readouterr().out == "complete: Sprint 01 2/2 features cost=0.25/1\n"

    status_code = cli.main(["status", "--root", str(complete_root), "--json"])
    status_payload = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status_payload["claims_gate"] == {
        "allow_fresh_verification_claim": True,
        "allow_repo_green_claim": False,
        "proof_scope": "sprint_state",
        "reason": "last passing evidence came from the stored sprint state; it does not prove repo-wide green",
    }

    failed_root = tmp_path / "failed"
    write_state(failed_root, state="complete", failed_features=["Login"])
    assert cli.main(["status", "--root", str(failed_root)]) == 0
    assert capsys.readouterr().out == "failed: Sprint 01 1/2 features cost=0.25/1\n"

    failed_status_code = cli.main(["status", "--root", str(failed_root), "--json"])
    failed_payload = json.loads(capsys.readouterr().out)
    assert failed_status_code == 0
    assert failed_payload["claims_gate"] == {
        "allow_fresh_verification_claim": False,
        "allow_repo_green_claim": False,
        "proof_scope": "none",
        "reason": "fresh passing verification evidence is not available",
    }

    active_root = tmp_path / "active"
    write_state(active_root)
    assert cli.main(["status", "--root", str(active_root)]) == 0
    assert capsys.readouterr().out == "in-progress: Sprint 01 1/2 features cost=0.25/1\n"


def test_run_scope_sprint_rejects_empty_sprint(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "SPRINT.md").write_text("# Sprint 01\n", encoding="utf-8")

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    assert code == 2
    assert "sprint has no task specs" in capsys.readouterr().err
    state = json.loads((tmp_path / ".simplicio" / "sprint_state.json").read_text(encoding="utf-8"))
    assert state["state"] == "failed"
    assert state["complete"] is False
    assert state["total_features"] == 0


def test_run_scope_sprint_reports_invalid_stack(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "missing",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    assert code == 2
    assert "unknown stack" in capsys.readouterr().err


def test_run_scope_sprint_resumes_completed_features(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )
    (sprint_dir / "02-reports.task.md").write_text(
        "# Reports\n\n## Goal\nImplement reports\n",
        encoding="utf-8",
    )
    state_dir = tmp_path / ".simplicio"
    state_dir.mkdir()
    (state_dir / "sprint_state.json").write_text(
        json.dumps(
            {
                "scope": "sprint",
                "sprint_name": "sprint-01",
                "stack": "py-fastapi",
                "results": [
                    {
                        "task": "Login",
                        "result": {
                            "scope": "feature",
                            "goal": "Implement login flow",
                            "stack": "py-fastapi",
                            "applied": True,
                            "tasks": [],
                            "replans": 0,
                            "warnings": [],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run_feature(**kwargs):
        calls.append(kwargs["goal"])
        return {
            "scope": "feature",
            "goal": kwargs["goal"],
            "stack": kwargs["stack_slug"],
            "applied": True,
            "tasks": [],
            "replans": 0,
            "warnings": [],
        }

    monkeypatch.setattr("simplicio.orchestrator.run_feature", fake_run_feature)

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == ["Implement reports"]
    assert payload["resumed"] is True
    assert len(payload["features"]) == 2


def test_run_scope_sprint_does_not_resume_ambiguous_duplicate_titles(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "01-login.task.md").write_text(
        "# Same\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )
    (sprint_dir / "02-reports.task.md").write_text(
        "# Same\n\n## Goal\nImplement reports\n",
        encoding="utf-8",
    )
    state_dir = tmp_path / ".simplicio"
    state_dir.mkdir()
    (state_dir / "sprint_state.json").write_text(
        json.dumps(
            {
                "scope": "sprint",
                "sprint_name": "sprint-01",
                "stack": "py-fastapi",
                "results": [
                    {
                        "task": "Same",
                        "result": {
                            "scope": "feature",
                            "goal": "Implement login flow",
                            "stack": "py-fastapi",
                            "applied": True,
                            "tasks": [],
                            "replans": 0,
                            "warnings": [],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_run_feature(**kwargs):
        calls.append(kwargs["goal"])
        return {
            "scope": "feature",
            "goal": kwargs["goal"],
            "stack": kwargs["stack_slug"],
            "applied": True,
            "tasks": [],
            "replans": 0,
            "warnings": [],
        }

    monkeypatch.setattr("simplicio.orchestrator.run_feature", fake_run_feature)

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert calls == ["Implement login flow", "Implement reports"]
    assert len(payload["features"]) == 2
    assert {row["task_id"] for row in payload["features"]} == {
        "01-login.task.md",
        "02-reports.task.md",
    }


def test_run_scope_sprint_manual_dod_blocks_completion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    sprint_dir = tmp_path / ".specs" / "sprints" / "sprint-01"
    sprint_dir.mkdir(parents=True)
    (sprint_dir / "SPRINT.md").write_text("- [ ] Manual QA approved\n", encoding="utf-8")
    (sprint_dir / "01-login.task.md").write_text(
        "# Login\n\n## Goal\nImplement login flow\n",
        encoding="utf-8",
    )

    def fake_run_feature(**kwargs):
        return {
            "scope": "feature",
            "goal": kwargs["goal"],
            "stack": kwargs["stack_slug"],
            "applied": True,
            "tasks": [],
            "replans": 0,
            "warnings": [],
        }

    monkeypatch.setattr("simplicio.orchestrator.run_feature", fake_run_feature)

    code = cli.main(
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--root",
            str(tmp_path),
            "--stack",
            "py-fastapi",
            "--max-cost",
            "1",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["applied"] is False
    assert payload["dod"][0]["passed"] is False

    status_code = cli.main(["status", "--root", str(tmp_path), "--json"])
    status = json.loads(capsys.readouterr().out)
    assert status_code == 0
    assert status["state"] == "failed"
    assert status["failed_dod_gates"] == ["Manual QA approved"]
