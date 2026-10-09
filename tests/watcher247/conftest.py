"""Shared fixture: state dir per test, active subscription, and an injected proc.run."""
import pytest

from simplicio_loop.watcher247 import config, proc, state, subscription

from .fakes import FIXED


@pytest.fixture
def env(tmp_path, monkeypatch):
    original = config.STATE_DIR
    config.set_state_dir(tmp_path)
    monkeypatch.setattr(state, "now", lambda: FIXED)
    monkeypatch.delenv("SIMPLICIO_247_CONCURRENCY", raising=False)

    async def active():
        return {"active": True, "reason": "ok"}

    monkeypatch.setattr(subscription, "mcp_subscription", active)

    def install(fake):
        monkeypatch.setattr(proc, "run", fake)
        return fake

    yield install
    config.set_state_dir(original)
