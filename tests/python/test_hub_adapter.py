"""Tests for simplicio.hub_adapter (issue #231, MVP slice)."""

from __future__ import annotations

import pytest

from simplicio import hub_adapter

# ---------------------------------------------------------------------------
# resolve_hub_mode
# ---------------------------------------------------------------------------


def test_resolve_hub_mode_explicit_wins_over_env(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HUB", "on")
    assert hub_adapter.resolve_hub_mode("off") == "off"


def test_resolve_hub_mode_reads_env_when_no_explicit(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HUB", "on")
    assert hub_adapter.resolve_hub_mode(None) == "on"


def test_resolve_hub_mode_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_HUB", raising=False)
    assert hub_adapter.resolve_hub_mode(None) == "auto"


def test_resolve_hub_mode_unrecognized_value_falls_back_to_auto(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_HUB", raising=False)
    assert hub_adapter.resolve_hub_mode("nonsense") == "auto"


# ---------------------------------------------------------------------------
# HubTaskIdentity
# ---------------------------------------------------------------------------


def test_identity_is_complete_requires_all_four_fields():
    complete = hub_adapter.HubTaskIdentity(
        run_id="run-1", task_id="task-1", lease="lease-1", idempotency_key="idem-1"
    )
    assert complete.is_complete()

    for missing in ("run_id", "task_id", "lease", "idempotency_key"):
        fields = {"run_id": "r", "task_id": "t", "lease": "l", "idempotency_key": "i"}
        fields[missing] = ""
        assert not hub_adapter.HubTaskIdentity(**fields).is_complete()


def test_identity_from_env_reads_all_fields(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HUB_ECOSYSTEM_ID", "eco-1")
    monkeypatch.setenv("SIMPLICIO_HUB_RUN_ID", "run-1")
    monkeypatch.setenv("SIMPLICIO_HUB_TASK_ID", "task-1")
    monkeypatch.setenv("SIMPLICIO_HUB_ATTEMPT", "3")
    monkeypatch.setenv("SIMPLICIO_HUB_LEASE", "lease-1")
    monkeypatch.setenv("SIMPLICIO_HUB_FENCE", "7")
    monkeypatch.setenv("SIMPLICIO_HUB_TRACE_ID", "trace-1")
    monkeypatch.setenv("SIMPLICIO_HUB_IDEMPOTENCY_KEY", "idem-1")

    identity = hub_adapter.HubTaskIdentity.from_env()

    assert identity.ecosystem_id == "eco-1"
    assert identity.run_id == "run-1"
    assert identity.task_id == "task-1"
    assert identity.attempt == 3
    assert identity.lease == "lease-1"
    assert identity.fence == 7
    assert identity.trace_id == "trace-1"
    assert identity.idempotency_key == "idem-1"
    assert identity.is_complete()


def test_identity_from_env_defaults_when_unset(monkeypatch):
    for key in (
        "SIMPLICIO_HUB_ECOSYSTEM_ID",
        "SIMPLICIO_HUB_RUN_ID",
        "SIMPLICIO_HUB_TASK_ID",
        "SIMPLICIO_HUB_ATTEMPT",
        "SIMPLICIO_HUB_LEASE",
        "SIMPLICIO_HUB_FENCE",
        "SIMPLICIO_HUB_TRACE_ID",
        "SIMPLICIO_HUB_IDEMPOTENCY_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    identity = hub_adapter.HubTaskIdentity.from_env()
    assert identity.attempt == 1
    assert identity.fence == 0
    assert not identity.is_complete()


def test_identity_from_env_falls_back_on_bad_integers(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HUB_ATTEMPT", "not-a-number")
    monkeypatch.setenv("SIMPLICIO_HUB_FENCE", "also-not-a-number")
    identity = hub_adapter.HubTaskIdentity.from_env()
    assert identity.attempt == 1
    assert identity.fence == 0


def test_identity_to_dict_round_trips_fields():
    identity = hub_adapter.HubTaskIdentity(run_id="r", task_id="t", lease="l", idempotency_key="i")
    as_dict = identity.to_dict()
    assert as_dict["run_id"] == "r"
    assert as_dict["idempotency_key"] == "i"


# ---------------------------------------------------------------------------
# route_task
# ---------------------------------------------------------------------------


def test_route_task_mechanical_when_plan_has_operations():
    plan = {"operations": [{"kind": "text-replace"}]}
    assert hub_adapter.route_task(plan=plan, goal="") == "mechanical"


def test_route_task_semantic_when_only_goal():
    assert hub_adapter.route_task(plan=None, goal="add a test") == "semantic"


def test_route_task_semantic_wins_when_plan_has_empty_operations():
    plan = {"operations": []}
    assert hub_adapter.route_task(plan=plan, goal="add a test") == "semantic"


def test_route_task_blocked_when_neither():
    assert hub_adapter.route_task(plan=None, goal="") == "blocked"
    assert hub_adapter.route_task(plan={"operations": []}, goal="") == "blocked"


def test_route_task_ignores_non_dict_plan():
    assert hub_adapter.route_task(plan="not-a-dict", goal="goal") == "semantic"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HubTaskAdapter
# ---------------------------------------------------------------------------


def _complete_identity() -> hub_adapter.HubTaskIdentity:
    return hub_adapter.HubTaskIdentity(
        run_id="run-1", task_id="task-1", lease="lease-1", idempotency_key="idem-1"
    )


def test_adapter_create_resolves_mode_and_identity(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_HUB", raising=False)
    for key in ("SIMPLICIO_HUB_RUN_ID", "SIMPLICIO_HUB_TASK_ID"):
        monkeypatch.delenv(key, raising=False)
    adapter = hub_adapter.HubTaskAdapter.create()
    assert adapter.mode == "auto"
    assert not adapter.identity.is_complete()


def test_guard_identity_passes_when_mode_off_regardless_of_identity():
    adapter = hub_adapter.HubTaskAdapter(mode="off", identity=hub_adapter.HubTaskIdentity())
    adapter.guard_identity()  # must not raise


def test_guard_identity_passes_when_mode_on_and_identity_complete():
    adapter = hub_adapter.HubTaskAdapter(mode="on", identity=_complete_identity())
    adapter.guard_identity()  # must not raise


def test_guard_identity_blocks_when_mode_on_and_identity_incomplete():
    adapter = hub_adapter.HubTaskAdapter(mode="on", identity=hub_adapter.HubTaskIdentity())
    with pytest.raises(hub_adapter.HubModeBlocked, match="run_id/task_id/lease"):
        adapter.guard_identity()


def test_route_passes_through_when_mode_off():
    adapter = hub_adapter.HubTaskAdapter(mode="off", identity=hub_adapter.HubTaskIdentity())
    assert adapter.route(plan=None, goal="") == "blocked"  # no raise despite blocked route


def test_route_blocks_when_mode_on_and_route_is_blocked():
    adapter = hub_adapter.HubTaskAdapter(mode="on", identity=_complete_identity())
    with pytest.raises(hub_adapter.HubModeBlocked, match="neither a mechanical plan"):
        adapter.route(plan=None, goal="")


def test_route_succeeds_when_mode_on_and_route_is_mechanical():
    adapter = hub_adapter.HubTaskAdapter(mode="on", identity=_complete_identity())
    assert adapter.route(plan={"operations": [{"kind": "x"}]}, goal="") == "mechanical"


def test_local_scheduler_allowed_false_only_in_mode_on():
    assert hub_adapter.HubTaskAdapter(
        mode="off", identity=hub_adapter.HubTaskIdentity()
    ).local_scheduler_allowed
    assert hub_adapter.HubTaskAdapter(
        mode="auto", identity=hub_adapter.HubTaskIdentity()
    ).local_scheduler_allowed
    assert not hub_adapter.HubTaskAdapter(
        mode="on", identity=hub_adapter.HubTaskIdentity()
    ).local_scheduler_allowed


def test_doctor_status_shape():
    adapter = hub_adapter.HubTaskAdapter(mode="on", identity=_complete_identity())
    status = adapter.doctor_status()
    assert status["schema"] == "simplicio.hub-adapter-status/v1"
    assert status["mode"] == "on"
    assert status["identity_complete"] is True
    assert status["local_scheduler_allowed"] is False
    assert status["identity"]["run_id"] == "run-1"
