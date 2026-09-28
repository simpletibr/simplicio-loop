from __future__ import annotations

import json
from dataclasses import replace

import pytest

from simplicio.plan_compiler import (
    EffectAuthorization,
    EffectPlan,
    PlanDAG,
    PlanNode,
    VerificationPlan,
    build_change_proposal,
)
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.effect_sink import EffectDispatchContext
from simplicio.plan_compiler.runtime_effect_sink import (
    RECEIPT_SCHEMA,
    TRANSACTION_SCHEMA,
    HttpRuntimeTransport,
    IntegratedModeRequiresSinkError,
    OfflineRuntimeTransport,
    RuntimeEffectError,
    RuntimeEffectSink,
    _contains_sensitive_key,
    _safe_write_set,
)


class FakeTransport:
    name = "http-json"

    def __init__(self, *, state="completed", failure=None):
        self.state = state
        self.failure = failure
        self.submitted = []
        self.queries = 0
        self.receipt = None

    def capabilities(self):
        return {
            "runtime_version": "1.4.0",
            "effect_transaction_schemas": [TRANSACTION_SCHEMA],
            "transports": [self.name],
        }

    def _make_receipt(self, transaction):
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "state": self.state,
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
            "validation": {"state": "passed"},
            "rollback": None,
            "reason_codes": [],
            "latency_ms": 1.25,
        }
        receipt["receipt_digest"] = canonical_hash(receipt)
        return receipt

    def submit(self, transaction):
        self.submitted.append(transaction)
        if self.failure:
            raise RuntimeEffectError(self.failure, "injected")
        self.receipt = self._make_receipt(transaction)
        return self.receipt

    def query(self, key):
        self.queries += 1
        if self.failure:
            raise RuntimeEffectError(self.failure, "injected")
        assert self.receipt and self.receipt["idempotency_key"] == key
        return self.receipt


@pytest.fixture
def effect():
    return EffectPlan(
        "effect-1", "node-1", "write", "runtime", "legacy-key", ["source clean"], context_handle="ctx-1"
    )


@pytest.fixture
def context(effect):
    node = PlanNode(
        "node-1",
        "edit.apply",
        read_set=["src/a.py"],
        write_set=["src/a.py"],
        risk="medium",
        acceptance_criteria_refs=["AC1"],
        requires_gate=True,
        rollback_strategy="checkpoint",
    )
    verification = VerificationPlan(
        "verify-1", "node-1", "pytest", "pytest -q", 60, acceptance_criteria_refs=["AC1"]
    )
    context = EffectDispatchContext(
        "plan-1",
        "goal-1",
        node,
        [verification],
        coordinator_kind="agent",
        coordinator_id="coordinator-1",
        session_id="session-1",
        turn_id="turn-1",
        attempt=2,
        subworkflow_id="sub-1",
        policy_revision="policy-7",
        base_hash="base-sha",
        source_hash="source-sha",
        context_handle="ctx-1",
        lease_id="lease-1",
        fencing_token="fence-1",
        plan=PlanDAG(
            "plan-1",
            "goal-1",
            "snapshot-1",
            "revision-1",
            nodes=[node],
            context_handle="ctx-1",
        ),
    )
    proposal = build_change_proposal(effect, context)
    return replace(
        context,
        authorization=EffectAuthorization.issue(
            proposal,
            authority="operator-1",
            issuer="simplicio-loop",
            human_gate_receipt="human-gate-1",
        ),
    )


def _reauthorize(effect, context):
    proposal = build_change_proposal(effect, context)
    return replace(
        context,
        authorization=EffectAuthorization.issue(
            proposal,
            authority="operator-1",
            issuer="simplicio-loop",
            human_gate_receipt="human-gate-1",
        ),
    )


