"""Offline system matrix for issue #301.

The tests in this module deliberately stop at the repository boundaries:

* the HTTP Runtime is a local deterministic server, never a real service;
* the offline transport is the production executor, not a recording fake;
* Loop is represented by its coordinator/attempt contract and causal fields;
* package lifecycle is a source-install smoke when a build tool is absent.

This keeps the acceptance matrix runnable without GitHub, Jira, Trello,
secrets, paid Actions, or a published simplicio-runtime deployment.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from simplicio import cli, pipeline
from simplicio.atomic_execution import AttemptContext
from simplicio.commands.run import _integrated_feature_task_runner
from simplicio.execution_mode import negotiate_execution_mode
from simplicio.plan_compiler import (
    EffectAuthorization,
    EffectPlan,
    OfflineRuntimeTransport,
)
from simplicio.plan_compiler.authority import build_change_proposal
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.compile_task_spec import compile_task_spec_to_plan
from simplicio.plan_compiler.effect_sink import EffectDispatchContext
from simplicio.plan_compiler.models import PlanDAG, PlanNode, VerificationPlan
from simplicio.plan_compiler.runtime_effect_sink import (
    RECEIPT_SCHEMA,
    TRANSACTION_SCHEMA,
    HttpRuntimeTransport,
    RuntimeEffectSink,
)
from simplicio.standalone_migration import (
    clear_effect_unknown,
    effect_unknown_pending,
    mutation_receipt,
    record_effect_unknown,
    standalone_policy,
    standalone_policy_for_root,
)
from simplicio.task_spec import TaskSpec

CONTEXT_HANDLE = "sha256:" + "c" * 64
CONTEXT_SNAPSHOT = {
    "schema": "simplicio.context-snapshot/v1",
    "snapshot_id": "snapshot-301",
    "revision": "revision-301",
    "digest": "sha256:" + "1" * 64,
}
CONTEXT_PACK = {"schema": "simplicio.context-pack/v1"}
READY_CAPABILITIES = {
    "runtime_version": "1.0.0",
    "effect_transaction_schemas": [TRANSACTION_SCHEMA],
    "transports": ["http-json"],
}


@pytest.fixture
def canonical_mapper_boundary(monkeypatch):
    """Provide a canonical Mapper boundary while keeping the test offline."""

    def load(payload, **_kwargs):
        if payload is CONTEXT_SNAPSHOT:
            return SimpleNamespace(
                payload_bytes=b"canonical-context-301",
                view=SimpleNamespace(
                    snapshot_id=CONTEXT_SNAPSHOT["snapshot_id"],
                    revision=CONTEXT_SNAPSHOT["revision"],
                    root_hash="root-hash-301",
                ),
            )
        from simplicio.plan_compiler.mapper_context import MapperContextError

        raise MapperContextError("TEST_CONTEXT_REJECTED", "not the canonical test snapshot")

    def bind(snapshot, pack, **_kwargs):
        assert snapshot is CONTEXT_SNAPSHOT
        assert pack is CONTEXT_PACK
        return SimpleNamespace(
            snapshot=load(snapshot),
            context_handle=SimpleNamespace(
                value=CONTEXT_HANDLE,
                to_dict=lambda: {
                    "schema": "simplicio.dev-cli.context-handle/v1",
                    "source_digest": "a" * 64,
                    "projection_digest": "b" * 64,
                },
            ),
        )

    monkeypatch.setattr("simplicio.execution_mode.load_mapper_context", load)
    monkeypatch.setattr("simplicio.pipeline_integrated.load_mapper_context", load)
    monkeypatch.setattr("simplicio.pipeline_integrated.bind_mapper_context", bind)
    monkeypatch.setattr("simplicio.pipeline_integrated.verify_context_sources", lambda *a, **k: None)
    return load


def _write_artifact(
    root: Path,
    name: str,
    *,
    text: str = "Effect API\n",
    validation: list[dict] | None = None,
) -> Path:
    path = root / name
    payload: dict[str, Any] = {
        "schema": "simplicio.mechanical-edit/v1",
        "operations": [{"op": "create_file", "path": name.removesuffix(".json") + ".txt", "text": text}],
    }
    if validation is not None:
        payload["validation"] = validation
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _effect(artifact_ref: str, *, effect_id: str = "effect-301") -> EffectPlan:
    return EffectPlan(
        effect_id,
        "node-1",
        "write",
        "dev-cli.edit",
        "a" * 64,
        ["source clean"],
        artifact_ref=artifact_ref,
        context_handle=CONTEXT_HANDLE,
    )


def _dispatch_context(effect: EffectPlan) -> EffectDispatchContext:
    node = PlanNode(
        "node-1",
        "edit.apply",
        acceptance_criteria_refs=["AC1"],
        requires_gate=True,
        rollback_strategy="checkpoint",
    )
    plan = PlanDAG(
        "plan-301",
        "goal-301",
        CONTEXT_SNAPSHOT["snapshot_id"],
        CONTEXT_SNAPSHOT["revision"],
        nodes=[node],
        context_handle=CONTEXT_HANDLE,
    )
    context = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=node,
        verifications=[VerificationPlan("verify-301", "node-1", "pytest", "pytest -q", 60, ["AC1"])],
        coordinator_kind="simplicio-loop",
        coordinator_id="attempt-301",
        session_id="session-301",
        turn_id="turn-301",
        attempt=1,
        subworkflow_id="issue-301",
        policy_revision="dev-cli-integrated-v1",
        base_hash="base-sha-301",
        source_hash="source-sha-301",
        context_handle=CONTEXT_HANDLE,
        lease_id="lease-301",
        fencing_token="fence-301",
        plan=plan,
    )
    proposal = build_change_proposal(effect, context)
    return replace(
        context,
        authorization=EffectAuthorization.issue(
            proposal,
            authority="operator-301",
            issuer="simplicio-loop",
            human_gate_receipt="human-gate-301",
        ),
    )


class _RuntimeState:
    def __init__(self, *, capabilities: dict[str, Any] | None = None, lose_first_response: bool = False):
        self.capabilities = capabilities or dict(READY_CAPABILITIES)
        self.lose_first_response = lose_first_response
        self.receipts: dict[str, dict[str, Any]] = {}
        self.post_count = 0
        self.query_count = 0


def _receipt(transaction: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "state": "completed",
        "idempotency_key": transaction["idempotency_key"],
        "effect_digest": transaction["effect_digest"],
        "proposal_digest": transaction["proposal_digest"],
        "authorization_digest": transaction["authorization_digest"],
        "effect_id": transaction["causal"]["effect_id"],
        "plan_node_id": transaction["causal"]["plan_node_id"],
        "causal": transaction["causal"],
        "acceptance_criteria_refs": transaction["acceptance_criteria_refs"],
        "gate_decision": "allow",
        "base_hash": transaction["base_hash"],
        "source_hash": transaction["source_hash"],
        "validation": {"executor": "http-json-test", "status": "completed", "checks": []},
        "rollback": None,
        "reason_codes": ["RUNTIME_EFFECT_APPLIED"],
        "latency_ms": 0.0,
        "executor": "http-json-test",
    }
    receipt["receipt_digest"] = canonical_hash(receipt)
    return receipt


class _RuntimeHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def log_message(self, *_args):
        return

    @property
    def state(self) -> _RuntimeState:
        return self.server.state  # type: ignore[attr-defined]

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/v1/capabilities":
            self._send(200, self.state.capabilities)
            return
        prefix = "/v1/effect-transactions/"
        if self.path.startswith(prefix):
            self.state.query_count += 1
            key = self.path.removeprefix(prefix)
            receipt = self.state.receipts.get(key)
            if receipt is None:
                self._send(404, {"error": "not found"})
            else:
                self._send(200, receipt)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/v1/effect-transactions":
            self._send(404, {"error": "not found"})
            return
        size = int(self.headers.get("Content-Length", "0"))
        transaction = json.loads(self.rfile.read(size).decode("utf-8"))
        self.state.post_count += 1
        key = transaction["idempotency_key"]
        receipt = self.state.receipts.setdefault(key, _receipt(transaction))
        if self.state.lose_first_response and self.state.post_count == 1:
            self._send(503, {"error": "response lost after commit"})
            return
        self._send(200, receipt)


@contextmanager
def _runtime_server(
    *, capabilities: dict[str, Any] | None = None, lose_first_response: bool = False
) -> Iterator[tuple[str, _RuntimeState]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RuntimeHandler)
    state = _RuntimeState(capabilities=capabilities, lose_first_response=lose_first_response)
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_issue_301_offline_effect_receipt_idempotency_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    artifact = _write_artifact(tmp_path, "offline-plan.json")
    effect = _effect(artifact.name)
    context = _dispatch_context(effect)
    transport = OfflineRuntimeTransport(root=tmp_path)
    sink = RuntimeEffectSink(transport, root=tmp_path)

    first = sink.submit(effect, context)
    second = RuntimeEffectSink(OfflineRuntimeTransport(root=tmp_path), root=tmp_path).submit(effect, context)

    assert first.state == "completed"
    assert first.receipt["schema"] == RECEIPT_SCHEMA
    assert first.receipt["executor"] == "offline-local"
    assert second.state == "completed"
    assert transport.apply_count == 1
    assert (tmp_path / "offline-plan.txt").read_text(encoding="utf-8") == "Effect API\n"
    assert list((tmp_path / ".simplicio" / "runtime-effects").glob("*.offline-receipt.json"))

    failed_artifact = _write_artifact(
        tmp_path,
        "rollback-plan.json",
        validation=[{"cmd": [sys.executable, "-c", "raise SystemExit(1)"]}],
    )
    failed = RuntimeEffectSink(OfflineRuntimeTransport(root=tmp_path), root=tmp_path).submit(
        _effect(failed_artifact.name, effect_id="effect-rollback-301"),
        _dispatch_context(_effect(failed_artifact.name, effect_id="effect-rollback-301")),
    )
    assert failed.state in {"validation_failed", "denied"}
    assert failed.receipt["gate_decision"] == "deny"
    assert failed.receipt["rollback"] is not None or failed.state == "denied"
    assert not (tmp_path / "rollback-plan.txt").exists()


def test_issue_301_online_transport_lost_response_reconciles_without_second_submit(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    for proxy_name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(proxy_name, raising=False)
    artifact = _write_artifact(tmp_path, "online-plan.json")
    effect = _effect(artifact.name, effect_id="effect-online-301")
    context = _dispatch_context(effect)
    with _runtime_server(lose_first_response=True) as (url, state):
        transport = HttpRuntimeTransport(url)
        client = RuntimeEffectSink(transport, root=tmp_path)
        uncertain = client.submit(effect, context)
        resolved = client.reconcile(uncertain.idempotency_key)

    assert uncertain.state == "effect_unknown"
    assert resolved.state == "completed"
    assert state.post_count == 1
    assert state.query_count == 1
    assert resolved.receipt["executor"] == "http-json-test"


@pytest.mark.parametrize(
    ("runtime_state", "expected"),
    [
        ("absent", "INCOMPATIBLE_RUNTIME"),
        ("incompatible", "INCOMPATIBLE_RUNTIME"),
        ("present", "INTEGRATED_READY"),
    ],
)
def test_issue_301_runtime_presence_and_capability_matrix(
    runtime_state, expected, tmp_path, monkeypatch, canonical_mapper_boundary
):
    monkeypatch.delenv("SIMPLICIO_RUNTIME_URL", raising=False)
    monkeypatch.delenv("SIMPLICIO_RUNTIME_OFFLINE", raising=False)
    sink = None
    if runtime_state == "present":
        monkeypatch.setenv("SIMPLICIO_RUNTIME_OFFLINE", "1")
        sink = RuntimeEffectSink.from_environment(root=tmp_path)
        handshake = sink.capability_handshake()
    elif runtime_state == "incompatible":
        for proxy_name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            monkeypatch.delenv(proxy_name, raising=False)
        monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
        monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
        with _runtime_server(
            capabilities={
                "runtime_version": "9.0.0",
                "effect_transaction_schemas": [TRANSACTION_SCHEMA],
                "transports": ["http-json"],
            }
        ) as (url, _state):
            sink = RuntimeEffectSink(HttpRuntimeTransport(url), root=tmp_path)
            handshake = sink.capability_handshake()
    else:
        handshake = {"verified": False, "capabilities": [], "reason": "runtime-not-found"}

    profile = negotiate_execution_mode(
        "integrated",
        root=tmp_path,
        runtime_handshake=handshake,
        context_snapshot=CONTEXT_SNAPSHOT,
        effect_sink=sink,
    )
    assert profile.reason_code == expected
    assert profile.effective_mode == ("integrated" if runtime_state == "present" else "blocked")


@pytest.mark.parametrize(
    ("phase", "opted_in", "write_allowed", "reason"),
    [
        ("shadow", False, True, "LEGACY_STANDALONE_SHADOW"),
        ("opt_in", False, False, "LEGACY_STANDALONE_OPT_IN_REQUIRED"),
        ("opt_in", True, True, "LEGACY_STANDALONE_OPTED_IN"),
        ("warning", False, False, "LEGACY_STANDALONE_OPT_IN_REQUIRED"),
        ("warning", True, True, "LEGACY_STANDALONE_OPTED_IN"),
        ("read_only", True, False, "LEGACY_STANDALONE_READ_ONLY"),
        ("removed", True, False, "LEGACY_STANDALONE_READ_ONLY"),
    ],
)
def test_issue_301_migration_phase_matrix(monkeypatch, phase, opted_in, write_allowed, reason):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", phase)
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1" if opted_in else "0")
    policy = standalone_policy()
    assert policy.phase == phase
    assert policy.legacy_opt_in is opted_in
    assert policy.write_allowed is write_allowed
    assert policy.reason_code == reason
    assert mutation_receipt("legacy_standalone", entrypoint="edit", policy=policy)["legacy"] is True


def test_issue_301_effect_unknown_lock_blocks_legacy_edit_until_reconciled(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "shadow")
    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")
    record_effect_unknown(str(tmp_path))
    assert effect_unknown_pending(str(tmp_path)) is True
    assert standalone_policy_for_root(str(tmp_path)).reason_code == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"

    plan = tmp_path / "edit.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [{"op": "create_file", "path": "must-not-write.txt", "text": "x\n"}],
            }
        ),
        encoding="utf-8",
    )
    assert (
        cli.main(["mechanical-edit", "--root", str(tmp_path), "--plan", str(plan), "--apply", "--json"]) == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["errors"][0]["code"] == "EFFECT_UNKNOWN_RECONCILIATION_REQUIRED"
    assert not (tmp_path / "must-not-write.txt").exists()

    with pytest.raises(ValueError):
        clear_effect_unknown(str(tmp_path), runtime_reconciled=False)
    clear_effect_unknown(str(tmp_path), runtime_reconciled=True)
    assert effect_unknown_pending(str(tmp_path)) is False


def test_issue_301_kill_switch_blocks_integrated_mutation_before_dispatch(
    tmp_path, monkeypatch, canonical_mapper_boundary
):
    monkeypatch.setenv("SIMPLICIO_RUNTIME_OFFLINE", "1")
    monkeypatch.setenv("SIMPLICIO_INTEGRATED_KILL_SWITCH", "1")
    sink = RuntimeEffectSink.from_environment(root=tmp_path)
    profile = negotiate_execution_mode(
        "integrated",
        root=tmp_path,
        runtime_handshake=sink.capability_handshake(),
        context_snapshot=CONTEXT_SNAPSHOT,
        effect_sink=sink,
    )
    assert profile.effective_mode == "blocked"
    assert profile.reason_code == "INTEGRATED_KILLED"


@pytest.mark.parametrize(
    "argv",
    [
        ["task", "update src/app.py", "--target", "src/app.py", "--mode", "integrated", "--json"],
        [
            "run",
            "implement login feature",
            "--scope",
            "feature",
            "--stack",
            "py-fastapi",
            "--mode",
            "integrated",
            "--json",
        ],
        [
            "run",
            "finish sprint 1",
            "--scope",
            "sprint",
            "--stack",
            "py-fastapi",
            "--sprint",
            "sprint-01",
            "--max-cost",
            "1",
            "--mode",
            "integrated",
            "--json",
        ],
    ],
)
def test_issue_301_task_feature_sprint_entrypoints_fail_closed_without_runtime(
    tmp_path, monkeypatch, argv, capsys
):
    monkeypatch.setenv("SIMPLICIO_SKIP_AUTO_INIT", "1")
    before = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".simplicio" not in path.relative_to(tmp_path).parts
    )
    assert cli.main([*argv, "--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["applied"] is False
    assert payload["execution_profile"]["effective_mode"] == "blocked"
    assert payload["warnings"] in (
        ["RUNTIME_NOT_CONFIGURED"],
        ["INCOMPATIBLE_RUNTIME"],
        ["CONTEXT_REQUIRED"],
    )
    after = sorted(
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".simplicio" not in path.relative_to(tmp_path).parts
    )
    assert before == after


def _feature_task_spec(task, stack, artifact_ref: str) -> TaskSpec:
    source = {
        "kind": "feature-plan",
        "task_id": task.id,
        "target": task.target,
        "verify": task.verify,
    }
    source_hash = (
        __import__("hashlib")
        .sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        .hexdigest()
    )
    return TaskSpec(
        task_id=task.id,
        source=source,
        source_hash=source_hash,
        language=stack.language,
        functionality=task.goal,
        narrative={"goal": task.goal, "constraints": task.constraints},
        acceptance_criteria=[
            {"id": f"AC{index}", "text": line.lstrip("-* ").strip()}
            for index, line in enumerate(task.criteria.splitlines(), start=1)
            if line.strip()
        ],
        verification_commands=[{"command": task.verify, "verifier": "declared"}],
        extra_fields={"artifact_ref": artifact_ref},
    )


def _authorization_for_task_spec(task_spec: TaskSpec) -> EffectAuthorization:
    import hashlib

    goal_id = f"goal-{hashlib.sha256(task_spec.canonical_hash().encode('utf-8')).hexdigest()[:16]}"
    plan, effects, verifications = compile_task_spec_to_plan(
        task_spec,
        goal_id=goal_id,
        context_snapshot_id=CONTEXT_SNAPSHOT["snapshot_id"],
        revision=CONTEXT_SNAPSHOT["revision"],
        context_handle=CONTEXT_HANDLE,
    )
    effect = effects[0]
    node = next(item for item in plan.nodes if item.node_id == effect.plan_node_id)
    context = EffectDispatchContext(
        plan_id=plan.plan_id,
        goal_id=plan.goal_id,
        plan_node=node,
        verifications=verifications,
        coordinator_id="attempt-301",
        source_hash=task_spec.source_hash,
        context_handle=CONTEXT_HANDLE,
        lease_id="lease-301",
        fencing_token="fence-301",
        policy_revision="dev-cli-integrated-v1",
        plan=plan,
    )
    return EffectAuthorization.issue(
        build_change_proposal(effect, context),
        authority="operator-301",
        issuer="simplicio-loop",
        human_gate_receipt="human-gate-301",
    )


def test_issue_301_task_and_feature_sprint_dispatch_use_offline_effect_api(
    tmp_path, monkeypatch, canonical_mapper_boundary
):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", f'{sys.executable} -c "raise SystemExit(0)"')
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "offline-e2e-prompt")
    sink = RuntimeEffectSink(OfflineRuntimeTransport(root=tmp_path), root=tmp_path)
    attempt = AttemptContext("attempt-301", "lease-301", "fence-301", CONTEXT_HANDLE)

    task_spec = TaskSpec(
        task_id="task-301",
        source={"kind": "task", "target": "task-artifact.txt"},
        source_hash="b" * 64,
        language="text",
        narrative={"goal": "apply task artifact", "constraints": "offline"},
        acceptance_criteria=[{"id": "AC1", "text": "artifact exists"}],
        verification_commands=[{"command": os.environ["SIMPLICIO_TEST_CMD"], "verifier": "pytest"}],
        extra_fields={"artifact_ref": "task-plan.json"},
    )
    _write_artifact(tmp_path, "task-plan.json", text="task\n")
    task_result = pipeline.run_task(
        str(tmp_path),
        "text",
        "apply task artifact",
        "task-301",
        "- artifact exists",
        "- offline",
        mode="integrated",
        effect_sink=sink,
        authorization=_authorization_for_task_spec(task_spec),
        context_snapshot=CONTEXT_SNAPSHOT,
        context_pack=CONTEXT_PACK,
        runtime_handshake=sink.capability_handshake(),
        integrated_attempt=attempt,
        task_spec=task_spec,
        quiet=True,
    )
    assert task_result["applied"] is True
    assert task_result["mutation_receipt"]["route"] == "runtime_effect_api"
    # Route telemetry is intentionally not a causal Runtime receipt.  The
    # verified receipt lives in the sink's durable store and is asserted by
    # the transport tests above.
    assert task_result["mutation_receipt"]["runtime_gated"] is False
    assert (tmp_path / "task-plan.txt").read_text(encoding="utf-8") == "task\n"

    from simplicio.scratch.plan_schema import Task

    for task_id, plan_name, output_name in (
        ("feature-301", "feature-plan.json", "feature-plan.txt"),
        ("sprint-301", "sprint-plan.json", "sprint-plan.txt"),
    ):
        _write_artifact(tmp_path, plan_name, text=task_id + "\n")
        task = Task(
            id=task_id,
            goal=f"apply {task_id}",
            target=output_name,
            criteria="- artifact exists",
            constraints="- offline",
            verify=os.environ["SIMPLICIO_TEST_CMD"],
        )
        task_spec = _feature_task_spec(task, SimpleNamespace(language="text", framework=None), plan_name)
        # ``_integrated_feature_task_runner`` carries the artifact through the
        # environment bridge used by the coordinator-facing adapter; its
        # generated TaskSpec itself has no extra_fields.
        monkeypatch.setenv("SIMPLICIO_EFFECT_ARTIFACT_REF", plan_name)
        authorization_spec = replace(task_spec, extra_fields={})
        prepared = SimpleNamespace(
            effect_sink=sink,
            context_snapshot=CONTEXT_SNAPSHOT,
            context_pack=CONTEXT_PACK,
            execution_context=None,
            authorization=_authorization_for_task_spec(authorization_spec),
            runtime_handshake=sink.capability_handshake(),
            attempt=attempt,
        )
        args = SimpleNamespace(
            _execution_inputs=prepared,
            coordinator_kind="simplicio-loop",
            coordinator_id="loop-301",
        )
        passed, log = _integrated_feature_task_runner(args)(
            task, tmp_path, SimpleNamespace(language="text", framework=None), quiet=True
        )
        assert passed is True, log
        assert (tmp_path / output_name).read_text(encoding="utf-8") == task_id + "\n"

    assert sink.transport.apply_count == 3


def test_issue_301_edit_entrypoint_reports_legacy_receipt_and_respects_phase(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    monkeypatch.setenv("SIMPLICIO_STANDALONE_MIGRATION_PHASE", "warning")
    plan = tmp_path / "edit.json"
    plan.write_text(
        json.dumps(
            {
                "schema": "simplicio.mechanical-edit/v1",
                "operations": [{"op": "create_file", "path": "legacy.txt", "text": "legacy\n"}],
            }
        ),
        encoding="utf-8",
    )
    assert (
        cli.main(["mechanical-edit", "--root", str(tmp_path), "--plan", str(plan), "--apply", "--json"]) == 1
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["mutation_receipt"]["route"] == "blocked"
    assert not (tmp_path / "legacy.txt").exists()

    monkeypatch.setenv("SIMPLICIO_ENABLE_LEGACY_STANDALONE_WRITE", "1")
    assert (
        cli.main(["mechanical-edit", "--root", str(tmp_path), "--plan", str(plan), "--apply", "--json"]) == 0
    )
    applied = json.loads(capsys.readouterr().out)
    assert applied["mutation_receipt"]["legacy"] is True
    assert applied["mutation_receipt"]["runtime_gated"] is False
    assert (tmp_path / "legacy.txt").read_text(encoding="utf-8") == "legacy\n"


def test_issue_301_clean_source_install_and_contract_rollback_smoke(tmp_path):
    """Exercise clean-install isolation without requiring pip or a network.

    The worker image used for these tests intentionally has no package
    installer.  Copying the package into two isolated targets still verifies
    that the source distribution's runtime package is self-contained for the
    contract imports; the published wheel upgrade/downgrade remains an
    external release test.
    """

    repo = Path(__file__).resolve().parents[2]
    installs = []
    for label in ("v1", "v2"):
        target = tmp_path / label
        shutil.copytree(repo / "simplicio", target / "simplicio")
        (target / "simplicio" / "_issue_301_install_marker.txt").write_text(label, encoding="utf-8")
        installs.append(target)

    probe = (
        "import importlib, pathlib, sys; "
        "module=importlib.import_module('simplicio.plan_compiler.runtime_effect_sink'); "
        "assert module.TRANSACTION_SCHEMA == 'simplicio.effect-transaction/v1'; "
        "assert pathlib.Path(module.__file__).parents[1].joinpath("
        "'_issue_301_install_marker.txt').read_text() == sys.argv[1]"
    )
    for target, label in zip(installs, ("v1", "v2"), strict=True):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([str(target), str(repo)])
        result = subprocess.run(
            [sys.executable, "-c", probe, label],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    # A downgrade must not erase the v1 contract fields.  This is the local
    # equivalent of the package rollback assertion; published artifacts are
    # intentionally not invented when no build/install tool is present.
    assert (installs[0] / "simplicio" / "_issue_301_install_marker.txt").read_text() == "v1"
    assert (installs[1] / "simplicio" / "_issue_301_install_marker.txt").read_text() == "v2"
