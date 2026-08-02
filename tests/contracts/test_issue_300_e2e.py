"""End-to-end evidence for issue #300.

The first group of tests is a deterministic process-boundary harness: it uses
the real Dev CLI integrated pipeline, the real ContextSnapshot/ContextPack
adapter, and the real ``OfflineRuntimeTransport``. The Loop and Mapper sides
are represented by the public JSON contracts, so the test never calls a real
LLM or invents a second execution path.

The installed cross-repository test is intentionally skipped unless the
operator supplies the external stack. A local harness is useful evidence,
but it is not evidence that independently installed Loop, Mapper, and Runtime
packages interoperate.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from simplicio import pipeline
from simplicio.atomic_execution import AttemptContext
from simplicio.plan_compiler import (
    EffectAuthorization,
    EffectPlan,
    GoalEnvelope,
    OfflineRuntimeTransport,
    PlanDAG,
    PlanNode,
    build_change_proposal,
    compile_task_spec_to_plan,
)
from simplicio.plan_compiler.compat_adapter import (
    CompatAdapterError,
    UnsupportedCompatVersionError,
    adapt_goal_envelope_outbound,
    adapt_outbound,
)
from simplicio.plan_compiler.effect_sink import EffectDispatchContext, RecordingEffectSink
from simplicio.plan_compiler.mapper_context import (
    MAPPER_CONTEXT_PACK_SCHEMA,
    MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
    ContextBinding,
    ContextBindingCache,
    bind_mapper_context,
)
from simplicio.plan_compiler.runtime_effect_sink import RuntimeEffectSink
from simplicio.task_spec import TaskSpec


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.fixture
def mapper_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the pinned Mapper boundary without importing an unpublished wheel."""

    from simplicio.plan_compiler import mapper_context

    monkeypatch.setattr(
        mapper_context,
        "_read_manifest",
        lambda: MappingProxyType({"owner": "wesleysimplicio/simplicio-mapper"}),
    )

    def validate(payload: Any, **_kwargs: Any) -> dict[str, Any]:
        if (
            isinstance(payload, dict)
            and payload.get("schema") == MAPPER_CONTEXT_SNAPSHOT_SCHEMA
            and payload.get("schema_version") == "v1"
            and payload.get("root_hash") == "root-hash"
        ):
            return {"valid": True, "reason_codes": []}
        return {"valid": False, "reason_codes": [{"code": "UNSUPPORTED_SCHEMA", "path": "$.schema"}]}

    monkeypatch.setattr(mapper_context, "_mapper_api", lambda: (validate, _canonical))


def _snapshot(*, revision: str = "rev-1", root_hash: str = "root-hash") -> dict[str, Any]:
    return {
        "schema": MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
        "schema_version": "v1",
        "snapshot_id": "snapshot-300",
        "revision": revision,
        "root_hash": root_hash,
        "producer": {"name": "simplicio-mapper", "version": "0.24.1"},
        "freshness": {"graph_hash": "graph-hash", "root_hash": root_hash},
        "fidelity": {"gate": "ready", "status": "complete"},
        "graph": {
            "nodes": [{"source": {"file": "src/app.py", "line": 1}}],
            "edges": [],
        },
        "source_set": ["src/app.py"],
        "needs_broader_context": False,
    }


def _pack(snapshot: dict[str, Any], root: Path, **overrides: Any) -> dict[str, Any]:
    source = root / "src/app.py"
    payload = {
        "schema": MAPPER_CONTEXT_PACK_SCHEMA,
        "pack_hash": "a" * 64,
        "source_snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "revision": snapshot["revision"],
            "source_digest": hashlib.sha256(_canonical(snapshot)).hexdigest(),
            "root_hash": snapshot["root_hash"],
        },
        "files": [
            {
                "path": "src/app.py",
                "snapshot_hash": hashlib.sha256(source.read_bytes()).hexdigest(),
                "selectors": ["module"],
            }
        ],
        "fidelity": {"gate": "ready", "status": "sufficient"},
        "needs_broader_context": False,
        "serialization_budget": {"token_budget": 200, "estimated_tokens": 12},
    }
    payload.update(overrides)
    return payload