def test_maps_full_transaction_and_verifies_completed_receipt(tmp_path, effect, context):
    transport = FakeTransport()
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    transaction = transport.submitted[0]
    assert outcome.state == "completed" and outcome.terminal
    assert transaction["causal"] == {
        "coordinator_kind": "agent",
        "coordinator_id": "coordinator-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "attempt": 2,
        "subworkflow_id": "sub-1",
        "plan_id": "plan-1",
        "goal_id": "goal-1",
        "plan_node_id": "node-1",
        "effect_id": "effect-1",
        "context_handle": "ctx-1",
    }
    assert transaction["write_set"] == ["src/a.py"]
    assert transaction["plan"] == context.plan.to_dict()
    assert transaction["plan_digest"] == context.plan.canonical_hash()
    assert transaction["acceptance_criteria_refs"] == ["AC1"]
    assert transaction["validation_plan"][0]["verification_id"] == "verify-1"
    assert transaction["rollback_policy"] == "checkpoint"
    assert list((tmp_path / ".simplicio-loop/runtime-effects").glob("*.receipt.json"))


def test_plan_provenance_mismatch_is_rejected_before_transport(tmp_path, effect, context):
    transport = FakeTransport()
    invalid_plan = PlanDAG(
        "plan-1",
        "other-goal",
        "snapshot-1",
        "revision-1",
        nodes=[context.plan_node],
        context_handle="ctx-1",
    )

    with pytest.raises(RuntimeEffectError, match="PLAN_CONTEXT_MISMATCH"):
        RuntimeEffectSink(transport, root=tmp_path).submit(effect, replace(context, plan=invalid_plan))

    assert transport.submitted == []


def test_missing_authorization_is_rejected_before_transport(tmp_path, effect, context):
    transport = FakeTransport()

    with pytest.raises(RuntimeEffectError, match="EFFECT_AUTHORIZATION_REQUIRED"):
        RuntimeEffectSink(transport, root=tmp_path).submit(effect, replace(context, authorization=None))

    assert transport.submitted == []
    assert not (tmp_path / ".simplicio-loop/runtime-effects").exists()


def test_authorization_binds_effect_and_fence_before_transport(tmp_path, effect, context):
    transport = FakeTransport()
    forged = replace(
        context.authorization,
        fencing_token="fence-forged",
        authorization_digest=context.authorization.authorization_digest,
    )

    with pytest.raises(
        RuntimeEffectError, match="AUTHORIZATION_BINDING_MISMATCH|AUTHORIZATION_DIGEST_INVALID"
    ):
        RuntimeEffectSink(transport, root=tmp_path).submit(effect, replace(context, authorization=forged))

    assert transport.submitted == []


def test_capability_handshake_reports_the_versioned_effect_contract(tmp_path):
    sink = RuntimeEffectSink(FakeTransport(), root=tmp_path)

    handshake = sink.capability_handshake()

    assert handshake == {
        "verified": True,
        "version": "1.4.0",
        "capabilities": [TRANSACTION_SCHEMA],
        "reason": "ok",
        "transport": "http-json",
    }


def test_capability_handshake_fails_closed_without_raising(tmp_path):
    transport = FakeTransport()
    transport.capabilities = lambda: {
        "runtime_version": "2.0.0",
        "effect_transaction_schemas": [TRANSACTION_SCHEMA],
        "transports": [transport.name],
    }

    handshake = RuntimeEffectSink(transport, root=tmp_path).capability_handshake()

    assert handshake["verified"] is False
    assert handshake["reason"] == "RUNTIME_VERSION_INCOMPATIBLE"
    assert handshake["capabilities"] == []


@pytest.mark.parametrize(
    "capabilities",
    [
        None,
        {"runtime_version": "1.4.0", "effect_transaction_schemas": None, "transports": ["http-json"]},
        {
            "runtime_version": "1.4.0",
            "effect_transaction_schemas": [TRANSACTION_SCHEMA],
            "transports": None,
        },
    ],
)
def test_capability_handshake_fails_closed_for_malformed_external_shapes(tmp_path, capabilities):
    class MalformedTransport(FakeTransport):
        def capabilities(self):
            return capabilities

    handshake = RuntimeEffectSink(MalformedTransport(), root=tmp_path).capability_handshake()

    assert handshake["verified"] is False
    assert handshake["reason"] == "RUNTIME_CAPABILITY_INVALID"


