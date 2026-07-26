"""Shared isolation for deterministic local and contract tests."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_execution_environment(monkeypatch: pytest.MonkeyPatch):
    """Keep legacy pipeline tests explicit and independent of host proxies.

    Production defaults remain fail-closed. Tests that exercise the legacy
    standalone pipeline opt in through the same migration switch required of
    real callers; execution-mode tests can still delete or override it.
    """
    monkeypatch.setenv("SIMPLICIO_ALLOW_STANDALONE_FALLBACK", "true")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "*")
    yield
    (REPO_ROOT / ".simplicio" / "events.jsonl").unlink(missing_ok=True)
