from __future__ import annotations

from simplicio import pipeline
from simplicio.orchestrator import feature
from simplicio.scratch.plan_schema import Task
from simplicio.standalone_migration import mutation_receipt


def _task(target: str = "src/app.py") -> Task:
    return Task(
        id="issue-404-task",
        goal="update a bounded file",
        target=target,
        criteria="- passes",
        constraints="- keep scope",
        verify='python -c "raise SystemExit(0)"',
    )


def test_feature_context_route_never_calls_scratch_codegen(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    def fake_pipeline(task, project_dir, stack, **kwargs):
        seen["task"] = task
        seen["project_dir"] = project_dir
        seen["context"] = kwargs["forwarded_pipeline_kwargs"]
        return False, "blocked"

    monkeypatch.setattr(feature, "run_plan_task", fake_pipeline)
    stack = feature.StackRegistry().get("php-vanilla")
    assert stack is not None
    passed, log = feature._run_feature_task(
        _task("docs/outside.md"),
        tmp_path,
        stack,
        forwarded_pipeline_kwargs={
            "repo_root": str(tmp_path),
            "scope_root": str(tmp_path / "src"),
        },
    )
    assert passed is False
    assert log == "blocked"
    assert seen["context"] == {"repo_root": str(tmp_path), "scope_root": str(tmp_path / "src")}


def test_empty_feature_context_route_fails_closed_before_any_mutation(tmp_path, monkeypatch):
    called = {"pipeline": 0}

    def fake_pipeline(*args, **kwargs):
        called["pipeline"] += 1
        return False, "MUTATION_CONTEXT_REQUIRED"

    monkeypatch.setattr(feature, "run_plan_task", fake_pipeline)
    stack = feature.StackRegistry().get("php-vanilla")
    assert stack is not None
    passed, log = feature._run_feature_task(_task(), tmp_path, stack, forwarded_pipeline_kwargs={})
    assert passed is False
    assert log == "MUTATION_CONTEXT_REQUIRED"
    assert called == {"pipeline": 1}


def test_pipeline_blocked_exit_has_stable_truthful_receipt(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "update a file",
        "src/app.py",
        "- passes",
        "- bounded",
        mode="standalone",
        quiet=True,
    )
    receipt = result["mutation_authorization_receipt"]
    assert result["applied"] is False
    assert receipt["route"] == "blocked"
    assert receipt["final_status"] == "blocked"


def test_dry_run_receipt_is_not_applied(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_PREFLIGHT", "1")
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "inspect a file",
        "src/app.py",
        "- report",
        "- read only",
        mode="standalone",
        dry_run_task=True,
        quiet=True,
    )
    receipt = result["mutation_authorization_receipt"]
    assert result["applied"] is False
    assert receipt["final_status"] in {"blocked", "dry_run"}
    assert receipt["final_status"] != "applied"


def test_integrated_non_applied_status_is_truthful():
    assert (
        pipeline._final_receipt_status(
            {"applied": False, "status": "integrated_atomic", "observation": {"outcome": "rejected"}},
            dry_run=False,
        )
        == "blocked"
    )
    assert (
        pipeline._final_receipt_status(
            {"applied": False, "status": "integrated_atomic", "observation": {"outcome": "error"}},
            dry_run=False,
        )
        == "failed"
    )


def test_legacy_route_never_infers_applied():
    receipt = mutation_receipt("legacy_standalone", entrypoint="edit")
    assert receipt["final_status"] == "unknown"