def test_context_handle_crosses_transaction_and_verified_receipt(tmp_path, effect, context):
    context = replace(context, context_handle="sha256:" + "c" * 64)
    effect = replace(effect, context_handle=context.context_handle)
    context = replace(context, plan=replace(context.plan, context_handle=context.context_handle))
    context = _reauthorize(effect, context)
    transport = FakeTransport()

    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    assert transport.submitted[0]["causal"]["context_handle"] == context.context_handle
    assert transport.submitted[0]["effect"]["context_handle"] == context.context_handle
    assert outcome.receipt is not None
    assert outcome.receipt["causal"]["context_handle"] == context.context_handle


def test_runtime_rejects_context_handle_mismatch_before_persist_or_submit(tmp_path, effect, context):
    transport = FakeTransport()
    context = replace(context, context_handle="sha256:" + "c" * 64)
    with pytest.raises(RuntimeEffectError, match="CONTEXT_HANDLE_MISMATCH"):
        RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert transport.submitted == []
    assert not (tmp_path / ".simplicio-loop").exists()


@pytest.mark.parametrize(
    "state",
    ["denied", "running", "validation_failed", "rolled_back", "blocked_conflict", "cancelled_safe"],
)
def test_preserves_all_runtime_states(tmp_path, effect, context, state):
    outcome = RuntimeEffectSink(FakeTransport(state=state), root=tmp_path / state).submit(effect, context)
    assert outcome.state == state
    assert outcome.validation == {"state": "passed"}


def test_lost_response_is_unknown_and_never_retried(tmp_path, effect, context):
    transport = FakeTransport(failure="RUNTIME_TRANSPORT_ERROR")
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert outcome.state == "effect_unknown"
    assert len(transport.submitted) == 1
    assert transport.queries == 0


def test_capability_transport_failure_is_not_started_before_admission(tmp_path, effect, context):
    transport = FakeTransport()
    transport.capabilities = lambda: (_ for _ in ()).throw(
        RuntimeEffectError("RUNTIME_TRANSPORT_ERROR", "offline")
    )

    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    assert outcome.state == "not_started"
    assert outcome.reason_codes == ["RUNTIME_TRANSPORT_ERROR"]
    assert transport.submitted == []
    assert next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.outcome.json"))


def test_replay_reconciles_without_duplicate_submit(tmp_path, effect, context):
    transport = FakeTransport()
    sink = RuntimeEffectSink(transport, root=tmp_path)
    first = sink.submit(effect, context)
    second = sink.submit(effect, context)
    assert first.idempotency_key == second.idempotency_key
    assert len(transport.submitted) == 1
    assert transport.queries == 1


def test_restart_reconciles_durable_intent(tmp_path, effect, context):
    transport = FakeTransport()
    first = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    second = RuntimeEffectSink(transport, root=tmp_path).reconcile(first.idempotency_key)
    assert second.state == "completed"


@pytest.mark.parametrize("field", ["effect_id", "plan_node_id", "idempotency_key", "effect_digest"])
def test_forged_correlation_is_rejected(tmp_path, effect, context, field):
    transport = FakeTransport()
    original = transport._make_receipt

    def forged(transaction):
        receipt = original(transaction)
        receipt[field] = "forged"
        receipt["receipt_digest"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "receipt_digest"}
        )
        return receipt

    transport._make_receipt = forged
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RECEIPT_CORRELATION_MISMATCH"]
    assert not list((tmp_path / ".simplicio-loop/runtime-effects").glob("*.receipt.json"))


def test_tampered_receipt_digest_is_rejected(tmp_path, effect, context):
    transport = FakeTransport()
    original = transport._make_receipt

    def tampered(transaction):
        receipt = original(transaction)
        receipt["gate_decision"] = "deny"
        return receipt

    transport._make_receipt = tampered
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RECEIPT_DIGEST_INVALID"]


