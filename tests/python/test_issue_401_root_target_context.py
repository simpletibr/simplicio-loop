from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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


def test_from_dict_recomputes_and_rejects_tampered_context_hash(tmp_path: Path) -> None:
    context = TaskContext.from_values(
        repo_root=tmp_path,
        scope_root=tmp_path,
        target="app.py",
        context_snapshot_id="snapshot-401",
        context_pack_hash="pack-401",
        attempt_id="attempt-401",
        require_identity=True,
    )
    payload = context.to_dict()
    payload["context_hash"] = "0" * 64

    with pytest.raises(TaskContextError, match="CONTEXT_HASH_MISMATCH") as error:
        TaskContext.from_dict(payload)
    assert error.value.code == "CONTEXT_HASH_MISMATCH"


def test_pipeline_binds_declared_repo_root_to_actual_mutation_root(tmp_path: Path) -> None:
    result = run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- true",
        "- safe",
        mode="standalone",
        repo_root=tmp_path.parent,
    )

    assert result["status"] == "blocked"
    assert result["warnings"] == ["REPO_ROOT_MISMATCH"]


def test_pipeline_rejects_stale_supplied_mapper_identity(tmp_path: Path) -> None:
    result = run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- true",
        "- safe",
        mode="standalone",
        context_snapshot={"snapshot_id": "canonical-snapshot"},
        context_pack={"pack_hash": "canonical-pack"},
        context_snapshot_id="stale-snapshot",
        context_pack_hash="canonical-pack",
    )

    assert result["status"] == "blocked"
    assert result["warnings"] == ["CONTEXT_SNAPSHOT_ID_MISMATCH"]


def test_integrated_feature_runner_forwards_context_and_receipt(monkeypatch, tmp_path: Path) -> None:
    from simplicio.commands import run as run_command

    captured: dict[str, object] = {}

    def fake_run_task(*args, **kwargs):
        captured.update(kwargs)
        return {
            "applied": True,
            "mutation_authorization_receipt": {"context_hash": "context-401"},
        }

    monkeypatch.setattr("simplicio.pipeline.run_task", fake_run_task)
    prepared = SimpleNamespace(
        effect_sink=object(),
        context_snapshot={"snapshot_id": "snapshot-401"},
        context_pack={"pack_hash": "pack-401"},
        execution_context={"schema": "simplicio.execution-context/v1"},
        authorization=object(),
        runtime_handshake={"verified": True},
        attempt="attempt-401",
    )
    args = SimpleNamespace(
        _execution_inputs=prepared,
        coordinator_kind="loop",
        coordinator_id="worker-401",
        execution_context="execution.json",
        effect_authorization="authorization.json",
        attempt_id="attempt-401",
        lease_id="lease-401",
        fencing_token="fence-401",
        context_handle="handle-401",
        repo_root=str(tmp_path),
        scope_root=str(tmp_path),
        context_snapshot_id="snapshot-401",
        context_pack_hash="pack-401",
    )
    runner = run_command._integrated_feature_task_runner(args)
    task = SimpleNamespace(
        id="task-401",
        target="simplicio/pipeline.py",
        goal="repair route",
        verify="pytest -q",
        criteria="- receipt is returned",
        constraints="- bounded",
    )

    passed, log = runner(task, tmp_path, SimpleNamespace(language="python", framework=""))
    payload = json.loads(log)

    assert passed is True
    assert captured["context_snapshot"] == prepared.context_snapshot
    assert captured["context_pack"] == prepared.context_pack
    assert captured["authorization_path"] == "authorization.json"
    assert captured["attempt_id"] == "attempt-401"
    assert payload["mutation_authorization_receipt"]["context_hash"] == "context-401"
