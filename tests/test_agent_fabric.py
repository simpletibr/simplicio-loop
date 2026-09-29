import pytest
from simplicio_loop.agent_fabric import (
    AddressRegistry, FabricAddress, FabricCapability, FabricController,
    FabricError, build_envelope,
)


def setup(level="E2E"):
    registry = AddressRegistry()
    sender = FabricAddress("loop", "router", FabricCapability("route", "1", "DEFAULT", "c"), 1, "loop://router")
    recipient = FabricAddress("fast", "executor", FabricCapability("execute", "1", level, "c"), 1, "fast://executor")
    registry.register(sender); registry.register(recipient)
    return registry, sender, recipient


def envelope(sender, recipient, **changes):
    values = dict(
        run_id="r", task_id="t", work_item_id="w", stage="execution", attempt=1,
        fence="f1", plan_revision="1", sender=sender, recipient=recipient,
        payload_handle="fast://page/1", payload_hash="p", causal_parent="root",
        sequence=1, scope="repo", repo="org/repo", commit="a" * 40, worktree="/w",
        policy_hash="policy", ttl_seconds=60, expected_receipt="fabric-receipt/v1",
        evidence_handles=["mapper://atlas", "quality://plan/1"], reply_handle="loop://reply",
        priority=1, resource_class="write",
    )
    values.update(changes)
    return build_envelope(**values)


def test_address_first_and_capability_levels_do_not_materialize_worker():
    registry, _, _ = setup()
    assert registry.resolve("execute", minimum_level="E2E").agent_id == "executor"
    assert registry.inspect()["workers_materialized"] == 0
    with pytest.raises(FabricError, match="capability_not_bound"):
        registry.resolve("execute", minimum_level="MEASURED")


def test_hookwall_is_only_fire_boundary_and_duplicate_is_idempotent():
    registry, sender, recipient = setup()
    controller = FabricController(registry)
    item = envelope(sender, recipient)
    calls = []
    hookwall = lambda env, fire: fire()
    execute = lambda env: calls.append(env) or {"status": "VERIFIED", "receipt": "effect"}
    first = controller.fire(item, current_fence="f1", hookwall=hookwall, execute=execute)
    second = controller.fire(item, current_fence="f1", hookwall=hookwall, execute=execute)
    assert first == second and len(calls) == 1
    assert registry.workers_materialized == 1
    assert first["completion_authority"] == "LOOP_ONLY"


def test_stale_cross_fence_tamper_and_no_fire_fail_closed():
    registry, sender, recipient = setup()
    controller = FabricController(registry)
    item = envelope(sender, recipient)
    with pytest.raises(FabricError, match="cross_fence"):
        controller.fire(item, current_fence="f2", hookwall=lambda e, f: f(), execute=lambda e: {})
    tampered = dict(item, payload_hash="changed")
    with pytest.raises(FabricError, match="checksum"):
        controller.fire(tampered, current_fence="f1", hookwall=lambda e, f: f(), execute=lambda e: {})
    with pytest.raises(FabricError, match="not_fired"):
        controller.fire(item, current_fence="f1", hookwall=lambda e, f: {"status": "VERIFIED"}, execute=lambda e: {})
    assert registry.workers_materialized == 0


def test_retry_is_bounded_addenda_are_immutable_and_replayable():
    registry, sender, recipient = setup()
    controller = FabricController(registry, max_attempts=2)
    item = envelope(sender, recipient)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            controller.fire(
                item, current_fence="f1", hookwall=lambda e, fire: fire(),
                execute=lambda e: (_ for _ in ()).throw(RuntimeError("boom")),
            )
    with pytest.raises(FabricError, match="retry_exhausted"):
        controller.fire(item, current_fence="f1", hookwall=lambda e, f: f(), execute=lambda e: {})
    replay = controller.replay()
    assert len(replay["addenda"]) == 2
    assert replay["addenda"][1]["previous_addendum_digest"] == replay["addenda"][0]["addendum_digest"]


def test_backpressure_is_explicit():
    registry, sender, recipient = setup()
    controller = FabricController(registry, max_inflight=1)
    controller._inflight = 1
    with pytest.raises(FabricError, match="backpressure"):
        controller.fire(envelope(sender, recipient), current_fence="f1",
                        hookwall=lambda e, f: f(), execute=lambda e: {})


def test_real_hookwall_adapter_produces_pre_post_evidence(tmp_path):
    from simplicio_loop.agent_fabric import HookwallAdapter
    from simplicio_loop.coverage_custodian_host import proceed_decision
    registry, sender, recipient = setup()
    adapter = HookwallAdapter(
        str(tmp_path),
        lambda value: proceed_decision(value, phase="pre"),
        lambda value, receipt: proceed_decision(
            value, phase="post", receipt_hash=receipt["receipt_hash"],
        ),
    )
    receipt = FabricController(registry).fire(
        envelope(sender, recipient), current_fence="f1", hookwall=adapter,
        execute=lambda value: {"worker": "fast", "status": "FIXED"},
    )
    assert receipt["effect_receipt"]["hookwall_evidence"]["verdict"] == "verified"