def test_non_object_receipt_is_durable_unknown(tmp_path, effect, context):
    transport = FakeTransport()
    transport._make_receipt = lambda _transaction: []

    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RUNTIME_RESPONSE_INVALID"]


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("coordinator_kind", "runtime"),
        ("coordinator_id", "attacker"),
        ("session_id", "other-session"),
        ("turn_id", "other-turn"),
        ("attempt", 999),
        ("subworkflow_id", "other-subworkflow"),
        ("plan_id", "other-plan"),
        ("goal_id", "other-goal"),
    ],
)
def test_forged_causal_identity_is_rejected(tmp_path, effect, context, field, forged):
    transport = FakeTransport()
    original = transport._make_receipt

    def forged_receipt(transaction):
        receipt = original(transaction)
        receipt["causal"] = {**receipt["causal"], field: forged}
        receipt["receipt_digest"] = canonical_hash(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        return receipt

    transport._make_receipt = forged_receipt
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RECEIPT_CORRELATION_MISMATCH"]


def test_incompatible_capability_fails_closed(tmp_path, effect, context):
    transport = FakeTransport()
    transport.capabilities = lambda: {
        "runtime_version": "2.0",
        "effect_transaction_schemas": [],
        "transports": [],
    }
    with pytest.raises(RuntimeEffectError, match="RUNTIME_CAPABILITY_INCOMPATIBLE"):
        RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)


def test_same_key_different_digest_fails_closed(tmp_path, effect, context):
    sink = RuntimeEffectSink(FakeTransport(), root=tmp_path)
    outcome = sink.submit(effect, context)
    intent = next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.intent.json"))
    payload = json.loads(intent.read_text())
    payload["effect_digest"] = "different"
    intent.write_text(json.dumps(payload))
    with pytest.raises(RuntimeEffectError, match="IDEMPOTENCY_DIGEST_CONFLICT"):
        sink.submit(effect, context)
    assert outcome.state == "completed"


def test_oversized_and_write_escape_are_rejected_before_transport(tmp_path, effect, context):
    transport = FakeTransport()
    with pytest.raises(RuntimeEffectError, match="EFFECT_PAYLOAD_OVERSIZED"):
        RuntimeEffectSink(transport, root=tmp_path, max_payload_bytes=10).submit(effect, context)
    with pytest.raises(RuntimeEffectError, match="WRITE_SET_ESCAPE"):
        RuntimeEffectSink(transport, root=tmp_path).submit(
            effect, replace(context, plan_node=replace(context.plan_node, write_set=["../secret"]))
        )
    assert not transport.submitted


def test_receipt_and_events_do_not_contain_effect_payload(tmp_path, effect, context):
    secret_effect = replace(effect, preconditions=["TOKEN_DO_NOT_LOG"])
    context = _reauthorize(secret_effect, context)
    sink = RuntimeEffectSink(FakeTransport(), root=tmp_path)
    sink.submit(secret_effect, context)
    outcome_text = next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.outcome.json")).read_text()
    assert "TOKEN_DO_NOT_LOG" not in outcome_text


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ({"schema": "wrong"}, "RECEIPT_SCHEMA_INVALID"),
        ({"state": "applied"}, "RECEIPT_STATE_INVALID"),
        ({"gate_decision": "maybe"}, "RECEIPT_GATE_DECISION_INVALID"),
        ({"base_hash": "stale"}, "RECEIPT_HASH_MISMATCH"),
        ({"prompt": "private"}, "RECEIPT_REDACTION_INVALID"),
        ({"validation": None}, "RECEIPT_VALIDATION_MISSING"),
    ],
)
def test_malformed_or_unsafe_receipt_is_rejected(tmp_path, effect, context, mutation, code):
    transport = FakeTransport()
    original = transport._make_receipt

    def malformed(transaction):
        receipt = original(transaction)
        receipt.update(mutation)
        receipt["receipt_digest"] = canonical_hash(
            {k: v for k, v in receipt.items() if k != "receipt_digest"}
        )
        return receipt

    transport._make_receipt = malformed
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == [code]


def test_invalid_receipt_is_durable_unknown_without_unsafe_receipt(tmp_path, effect, context):
    transport = FakeTransport()
    original = transport._make_receipt

    def forged(transaction):
        receipt = original(transaction)
        receipt["prompt"] = "DO_NOT_PERSIST"
        receipt["receipt_digest"] = canonical_hash(
            {key: value for key, value in receipt.items() if key != "receipt_digest"}
        )
        return receipt

    transport._make_receipt = forged
    outcome = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)

    assert outcome.state == "effect_unknown"
    assert outcome.latency_ms is not None
    assert not list((tmp_path / ".simplicio-loop/runtime-effects").glob("*.receipt.json"))
    outcome_text = next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.outcome.json")).read_text()
    events_text = (tmp_path / ".simplicio-loop/events.jsonl").read_text()
    assert "DO_NOT_PERSIST" not in outcome_text + events_text
    assert "RECEIPT_REDACTION_INVALID" in outcome_text + events_text


