"""`simplicio-loop watch247 login-check` (#1467): per-CLI login state and the exact fix command. Fake CLIs only."""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, exec_auth
from simplicio_loop.watcher247 import login_check


def install(directory, name, logged_in):
    script = directory / name
    script.write_text(f"#!/bin/sh\nexit {0 if logged_in else 1}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def clis(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # no real credential files
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    found = {}
    monkeypatch.setattr(exec_auth.shutil, "which", lambda name, *a, **k: found.get(name))

    def add(name, logged_in):
        found[name] = str(install(bin_dir, name, logged_in))

    monkeypatch.setenv("SIMPLICIO_EXEC_FAMILIES", "claude,codex,grok")
    return add


def test_all_ok_exits_zero(clis, capsys):
    clis("claude", True)
    clis("codex", True)
    clis("grok", True)
    cred = Path.home() / ".grok" / "auth.json"
    cred.parent.mkdir(parents=True)
    cred.write_text("{}")
    assert login_check.main() == 0
    out = capsys.readouterr().out
    assert "claude: ok" in out and "codex: ok" in out and "grok: ok" in out


def test_missing_login_prints_the_exact_command_and_exits_one(clis, capsys):
    clis("claude", True)
    clis("codex", False)  # `codex login status` fails
    assert login_check.main() == 1
    out = capsys.readouterr().out
    assert "claude: ok" in out
    assert "codex: login_missing: sudo -u simplicio-loop -H codex login" in out
    assert "grok: cli_missing" in out and "sudo -u simplicio-loop -H grok login" in out


def test_command_is_wired_into_the_cli(clis, capsys):
    clis("claude", True)
    clis("codex", True)
    assert cli_impl.main(["watch247", "login-check"]) == 1  # grok is missing
    assert "claude: ok" in capsys.readouterr().out
