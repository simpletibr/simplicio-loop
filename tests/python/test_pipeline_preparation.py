from __future__ import annotations

import pytest

from simplicio import pipeline_preparation
from simplicio.execution_mode import ExecutionInputError
from simplicio.task_spec import TaskSpec


def test_prepare_pipeline_inputs_builds_immutable_route_inputs(tmp_path):
    prepared = pipeline_preparation.prepare_pipeline_inputs(
        "standalone",
        root=tmp_path,
        repo_root=tmp_path,
        scope_root=tmp_path,
    )

    assert prepared.input.actual_root == tmp_path.resolve()
    assert prepared.requested_execution_mode == "standalone"
    assert prepared.profile.effective_mode == "standalone"
    assert prepared.execution.attempt is None


def test_prepare_pipeline_inputs_preserves_fail_closed_input_errors(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise ExecutionInputError("INCOMPATIBLE_CONTEXT", "invalid context")

    monkeypatch.setattr(pipeline_preparation, "prepare_execution_inputs", fail)

    with pytest.raises(ExecutionInputError, match="INCOMPATIBLE_CONTEXT"):
        pipeline_preparation.prepare_pipeline_inputs("auto", root=tmp_path)


def test_prepare_task_preflight_builds_context_and_identity_decisions(tmp_path):
    prepared = pipeline_preparation.prepare_pipeline_inputs(
        "standalone",
        root=tmp_path,
        repo_root=tmp_path,
        scope_root=tmp_path,
    )

    preflight = pipeline_preparation.prepare_task_preflight(
        prepared,
        target="src/app.py",
        dry_run_task=False,
    )

    assert preflight.context_error is None
    assert preflight.identity_error is None
    assert preflight.identity_required is False
    assert preflight.task_context is not None
    assert preflight.task_context.target == "src/app.py"
    assert preflight.profile.effective_mode == "standalone"


def test_prepare_task_preflight_preserves_repo_root_block(tmp_path):
    prepared = pipeline_preparation.prepare_pipeline_inputs(
        "standalone",
        root=tmp_path,
        repo_root=tmp_path / "declared-repo",
        scope_root=tmp_path,
    )

    preflight = pipeline_preparation.prepare_task_preflight(
        prepared,
        target="app.py",
        dry_run_task=False,
    )

    assert preflight.task_context is None
    assert preflight.context_error is not None
    assert preflight.context_error.code == "REPO_ROOT_MISMATCH"


def _task_spec() -> TaskSpec:
    return TaskSpec(
        task_id="task-420",
        source={"kind": "argument"},
        source_hash="0" * 64,
        language="pt-BR",
    )


def test_resolve_task_spec_route_allows_missing_or_integrated_task():
    assert pipeline_preparation.resolve_task_spec_route(None, "standalone") == (
        pipeline_preparation.TaskSpecRouteDecision(blocked=False)
    )
    assert pipeline_preparation.resolve_task_spec_route(_task_spec(), "integrated") == (
        pipeline_preparation.TaskSpecRouteDecision(blocked=False)
    )


@pytest.mark.parametrize("mode", ["standalone", "blocked"])
def test_resolve_task_spec_route_rejects_non_integrated_task(mode):
    decision = pipeline_preparation.resolve_task_spec_route(_task_spec(), mode)

    assert decision == pipeline_preparation.TaskSpecRouteDecision(
        blocked=True,
        code="TASK_SPEC_REQUIRES_INTEGRATED_MODE",
        message="typed TaskSpec input is accepted only by the integrated execution path",
    )