def test_reconcile_invalid_receipt_is_durable_unknown(tmp_path, effect, context):
    transport = FakeTransport()
    sink = RuntimeEffectSink(transport, root=tmp_path)
    completed = sink.submit(effect, context)
    receipt_path = next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.receipt.json"))
    receipt_path.unlink()
    assert transport.receipt is not None
    transport.receipt["causal"] = {**transport.receipt["causal"], "turn_id": "forged"}
    transport.receipt["receipt_digest"] = canonical_hash(
        {key: value for key, value in transport.receipt.items() if key != "receipt_digest"}
    )

    outcome = sink.reconcile(completed.idempotency_key)

    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RECEIPT_CORRELATION_MISMATCH"]
    persisted = json.loads(
        next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.outcome.json")).read_text()
    )
    assert persisted["state"] == "effect_unknown"


def test_restart_reconcile_negotiation_failure_is_durable_unknown(tmp_path, effect, context):
    transport = FakeTransport()
    completed = RuntimeEffectSink(transport, root=tmp_path).submit(effect, context)
    restarted_transport = FakeTransport()
    restarted_transport.capabilities = lambda: (_ for _ in ()).throw(
        RuntimeEffectError("RUNTIME_TRANSPORT_ERROR", "offline")
    )

    outcome = RuntimeEffectSink(restarted_transport, root=tmp_path).reconcile(completed.idempotency_key)

    assert outcome.state == "effect_unknown"
    assert outcome.reason_codes == ["RUNTIME_TRANSPORT_ERROR"]
    persisted = json.loads(
        next((tmp_path / ".simplicio-loop/runtime-effects").glob("*.outcome.json")).read_text()
    )
    assert persisted["state"] == "effect_unknown"


def test_status_reports_health_and_reason_code(tmp_path):
    healthy = RuntimeEffectSink(FakeTransport(), root=tmp_path / "ok")
    assert healthy.status() == {"healthy": True, "transport": "http-json", "reason_codes": []}
    broken_transport = FakeTransport()
    broken_transport.capabilities = lambda: {
        "runtime_version": "invalid",
        "effect_transaction_schemas": [TRANSACTION_SCHEMA],
        "transports": ["http-json"],
    }
    broken = RuntimeEffectSink(broken_transport, root=tmp_path / "broken")
    assert broken.status()["reason_codes"] == ["RUNTIME_VERSION_INVALID"]


def test_circuit_breaker_opens_after_repeated_unknowns(tmp_path, effect, context):
    transport = FakeTransport(failure="RUNTIME_TRANSPORT_ERROR")
    sink = RuntimeEffectSink(transport, root=tmp_path)
    for attempt in range(3):
        current_effect = replace(effect, effect_id=f"effect-{attempt}")
        current_context = _reauthorize(current_effect, replace(context, turn_id=str(attempt)))
        outcome = sink.submit(current_effect, current_context)
        assert outcome.state == "effect_unknown"
    opened_at = sink.breaker.opened_at
    final_effect = replace(effect, effect_id="effect-final")
    blocked = sink.submit(final_effect, _reauthorize(final_effect, replace(context, turn_id="final")))
    assert blocked.state == "not_started"
    assert blocked.reason_codes == ["RUNTIME_CIRCUIT_OPEN"]
    assert sink.breaker.opened_at == opened_at


def test_reconcile_missing_intent_fails_closed(tmp_path):
    with pytest.raises(RuntimeEffectError, match="INTENT_NOT_FOUND"):
        RuntimeEffectSink(FakeTransport(), root=tmp_path).reconcile("missing")


