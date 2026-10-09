"""Tests for exec_auth doctor check integration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    """PATH holds only fake CLIs in tmp_path/bin; HOME is a fake tmp_path/home.

    Returns (bin_dir, home, log). Each fake appends its argv to `log` and exits with its code.
    """
    bin_dir = tmp_path / "bin"
    home = tmp_path / "home"
    bin_dir.mkdir()
    home.mkdir()
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: home)
    return bin_dir, home, log


def _fake_cli(fake_env, name: str, exit_code: int) -> Path:
    bin_dir, _home, log = fake_env
    script = bin_dir / name
    script.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit {exit_code}\n')
    script.chmod(0o755)
    return script


def test_chk_exec_clis_integration(fake_env, exec_auth_spawn_guard):
    """chk_exec_clis is in doctor.CHECKS and reports per-CLI state from fakes only."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

    import doctor

    assert hasattr(doctor, "chk_exec_clis"), "chk_exec_clis not found in doctor.py"
    check_names = [c.__name__ for c in doctor.CHECKS]
    assert "chk_exec_clis" in check_names, "chk_exec_clis not in CHECKS list"

    _bin_dir, home, log = fake_env
    claude = _fake_cli(fake_env, "claude", 0)  # `claude auth status` succeeds -> ok
    codex = _fake_cli(fake_env, "codex", 1)  # `codex login status` fails, no creds -> login_missing
    _fake_cli(fake_env, "grok", 1)  # no status subcommand; credential file -> ok
    (home / ".grok").mkdir()
    (home / ".grok" / "auth.json").write_text("{}")
    # gemini: no binary on PATH -> cli_missing

    result = doctor.chk_exec_clis()

    assert result["name"] == "exec CLIs auth"
    assert result["tier"] == "OPTIONAL"
    assert result["status"] == doctor.OK
    assert result["msg"] == (
        "2 authenticated: claude, grok"
        " | 1 missing: cli_missing:gemini"
        " | 1 unauthenticated: login_missing:codex"
    )
    # Only the verified status subcommands ran; grok (no status subcommand) was never spawned.
    assert sorted(log.read_text().splitlines()) == ["claude auth status", "codex login status"]
    assert set(exec_auth_spawn_guard) == {str(claude.resolve()), str(codex.resolve())}


def test_exec_auth_reason_codes(fake_env, exec_auth_spawn_guard):
    """Reason codes: cli_missing/<cli>_not_in_path and login_missing/no_credentials_found."""
    from simplicio_loop.exec_auth import check_sync

    result = check_sync("claude")
    assert (result.status, result.reason_code) == ("cli_missing", "claude_not_in_path")
    assert exec_auth_spawn_guard == []

    _fake_cli(fake_env, "claude", 1)  # status fails, fake HOME has no credentials
    result = check_sync("claude")
    assert (result.status, result.reason_code) == ("login_missing", "no_credentials_found")
    assert len(set(exec_auth_spawn_guard)) == 1


if __name__ == "__main__":
    pytest.main(["-v", __file__])
