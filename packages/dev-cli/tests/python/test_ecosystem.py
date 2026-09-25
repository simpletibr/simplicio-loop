from __future__ import annotations

import importlib

import simplicio.ecosystem as eco


def _reload():
    module = importlib.reload(eco)
    if hasattr(module, module._SENTINEL_NAME):
        delattr(module, module._SENTINEL_NAME)
    return module


def test_maybe_run_session_start_is_opt_in(monkeypatch):
    module = _reload()
    calls: list[bool] = []
    monkeypatch.delenv("SIMPLICIO_AUTO_UPGRADE", raising=False)
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    monkeypatch.delenv("SIMPLICIO_HOOK_GUARD", raising=False)
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])

    module.maybe_run_session_start()

    assert calls == []


def test_maybe_run_session_start_runs_when_enabled(monkeypatch):
    module = _reload()
    calls: list[bool] = []
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.delenv("SIMPLICIO_SKIP_AUTO_INIT", raising=False)
    monkeypatch.delenv("SIMPLICIO_HOOK_GUARD", raising=False)
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])

    module.maybe_run_session_start()

    assert calls == [True]


def test_no_auto_upgrade_wins_over_auto_upgrade(monkeypatch):
    module = _reload()
    calls: list[bool] = []
    monkeypatch.setenv("SIMPLICIO_AUTO_UPGRADE", "1")
    monkeypatch.setenv("SIMPLICIO_NO_AUTO_UPGRADE", "1")
    monkeypatch.setattr(module, "ensure_latest", lambda: calls.append(True) or [])

    module.maybe_run_session_start()

    assert calls == []


def test_version_lt_handles_prereleases():
    assert eco._version_lt("1.12.0rc1", "1.12.0") is True
    assert eco._version_lt("1.12.0", "1.12.1") is True
    assert eco._version_lt("1.12.0", "1.12.0") is False
    assert eco._version_lt("1.12.0", "1.12.0rc1") is False


def test_ensure_latest_dry_run_never_invokes_pip(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_NO_AUTO_UPGRADE", raising=False)
    monkeypatch.setattr(
        eco,
        "check",
        lambda packages: [
            eco.DepStatus("simplicio-prompt", "1.0.0", "1.1.0", "1.1.0", True, "stale"),
            eco.DepStatus("simplicio-mapper", "1.0.0", "1.0.0", "1.0.0", False, ""),
        ],
    )
    monkeypatch.setattr(
        eco.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pip"))
    )

    result = eco.ensure_latest(dry_run=True)

    assert result == ["simplicio-prompt"]