def test_http_transport_uses_public_endpoints(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return Response()

    monkeypatch.setattr("httpx.request", request)
    transport = HttpRuntimeTransport("https://runtime.example/")
    assert transport.capabilities() == {"ok": True}
    assert transport.submit({"x": 1}) == {"ok": True}
    assert transport.query("key") == {"ok": True}
    assert calls == [
        ("GET", "https://runtime.example/v1/capabilities", None),
        ("POST", "https://runtime.example/v1/effect-transactions", {"x": 1}),
        ("GET", "https://runtime.example/v1/effect-transactions/key", None),
    ]


def test_http_transport_rejects_non_object_and_network_error(monkeypatch):
    class BadResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr("httpx.request", lambda *args, **kwargs: BadResponse())
    with pytest.raises(RuntimeEffectError, match="RUNTIME_RESPONSE_INVALID"):
        HttpRuntimeTransport("https://runtime.example").capabilities()

    def fail(*args, **kwargs):
        import httpx

        raise httpx.ConnectError("offline")

    monkeypatch.setattr("httpx.request", fail)
    with pytest.raises(RuntimeEffectError, match="RUNTIME_TRANSPORT_ERROR"):
        HttpRuntimeTransport("https://runtime.example").capabilities()


def test_offline_artifact_paths_and_plan_shapes_fail_closed(tmp_path):
    transport = OfflineRuntimeTransport(root=tmp_path)
    for value in (None, ""):
        with pytest.raises(RuntimeEffectError, match="artifact_ref"):
            transport._artifact_path(value)
    with pytest.raises(RuntimeEffectError, match="inside root"):
        transport._artifact_path(str(tmp_path.parent / "escape.json"))
    with pytest.raises(RuntimeEffectError, match="transaction effect"):
        transport._apply_artifact({})
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeEffectError, match="valid JSON"):
        transport._apply_artifact({"effect": {"artifact_ref": str(invalid)}})
    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps({"operations": "no"}), encoding="utf-8")
    with pytest.raises(RuntimeEffectError, match="mechanical edit plan"):
        transport._apply_artifact({"effect": {"artifact_ref": str(malformed)}})


def test_offline_submit_rejects_keys_schemas_and_persists_after_apply_failure(tmp_path):
    transport = OfflineRuntimeTransport(root=tmp_path)
    with pytest.raises(RuntimeEffectError, match="idempotency key"):
        transport.submit({"idempotency_key": "bad"})
    with pytest.raises(RuntimeEffectError, match="unsupported transaction schema"):
        transport.submit({"idempotency_key": "a" * 16, "schema": "wrong"})
    result = transport.submit(
        {
            "schema": TRANSACTION_SCHEMA,
            "idempotency_key": "b" * 16,
            "effect_digest": "effect",
            "proposal_digest": "proposal",
            "authorization_digest": "authorization",
            "causal": {"effect_id": "effect-1", "plan_node_id": "node-1"},
            "acceptance_criteria_refs": [],
            "base_hash": "base",
            "source_hash": "source",
            "effect": {"artifact_ref": str(tmp_path / "missing.json")},
        }
    )
    assert result["state"] == "denied"
    assert result["reason_codes"] == ["OFFLINE_EFFECT_ARTIFACT_INVALID"]
    assert transport.query("b" * 16)["state"] == "denied"


def test_runtime_sink_environment_requires_explicit_transport(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_RUNTIME_OFFLINE", raising=False)
    monkeypatch.delenv("SIMPLICIO_RUNTIME_URL", raising=False)
    with pytest.raises(IntegratedModeRequiresSinkError, match="RUNTIME_NOT_CONFIGURED"):
        RuntimeEffectSink.from_environment(root=tmp_path)
    monkeypatch.setenv("SIMPLICIO_RUNTIME_OFFLINE", "1")
    sink = RuntimeEffectSink.from_environment(root=tmp_path)
    assert isinstance(sink.transport, OfflineRuntimeTransport)


def test_sensitive_key_and_write_set_guards():
    assert _contains_sensitive_key({"nested": [{"api_key": "secret"}]}) is True
    assert _contains_sensitive_key({"safe": ["value"]}) is False
    with pytest.raises(RuntimeEffectError, match="unsafe write path"):
        _safe_write_set(["../secret"])
    _safe_write_set(["src/a.py", "nested\\b.py"])
