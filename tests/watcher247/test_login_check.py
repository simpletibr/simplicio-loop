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


# Verified against each CLI's --help on the reference host. gemini is not installed there: its entry is DOC-BASED.
VERIFIED_LOGIN = {
    "claude": "claude auth login",  # `claude auth --help`: login|logout|status
    "codex": "codex login",  # `codex login --help`: subcommand status only, bare `login` signs in
    "grok": "grok login",  # `grok login --help`
    "agy": "agy",  # `agy --help`: no login subcommand; sign-in runs on the interactive start
    "opencode": "opencode auth login",  # `opencode auth --help`: login|logout|list
}


@pytest.mark.parametrize("family,command", sorted(VERIFIED_LOGIN.items()))
def test_each_family_maps_to_its_verified_login_command(family, command):
    assert login_check.login_command(family) == f"sudo -u simplicio-loop -H {command}"


def test_gemini_entry_is_doc_based_and_labeled():
    assert login_check.login_command("gemini") == "sudo -u simplicio-loop -H gemini"
    assert "gemini" in login_check.DOC_BASED_FAMILIES
    assert login_check.DOC_BASED_FAMILIES.isdisjoint(VERIFIED_LOGIN)


def test_claude_line_uses_auth_login_not_bare_login():
    line = login_check.line(exec_auth.AuthCheckResult("claude", "login_missing", "x"))
    assert line.endswith("sudo -u simplicio-loop -H claude auth login")
    assert "claude login" not in line


def test_doc_based_family_is_labeled_in_the_output():
    line = login_check.line(exec_auth.AuthCheckResult("gemini", "login_missing", "x"))
    assert "doc-based, not verified" in line
