from __future__ import annotations

from simplicio_loop.mapper_agent_slots import MapperAgentSlotRegistry
from simplicio_loop import agent_slots


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def initialize(self):
        self.calls.append(("initialize",))
        return {"status": "ready"}

    def configure_agent_slots(self, capacity):
        self.calls.append(("configure", capacity))
        return {"capacity": capacity}

    def agent_slot_status(self):
        self.calls.append(("status",))
        return {"active_slots": 0}

    def agent_slot_acquire(self, agent_id, **kwargs):
        self.calls.append(("acquire", agent_id, kwargs))
        return {"accepted": True}

    def agent_slot_transition(self, agent_id, target, **kwargs):
        self.calls.append(("transition", agent_id, target, kwargs))
        return {"accepted": True}

    def agent_slot_update_blockers(self, agent_id, **kwargs):
        self.calls.append(("blockers", agent_id, kwargs))
        return {"accepted": True}

    def agent_slot_reclaim(self, agent_id=None):
        self.calls.append(("reclaim", agent_id))
        return {"accepted": True}


def test_mapper_registry_is_a_thin_lifecycle_facade():
    adapter = FakeAdapter()
    registry = MapperAgentSlotRegistry("/tmp/operations.sqlite", capacity=3, adapter=adapter)
    registry.initialize()
    registry.acquire("agent-a", worktree="wt", lease_id="lease")
    registry.start("agent-a")
    registry.update_blockers("agent-a", lease_active=True)
    registry.close_agent("agent-a", status="shutdown", reason="test")
    registry.reclaim("agent-a")
    assert adapter.calls == [
        ("initialize",),
        ("configure", 3),
        ("acquire", "agent-a", {"worktree": "wt", "lease_id": "lease"}),
        ("transition", "agent-a", "running", {"reason": "slot_started"}),
        ("blockers", "agent-a", {"descendants": 0, "worktree_active": False, "lease_active": True}),
        ("transition", "agent-a", "shutdown", {"reason": "test"}),
        ("reclaim", "agent-a"),
    ]


def test_agent_slots_cli_defaults_to_mapper_without_legacy_database(monkeypatch, capsys, tmp_path):
    adapter = FakeAdapter()
    monkeypatch.setattr(agent_slots, "_default_mapper_db", lambda _repo: tmp_path / "operations.sqlite")
    monkeypatch.setattr(
        "simplicio_loop.mapper_agent_slots.MapperAgentSlotRegistry",
        lambda database, **kwargs: MapperAgentSlotRegistry(database, adapter=adapter, **kwargs),
    )

    assert agent_slots.cli_main(["status", "--repo", str(tmp_path)]) == 0
    assert adapter.calls == [("status",)]
    assert not (tmp_path / ".simplicio-loop" / "orchestrator" / "agent-slots.sqlite").exists()
    assert '"active_slots": 0' in capsys.readouterr().out


def test_legacy_route_fails_closed_without_creating_a_database(tmp_path, capsys):
    assert agent_slots.cli_main([
        "status", "--route", "legacy", "--db", str(tmp_path / "legacy.sqlite"),
    ]) == 3
    assert not (tmp_path / "legacy.sqlite").exists()
    assert '"reason_code": "LEGACY_ROUTE_REMOVED"' in capsys.readouterr().out
