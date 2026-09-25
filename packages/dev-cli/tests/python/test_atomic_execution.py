"""Unit, integration, system and regression coverage for issue #258."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from simplicio.atomic_execution import (
    AttemptContext,
    IntegratedOwnershipError,
    execute_work_item_once,
)
from simplicio.plan_compiler import (
    EffectDispatchContext,
    EffectOutcome,
    EffectPlan,
    PlanNode,
    RecordingEffectSink,
)


class CallableSink:
    def __init__(self, callback):
        self.callback = callback

    def submit(self, effect, context):
        return self.callback(effect)


def _node(node_id: str = "edit") -> PlanNode:
    return PlanNode(node_id=node_id, capability="edit.apply")


def _effect(effect_id: str = "effect-1", node_id: str = "edit") -> EffectPlan:
    return EffectPlan(effect_id, node_id, "write", "runtime", f"key-{effect_id}")


def _attempt(identifier: str = "attempt-1", **kwargs) -> AttemptContext:
    return AttemptContext(identifier, "lease-1", "fence-1", "snapshot-1", **kwargs)


def test_outer_retries_are_exactly_one_sink_call_per_dispatch() -> None:
    sink = RecordingEffectSink()

    observations = [
        execute_work_item_once(
            _node(), _attempt(f"attempt-{index}"), effects=[_effect()], verifications=[], effect_sink=sink
        )
        for index in range(3)
    ]

    assert len(sink.received) == 3
    assert [item.attempt_id for item in observations] == ["attempt-0", "attempt-1", "attempt-2"]
    assert sum(item.resources["effect_calls"] for item in observations) == 3
    assert all(item.resources["model_calls"] == 0 for item in observations)


@pytest.mark.parametrize(
    ("attempt", "outcome"),
    [
        (_attempt(cancellation_requested=lambda: True), "cancelled"),
        (_attempt(lease_valid=lambda _lease, _fence: False), "lease_lost"),
        (_attempt(fence_current=lambda _fence: False), "stale_fence"),
    ],
)
def test_cancel_lease_and_fence_stop_before_effect(attempt: AttemptContext, outcome: str) -> None:
    sink = RecordingEffectSink()

    observation = execute_work_item_once(
        _node(), attempt, effects=[_effect()], verifications=[], effect_sink=sink
    )

    assert observation.outcome == outcome
    assert observation.retryability == "retryable"
    assert observation.failure_fingerprint
    assert sink.received == []


def test_guard_is_rechecked_immediately_before_effect_boundary() -> None:
    checks = iter([False, True])
    sink = RecordingEffectSink()
    attempt = _attempt(cancellation_requested=lambda: next(checks))

    observation = execute_work_item_once(
        _node(), attempt, effects=[_effect()], verifications=[], effect_sink=sink
    )

    assert observation.outcome == "cancelled"
    assert sink.received == []


def test_sink_outcomes_declare_retryability_but_never_retry() -> None:
    calls = 0

    def rejected(effect: EffectPlan) -> EffectOutcome:
        nonlocal calls
        calls += 1
        return EffectOutcome(effect.effect_id, "blocked_conflict", effect.idempotency_key)

    observation = execute_work_item_once(
        _node(), _attempt(), effects=[_effect()], verifications=[], effect_sink=CallableSink(rejected)
    )

    assert calls == 1
    assert observation.outcome == "failed"
    assert observation.retryability == "retryable"


def test_sink_crash_is_effect_unknown_without_automatic_retry() -> None:
    calls = 0

    def crashed(_effect: EffectPlan) -> EffectOutcome:
        nonlocal calls
        calls += 1
        raise ConnectionError("response lost")

    observation = execute_work_item_once(
        _node(), _attempt(), effects=[_effect()], verifications=[], effect_sink=CallableSink(crashed)
    )

    assert calls == 1
    assert observation.outcome == "effect_unknown"
    assert observation.retryability == "unknown"
    assert "response lost" not in observation.reason


def test_runtime_not_started_is_retryable_failure_not_submitted() -> None:
    class NotStartedSink:
        def submit(self, effect, context):
            return EffectOutcome(
                effect.effect_id,
                "not_started",
                "key-1",
                reason_codes=["RUNTIME_TRANSPORT_ERROR"],
            )

    observation = execute_work_item_once(
        _node(),
        _attempt(),
        effects=[_effect()],
        verifications=[],
        effect_sink=NotStartedSink(),
    )

    assert observation.outcome == "failed"
    assert observation.retryability == "retryable"
    assert observation.reason == "RUNTIME_TRANSPORT_ERROR"


def test_receipt_preserves_coordinator_identity_and_handles() -> None:
    def completed(effect: EffectPlan) -> EffectOutcome:
        return EffectOutcome(
            effect.effect_id,
            "completed",
            effect.idempotency_key,
            receipt={"receipt_handle": "runtime://receipt/1", "evidence_handles": ["sha256:abc"]},
        )

    observation = execute_work_item_once(
        _node(),
        _attempt("attempt-restart"),
        effects=[_effect()],
        verifications=[],
        effect_sink=CallableSink(completed),
    )
    payload = observation.to_dict()

    assert payload["outcome"] == "effect_submitted"
    assert payload["attempt_id"] == "attempt-restart"
    assert payload["lease_id"] == "lease-1"
    assert payload["fencing_token"] == "fence-1"
    assert payload["context_handle"] == "snapshot-1"
    assert payload["receipt_handles"] == ["runtime://receipt/1"]
    assert payload["evidence_handles"] == ["sha256:abc"]


def test_nested_attempt_and_multi_effect_dispatch_fail_closed() -> None:
    def nested(effect: EffectPlan) -> EffectOutcome:
        execute_work_item_once(
            _node(), _attempt("nested"), effects=[effect], verifications=[], effect_sink=RecordingEffectSink()
        )
        raise AssertionError("unreachable")

    with pytest.raises(IntegratedOwnershipError, match="nested integrated attempt"):
        execute_work_item_once(
            _node(), _attempt(), effects=[_effect()], verifications=[], effect_sink=CallableSink(nested)
        )

    with pytest.raises(IntegratedOwnershipError, match="at most one effect"):
        execute_work_item_once(
            _node(),
            _attempt(),
            effects=[_effect("effect-1"), _effect("effect-2")],
            verifications=[],
            effect_sink=RecordingEffectSink(),
        )


@pytest.mark.parametrize(
    ("context", "message"),
    [
        (
            EffectDispatchContext("plan-1", "goal-1", _node("other"), [], "attempt-1"),
            "PlanNode must match",
        ),
        (
            EffectDispatchContext("plan-1", "goal-1", _node(), [], "attempt-other"),
            "preserve the coordinator attempt_id",
        ),
    ],
)
def test_dispatch_context_cannot_replace_coordinator_identity(context, message: str) -> None:
    sink = RecordingEffectSink()

    with pytest.raises(IntegratedOwnershipError, match=message):
        execute_work_item_once(
            _node(),
            _attempt(),
            effects=[_effect()],
            verifications=[],
            effect_sink=sink,
            dispatch_context=context,
        )

    assert sink.received == []


def test_twenty_external_work_items_create_no_local_pool() -> None:
    """System simulation: the coordinator owns its pool; Dev CLI creates none."""
    baseline_threads = {thread.ident for thread in threading.enumerate()}
    sink = RecordingEffectSink()

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="coordinator-owned") as pool:
        observations = list(
            pool.map(
                lambda index: execute_work_item_once(
                    _node(),
                    _attempt(f"attempt-{index}"),
                    effects=[_effect(f"effect-{index}")],
                    verifications=[],
                    effect_sink=sink,
                ),
                range(20),
            )
        )

    assert len(sink.received) == 20
    assert all(item.resources["threads_created"] == 0 for item in observations)
    assert all(item.resources["worktrees_created"] == 0 for item in observations)
    assert not any(
        thread.name.startswith("simplicio") and thread.ident not in baseline_threads
        for thread in threading.enumerate()
    )


def test_attempt_context_rejects_missing_coordinator_fields() -> None:
    with pytest.raises(ValueError, match="attempt_id"):
        AttemptContext("", "lease", "fence", "snapshot")
