"""Client integrations are opt-in; Orca is never default."""

from __future__ import annotations

import json
import os
from pathlib import Path

from simplicio_loop.client_integrations import (
    describe,
    integration_enabled,
    resolve_integrations,
)
from simplicio_loop.orca_lifecycle import _disabled


def test_default_has_no_integrations(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert resolve_integrations(repo_root=tmp_path) == frozenset()
    assert integration_enabled("orca", repo_root=tmp_path) is False
    assert _disabled() is True


def test_env_list_enables_orca(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS", "orca")
    monkeypatch.delenv("SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC", raising=False)
    monkeypatch.chdir(tmp_path)
    assert integration_enabled("orca", repo_root=tmp_path) is True
    assert _disabled() is False


def test_legacy_orca_env_maps_to_integration(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS", raising=False)
    monkeypatch.setenv("SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC", "1")
    monkeypatch.chdir(tmp_path)
    assert integration_enabled("orca", repo_root=tmp_path) is True


def test_repo_file_enables_named_integrations(monkeypatch, tmp_path):
    monkeypatch.delenv("SIMPLICIO_LOOP_CLIENT_INTEGRATIONS", raising=False)
    monkeypatch.delenv("SIMPLICIO_LOOP_ORCA_LIFECYCLE_SYNC", raising=False)
    cfg = tmp_path / ".simplicio-loop" / "client-integrations.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        json.dumps({"schema": "simplicio.client-integrations/v1", "integrations": ["linear"]}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    assert integration_enabled("linear", repo_root=tmp_path) is True
    assert integration_enabled("orca", repo_root=tmp_path) is False
    payload = describe(repo_root=tmp_path)
    assert payload["policy"] == "opt-in-only-per-client-request"
    assert payload["enabled"] == ["linear"]