def _task_spec(*, artifact_ref: str = "offline-plan.json") -> TaskSpec:
    return TaskSpec(
        task_id="issue-300",
        source={"kind": "loop", "id": "loop-task-300"},
        source_hash=hashlib.sha256(b"issue-300-task").hexdigest(),
        language="python",
        narrative={"goal": "aplicar alteração autorizada"},
        acceptance_criteria=[{"id": "AC1", "text": "o efeito deve ser verificável"}],
        verification_commands=[{"command": "pytest -q", "verifier": "pytest"}],
        original_text="Adicionar uma alteração determinística\n",
        extra_fields={"artifact_ref": artifact_ref},
    )


def _write_artifact(root: Path, *, validation: list[dict[str, Any]] | None = None) -> None:
    plan = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [
            {"op": "create_file", "path": "generated-by-runtime.txt", "text": "Runtime receipt\n"}
        ],
    }
    if validation is not None:
        plan["validation"] = validation
    (root / "offline-plan.json").write_text(json.dumps(plan), encoding="utf-8")


def _limited_llm_prompt(pack: dict[str, Any]) -> str:
    """The Loop-facing projection contains only the bounded ContextPack."""

    projection = {
        key: pack[key]
        for key in ("schema", "pack_hash", "files", "fidelity", "serialization_budget")
        if key in pack
    }
    return "LOOP_CONTEXT_PACK=" + json.dumps(projection, sort_keys=True, separators=(",", ":"))


def _attempt(handle: str) -> AttemptContext:
    return AttemptContext("attempt-300", "lease-300", "fence-300", handle)


def _authorized_bundle(
    binding: ContextBinding,
    task_spec: TaskSpec,
    attempt: AttemptContext,
    *,
    coordinator_kind: str = "simplicio-loop",
    session_id: str = "session-300",
    turn_id: str = "turn-300",
    subworkflow_id: str = "issue-300",
    policy_revision: str = "issue-300-e2e-v1",
    base_hash: str = "base-300",
) -> tuple[PlanDAG, EffectPlan, EffectDispatchContext, EffectAuthorization]:
    goal_id = f"goal-{hashlib.sha256(task_spec.canonical_hash().encode()).hexdigest()[:16]}"
    plan, effects, verifications = compile_task_spec_to_plan(
        task_spec,
        goal_id=goal_id,
        context_snapshot_id=binding.snapshot.view.snapshot_id,
        revision=binding.snapshot.view.revision,
        context_handle=binding.context_handle.value,
    )
    effect = effects[0]
    effect_node = next(node for node in plan.nodes if node.node_id == effect.plan_node_id)
    context = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=effect_node,
        verifications=verifications,
        coordinator_kind=coordinator_kind,
        coordinator_id=attempt.attempt_id,
        session_id=session_id,
        turn_id=turn_id,
        attempt=1,
        subworkflow_id=subworkflow_id,
        policy_revision=policy_revision,
        base_hash=base_hash,
        source_hash=task_spec.source_hash,
        context_handle=attempt.context_handle,
        lease_id=attempt.lease_id,
        fencing_token=attempt.fencing_token,
        plan=plan,
    )
    proposal = build_change_proposal(effect, context)
    authorization = EffectAuthorization.issue(
        proposal,
        authority="loop-operator-300",
        issuer="simplicio-loop",
        human_gate_receipt="human-gate-300",
    )
    return plan, effect, context, authorization


