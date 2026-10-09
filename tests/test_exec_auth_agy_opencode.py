"""agy and opencode login preflight (#1513). Fake CLIs and fake credential files only; no real CLI is spawned.

agy:      no status subcommand (`agy --help`); credential file ~/.gemini/antigravity-cli/antigravity-oauth-token,
          tested by stat only (exists, regular file, non-empty), never opened.
opencode: `opencode auth list` always exits 0; its last line is `N credentials`. Only that count is parsed and the
          rest of the output (provider names) is dropped. A cred file is never read.
"""
from __future__ import annotations

import asyncio
import logging
import stat

import pytest

from simplicio_loop import exec_auth

SECRET = "sk-SECRET-TOKEN-0123456789abcdefghijklmnop"


@pytest.fixture
def env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(exec_auth.Path, "home", classmethod(lambda cls: home))
    return home, bindir


def fake_cli(bindir, name, body="exit 0"):
    script = bindir / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def agy_cred(home, content):
    cred = home / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
    cred.parent.mkdir(parents=True)
    cred.write_text(content)
    return cred


def opencode_list(count):
    # same shape as the real CLI: header with the file path, one line per provider, footer with the count
    return (
        "echo '┌  Credentials /somewhere/auth.json'; echo '│'; "
        f"echo '●  provider-name api'; echo '│'; echo '└  {count} credentials'"
    )


def run(family):
    return asyncio.run(exec_auth.check(family))


# ---- agy ----

def test_agy_logged_in(env):
    home, bindir = env
    fake_cli(bindir, "agy")
    agy_cred(home, SECRET)
    assert run("agy").status == "ok"


def test_agy_not_logged_in(env):
    _, bindir = env
    fake_cli(bindir, "agy")
    result = run("agy")
    assert (result.status, result.reason_code) == ("login_missing", "no_credentials_found")


def test_agy_cli_missing(env):
    home, _ = env
    agy_cred(home, SECRET)  # credentials alone do not make a missing CLI usable
    assert run("agy").status == "cli_missing"


def test_agy_empty_credential_file_is_not_logged_in(env):
    home, bindir = env
    fake_cli(bindir, "agy")
    agy_cred(home, "")
    assert run("agy").status == "login_missing"


def test_agy_never_spawned(env):
    """agy has no status subcommand: running it would start the interactive CLI."""
    home, bindir = env
    marker = home / "spawned"
    fake_cli(bindir, "agy", f"touch {marker}")
    run("agy")
    assert not marker.exists()


# ---- opencode ----

def test_opencode_logged_in(env):
    _, bindir = env
    fake_cli(bindir, "opencode", opencode_list(2))
    assert run("opencode").status == "ok"


def test_opencode_zero_credentials_is_not_logged_in(env):
    _, bindir = env
    fake_cli(bindir, "opencode", opencode_list(0))  # exit code is 0 here, so the count must decide
    assert run("opencode").status == "login_missing"


def test_opencode_cli_missing(env):
    assert run("opencode").status == "cli_missing"


def test_opencode_empty_credential_file_is_not_logged_in(env):
    home, bindir = env
    fake_cli(bindir, "opencode", opencode_list(0))
    cred = home / ".local" / "share" / "opencode" / "auth.json"
    cred.parent.mkdir(parents=True)
    cred.write_text("")
    assert run("opencode").status == "login_missing"


def test_opencode_unparseable_or_failing_output_fails_closed(env):
    _, bindir = env
    fake_cli(bindir, "opencode", "echo something unexpected")
    assert run("opencode").status == "login_missing"
    fake_cli(bindir, "opencode", opencode_list(3) + "; exit 1")
    assert run("opencode").status == "login_missing"


# ---- no secret reaches the result or the logs ----

def test_no_secret_in_result_or_logs(env, caplog, capsys):
    home, bindir = env
    caplog.set_level(logging.DEBUG)
    agy_cred(home, SECRET)
    cred = home / ".local" / "share" / "opencode" / "auth.json"
    cred.parent.mkdir(parents=True)
    cred.write_text(f'{{"x": {{"key": "{SECRET}"}}}}')
    fake_cli(bindir, "agy")
    fake_cli(bindir, "opencode", opencode_list(1) + f"; echo '{SECRET}' >&2")
    results = asyncio.run(exec_auth.check_all(["agy", "opencode"]))
    assert [r.status for r in results] == ["ok", "ok"]
    seen = " ".join(repr(r) + str(r) for r in results) + caplog.text + "".join(capsys.readouterr())
    assert SECRET not in seen
    assert "provider-name" not in seen  # opencode's provider list is parsed for a count only, then dropped


def test_credential_files_are_never_opened(env, monkeypatch):
    home, bindir = env
    agy_cred(home, SECRET)
    fake_cli(bindir, "agy")

    def forbidden(*a, **k):
        raise AssertionError("credential file opened")

    for name in ("open", "read_text", "read_bytes"):
        monkeypatch.setattr(exec_auth.Path, name, forbidden)
    assert run("agy").status == "ok"
