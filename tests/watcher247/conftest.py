"""Shared fixture: state dir per test, active subscription, and an injected proc.run."""
import pytest

from simplicio_loop.watcher247 import config, proc, sandbox, state, subscription

from .fakes import FIXED


@pytest.fixture
def env(tmp_path, monkeypatch):
    original = config.STATE_DIR
    config.set_state_dir(tmp_path)
    monkeypatch.setattr(state, "now", lambda: FIXED)
    monkeypatch.delenv("SIMPLICIO_247_CONCURRENCY", raising=False)
    monkeypatch.setenv("GH_TOKEN", "ghp_FAKEconftest00000000000000000000")  # the tick idles without a GitHub token
    monkeypatch.setenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", "1")  # sandbox has its own tests
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: None)  # same argv on every host
    # The default executor is exec (host_mode, see test_host_mode.py); these tests cover the opt-in openrouter path.
    monkeypatch.setenv("SIMPLICIO_EXECUTOR", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    async def active():
        return {"active": True, "reason": "ok"}

    monkeypatch.setattr(subscription, "mcp_subscription", active)

    def install(fake):
        monkeypatch.setattr(proc, "run", fake)
        return fake

    yield install
    config.set_state_dir(original)
