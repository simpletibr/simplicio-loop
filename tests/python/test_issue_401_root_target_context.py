from __future__ import annotations

from pathlib import Path

import pytest

from simplicio.pipeline import run_task
from simplicio.task_context import TaskContext, TaskContextError


def test_root_target_context_resolves_relative_target_inside_declared_scope(tmp_path: Path) -> None:
    scope = tmp_path / "src"
    scope.mkdir()
    context = TaskContext.from_values(
        repo_root=tmp_path,
        scope_root=scope,
        target="app.py",
        context_snapshot_id="snapshot-401",
        context_pack_hash="pack-401",
        attempt_id="attempt-401",
        require_identity=True,
    )

    assert context.target == "app.py"
    assert context.repo_root == str(tmp_path.resolve())
    assert context.scope_root == str(scope.resolve())
    assert len(context.context_hash) == 64
    assert (
        context.receipt(
            route="runtime_effect_api",
            effective_mode="integrated",
            authorization_id="auth-401",
            verification_status="verified",
        )["authorization_id"]
        == "auth-401"
    )


def test_root_scope_mismatch_is_stable_and_fail_closed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-401"
    with pytest.raises(TaskContextError, match="ROOT_SCOPE_MISMATCH") as error:
        TaskContext.from_values(repo_root=tmp_path, scope_root=outside, target="app.py")
    assert error.value.code == "ROOT_SCOPE_MISMATCH"


@pytest.mark.parametrize("target", ["../escape.py", "/absolute/escape.py", "src/../escape.py"])
def test_target_outside_scope_is_rejected(tmp_path: Path, target: str) -> None:
    with pytest.raises(TaskContextError, match="TARGET_OUTSIDE_SCOPE") as error:
        TaskContext.from_values(repo_root=tmp_path, scope_root=tmp_path, target=target)
    assert error.value.code == "TARGET_OUTSIDE_SCOPE"


def test_integrated_context_requires_mapper_identity_and_attempt(tmp_path: Path) -> None:
    with pytest.raises(TaskContextError, match="MAPPER_CONTEXT_IDENTITY_REQUIRED") as error:
        TaskContext.from_values(
            repo_root=tmp_path,
            scope_root=tmp_path,
            target="app.py",
            require_identity=True,
        )
    assert error.value.code == "MAPPER_CONTEXT_IDENTITY_REQUIRED"


def test_pipeline_rejects_target_escape_before_planning(tmp_path: Path) -> None:
    result = run_task(
        str(tmp_path),
        "python",
        "change app",
        "../escape.py",
        "- true",
        "- safe",
        mode="standalone",
    )

    assert result["status"] == "blocked"
    assert result["warnings"] == ["TARGET_OUTSIDE_SCOPE"]
    assert result["blocked_preconditions"][0]["code"] == "TARGET_OUTSIDE_SCOPE"