def _run_integrated(
    root: Path,
    snapshot: dict[str, Any],
    pack: dict[str, Any],
    *,
    sink: Any,
    attempt: AttemptContext,
    authorization: EffectAuthorization | None = None,
    task_spec: TaskSpec | None = None,
    context_refresh: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    from simplicio.pipeline_integrated import run_integrated

    task_spec = task_spec or _task_spec()
    return run_integrated(
        str(root),
        "python",
        "aplicar alteração autorizada",
        "src/app.py",
        "- o efeito deve ser verificável",
        "- manter a árvore dentro do root",
        _limited_llm_prompt(pack),
        "pytest -q",
        sink,
        authorization=authorization,
        context_snapshot=snapshot,
        context_pack=pack,
        context_refresh=context_refresh,
        attempt=attempt,
        task_spec=task_spec,
        **kwargs,
    )


def test_loop_mapper_dev_cli_runtime_receipt_is_one_causal_flow(
    tmp_path: Path, mapper_boundary: None
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('before')\n", encoding="utf-8")
    _write_artifact(tmp_path)
    snapshot = _snapshot()
    pack = _pack(snapshot, tmp_path)
    binding = bind_mapper_context(snapshot, pack, source_root=str(tmp_path))
    attempt = _attempt(binding.context_handle.value)
    task_spec = _task_spec()
    _, _, _, authorization = _authorized_bundle(binding, task_spec, attempt)
    prompt = _limited_llm_prompt(pack)
    sink = RuntimeEffectSink(OfflineRuntimeTransport(root=tmp_path), root=tmp_path)

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "aplicar alteração autorizada",
        "src/app.py",
        "- o efeito deve ser verificável",
        "- manter a árvore dentro do root",
        mode="integrated",
        effect_sink=sink,
        authorization=authorization,
        context_snapshot=snapshot,
        context_pack=pack,
        context_refresh=True,
        runtime_handshake=sink.capability_handshake(),
        coordinator_kind="simplicio-loop",
        integrated_attempt=attempt,
        task_spec=task_spec,
        session_id="session-300",
        turn_id="turn-300",
        attempt_number=1,
        subworkflow_id="issue-300",
        policy_revision="issue-300-e2e-v1",
        base_hash="base-300",
        quiet=True,
    )

    assert result["status"] == "integrated_atomic"
    assert result["observation"]["outcome"] == "effect_submitted"
    handle = binding.context_handle.value
    assert result["context_binding"]["context_handle"] == handle
    assert result["plan"]["context_handle"] == handle
    assert result["effects"][0]["context_handle"] == handle
    assert result["observation"]["context_handle"] == handle
    assert result["context_binding"]["cache"]["reason"] == "explicit_refresh"
    assert result["context_binding"]["cache"]["hit"] is False
    assert "graph" not in prompt
    assert "LOOP_CONTEXT_PACK=" in prompt
    assert "api_key" not in json.dumps(result, sort_keys=True).lower()
    assert (tmp_path / "generated-by-runtime.txt").read_text(encoding="utf-8") == "Runtime receipt\n"

    runtime_dir = tmp_path / ".simplicio/runtime-effects"
    intent = next(runtime_dir.glob("*.intent.json"))
    receipt = next(runtime_dir.glob("*.receipt.json"))
    transaction = json.loads(intent.read_text(encoding="utf-8"))
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert transaction["causal"]["context_handle"] == handle
    assert transaction["causal"]["coordinator_id"] == attempt.attempt_id
    assert receipt_payload["causal"] == transaction["causal"]
    assert receipt_payload["state"] == "completed"
    assert receipt_payload["receipt_digest"]


def test_context_binding_cache_is_visible_to_a_second_process(tmp_path: Path, mapper_boundary: None) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('cache')\n", encoding="utf-8")
    snapshot = _snapshot()
    pack = _pack(snapshot, tmp_path)
    binding = bind_mapper_context(snapshot, pack, source_root=str(tmp_path))
    cache = ContextBindingCache(tmp_path)
    cache.put(binding)
    identity = tmp_path / "context-handle.json"
    identity.write_text(json.dumps(binding.context_handle.to_dict()), encoding="utf-8")
    repo_root = Path(__file__).resolve().parents[2]
    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(repo_root), child_env.get("PYTHONPATH", "")) if item
    )
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; from pathlib import Path; "
                "from simplicio.plan_compiler.mapper_context import ContextBindingCache, ContextHandle; "
                "raw=json.loads(Path(sys.argv[2]).read_text()); "
                "fields={k:v for k,v in raw.items() if k != 'schema'}; "
                "print(json.dumps(ContextBindingCache(sys.argv[1]).lookup(ContextHandle(**fields))))"
            ),
            str(tmp_path),
            str(identity),
        ],
        cwd=repo_root,
        env=child_env,
        stdin=subprocess.DEVNULL,
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(child.stdout)
    assert observed["hit"] is True
    assert observed["reason"] == "exact_digest"
    assert "payload" not in observed
    assert "source_digest" in observed["identity"]


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        ("tampered_hash", lambda pack: pack.update(pack_hash="short"), "INCOMPATIBLE_CONTEXT"),
        (
            "wrong_snapshot",
            lambda pack: pack["source_snapshot"].update(snapshot_id="other"),
            "INCOMPATIBLE_CONTEXT",
        ),
        (
            "wrong_revision",
            lambda pack: pack["source_snapshot"].update(revision="rev-old"),
            "INCOMPATIBLE_CONTEXT",
        ),
        (
            "wrong_root",
            lambda pack: pack["source_snapshot"].update(root_hash="other-root"),
            "INCOMPATIBLE_CONTEXT",
        ),
        ("truncated_projection", lambda pack: pack.pop("fidelity"), "INCOMPATIBLE_CONTEXT"),
        (
            "sensitive_value_field",
            lambda pack: pack.update(api_key="must-not-cross-boundary"),
            "INCOMPATIBLE_CONTEXT",
        ),
        (
            "budget_exceeded",
            lambda pack: pack.update(serialization_budget={"token_budget": 1, "estimated_tokens": 2}),
            "INCOMPATIBLE_CONTEXT",
        ),
        (
            "insufficient_fidelity",
            lambda pack: pack.update(needs_broader_context=True),
            "INCOMPATIBLE_CONTEXT",
        ),
        (
            "root_path_escape",
            lambda pack: pack.update(files=[{"path": "../outside.py", "snapshot_hash": "b" * 64}]),
            "CONTEXT_ROOT_PATH_MISMATCH",
        ),
    ],
)
def test_context_contract_failure_is_before_runtime_effect(
    tmp_path: Path,
    mapper_boundary: None,
    name: str,
    mutate: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('safe')\n", encoding="utf-8")
    snapshot = _snapshot()
    valid_pack = _pack(snapshot, tmp_path)
    binding = bind_mapper_context(snapshot, valid_pack, source_root=str(tmp_path))
    pack = json.loads(json.dumps(valid_pack))
    mutate(pack)
    sink = RecordingEffectSink(state="completed")

    result = _run_integrated(
        tmp_path,
        snapshot,
        pack,
        sink=sink,
        attempt=_attempt(binding.context_handle.value),
    )

    assert result["status"] == "blocked", name
    assert result["warnings"] == [expected], name
    assert sink.received == [], name


def test_source_drift_and_attempt_handle_mismatch_are_before_runtime_effect(
    tmp_path: Path, mapper_boundary: None
) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/app.py"
    source.write_text("print('one')\n", encoding="utf-8")
    snapshot = _snapshot()
    pack = _pack(snapshot, tmp_path)
    binding = bind_mapper_context(snapshot, pack, source_root=str(tmp_path))
    sink = RecordingEffectSink(state="completed")

    source.write_text("print('drifted')\n", encoding="utf-8")
    drifted = _run_integrated(
        tmp_path,
        snapshot,
        pack,
        sink=sink,
        attempt=_attempt(binding.context_handle.value),
    )
    assert drifted["warnings"] == ["SOURCE_DRIFT"]
    assert sink.received == []

    source.write_text("print('one')\n", encoding="utf-8")
    mismatch = _run_integrated(
        tmp_path,
        snapshot,
        pack,
        sink=sink,
        attempt=_attempt("sha256:" + "0" * 64),
    )
    assert mismatch["warnings"] == ["CONTEXT_HANDLE_MISMATCH"]
    assert sink.received == []


def test_effect_unknown_reconciles_and_validation_failure_rolls_back(
    tmp_path: Path, mapper_boundary: None
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('recovery')\n", encoding="utf-8")
    snapshot = _snapshot()
    pack = _pack(snapshot, tmp_path)
    binding = bind_mapper_context(snapshot, pack, source_root=str(tmp_path))
    task_spec = _task_spec()
    attempt = _attempt(binding.context_handle.value)
    _, effect, context, authorization = _authorized_bundle(binding, task_spec, attempt)
    _write_artifact(tmp_path)
    uncertain_sink = RuntimeEffectSink(
        OfflineRuntimeTransport(root=tmp_path, failure="after_apply"), root=tmp_path
    )

    uncertain = uncertain_sink.submit(effect, replace(context, authorization=authorization))
    assert uncertain.state == "effect_unknown"
    assert (tmp_path / "generated-by-runtime.txt").is_file()

    reconciled_transport = OfflineRuntimeTransport(root=tmp_path)
    reconciled = RuntimeEffectSink(reconciled_transport, root=tmp_path).submit(
        effect, replace(context, authorization=authorization)
    )
    assert reconciled.state == "completed"
    assert reconciled_transport.apply_count == 0
    assert reconciled.receipt["causal"]["context_handle"] == binding.context_handle.value

    rollback_root = tmp_path / "rollback"
    (rollback_root / "src").mkdir(parents=True)
    (rollback_root / "src/app.py").write_text("print('rollback')\n", encoding="utf-8")
    rollback_snapshot = _snapshot()
    rollback_snapshot["snapshot_id"] = "snapshot-rollback"
    rollback_pack = _pack(rollback_snapshot, rollback_root)
    rollback_binding = bind_mapper_context(rollback_snapshot, rollback_pack, source_root=str(rollback_root))
    rollback_task = _task_spec()
    rollback_attempt = _attempt(rollback_binding.context_handle.value)
    _, rollback_effect, rollback_context, rollback_authorization = _authorized_bundle(
        rollback_binding, rollback_task, rollback_attempt
    )
    _write_artifact(
        rollback_root,
        validation=[{"cmd": [sys.executable, "-c", "raise SystemExit(1)"]}],
    )
    rollback_outcome = RuntimeEffectSink(
        OfflineRuntimeTransport(root=rollback_root), root=rollback_root
    ).submit(rollback_effect, replace(rollback_context, authorization=rollback_authorization))
    assert rollback_outcome.state == "validation_failed"
    assert rollback_outcome.rollback == {"status": "restored", "performed": True}
    assert not (rollback_root / "generated-by-runtime.txt").exists()


def test_n_minus_one_boundary_refuses_digest_bound_context_and_older_versions() -> None:
    goal = GoalEnvelope(
        "goal-300",
        "rev-1",
        "snapshot-300",
        "apply",
        context_handle="sha256:" + "c" * 64,
    )
    with pytest.raises(CompatAdapterError, match="context_handle"):
        adapt_goal_envelope_outbound(goal, 0)

    plan = PlanDAG(
        "plan-300",
        "goal-300",
        "snapshot-300",
        "rev-1",
        nodes=[PlanNode("edit", "edit.apply")],
        context_handle=goal.context_handle,
    )
    with pytest.raises(CompatAdapterError, match="context_handle"):
        adapt_outbound(plan, 1)
    with pytest.raises(UnsupportedCompatVersionError):
        adapt_outbound(plan, 0)


def test_real_installed_issue_300_stack_is_not_claimed_without_external_evidence() -> None:
    if os.environ.get("SIMPLICIO_ISSUE_300_REAL_E2E", "").lower() in {"1", "true", "yes"}:
        required = ["simplicio-loop", "simplicio-mapper", "simplicio-dev-cli", "simplicio"]
        missing = [name for name in required if shutil.which(name) is None]
        if not missing and os.environ.get("SIMPLICIO_RUNTIME_URL", "").strip():
            pytest.fail(
                "UNVERIFIED: the installed Loop/Mapper/Runtime protocol runner must be configured "
                "before this gate can be promoted to a live assertion"
            )
    pytest.skip(
        "UNVERIFIED: installed simplicio-loop + simplicio-mapper + simplicio-runtime "
        "cross-repository receipt runner is not configured"
    )
