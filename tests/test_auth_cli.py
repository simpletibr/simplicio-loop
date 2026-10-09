"""`simplicio-loop login | logout | auth status` (#1575).

A fake Runtime script stands in for `simplicio`; every token and e-mail is FAKE; HOME and PATH are under tmp_path.
No test reads the real ~/.simplicio, starts the real OAuth flow or calls the subscription server.
"""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from simplicio_loop import auth, auth_cli, cli

FAKE_ACCESS = "fake-access-token-AAAA"
FAKE_REFRESH = "fake-refresh-token-BBBB"
FAKE_EMAIL = "wesley.fake@example.org"
MASKED = "w***@example.org"
SECRETS = (FAKE_ACCESS, FAKE_REFRESH, FAKE_EMAIL, "wesley.fake")

posix = pytest.mark.skipif(os.name == "nt", reason="shell script Runtime")


def login_doc(**over):
    doc = {"access_token": FAKE_ACCESS, "refresh_token": FAKE_REFRESH,
           "access_expires_at": int(time.time()) + 900, "refresh_token_expires_at": 0,
           "verification": {"validated": {"user": {"email": FAKE_EMAIL},
                                          "entitlement": {"tier": "pro", "status": "active", "source": "stripe",
                                                          "plan": "p", "active": True}}}}
    doc.update(over)
    return doc


@pytest.fixture
def box(tmp_path, monkeypatch):
    """A private HOME and an empty PATH folder; the login env vars are cleared."""
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    for name in ("SIMPLICIO_247_LOGIN", "SIMPLICIO_AUTH_FILE", "BROWSER"):
        monkeypatch.delenv(name, raising=False)
    return type("Box", (), {"home": home, "bin": bindir, "login": home / ".simplicio" / "login.json",
                            "log": tmp_path / "runtime.log", "tmp": tmp_path})


def put_login(path: Path, doc=None, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc if doc is not None else login_doc()))
    path.chmod(mode)
    return path


def fake_runtime(box, *, writes=True, exit_code=0, version="3.10.0"):
    """A `simplicio` that answers --version, and on `login google` logs its argv/env and writes a FAKE login.

    PATH holds only this folder (a real Runtime must never be found), so the script uses shell builtins only."""
    box.login.parent.mkdir(parents=True, exist_ok=True)
    doc = json.dumps(login_doc(access_expires_at=int(time.time()) + 900))
    script = box.bin / "simplicio"
    script.write_text(f"""#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "simplicio {version}"; echo "executable: $0"; echo "component: runtime-kernel {version}"; exit 0
fi
echo "argv: $*" >> '{box.log}'
echo "auth_file: $SIMPLICIO_AUTH_FILE" >> '{box.log}'
echo "browser: $BROWSER" >> '{box.log}'
echo "Open https://example.invalid/device to sign in"
TARGET="${{SIMPLICIO_AUTH_FILE:-$HOME/.simplicio/login.json}}"
[ "{int(writes)}" = "1" ] && {{ umask 077; printf '%s' '{doc}' > "$TARGET"; }}
exit {exit_code}
""")
    script.chmod(0o755)
    return script


def output(capfd):
    out, err = capfd.readouterr()
    return out, err


def assert_no_secret(*channels):
    for text in channels:
        for secret in SECRETS:
            assert secret not in text, f"{secret!r} leaked"


# --- login -----------------------------------------------------------------------------------------------------------


@posix
def test_login_delegates_to_the_runtime_and_checks_the_shared_file(box, capfd):
    fake_runtime(box)
    rc = auth_cli.login()
    out, err = output(capfd)
    assert rc == 0
    assert "argv: login google" in box.log.read_text()
    assert box.login.is_file() and stat.S_IMODE(box.login.stat().st_mode) == 0o600
    assert "verified" in out and MASKED in out and "3.10.0" in out and str(box.login) in out
    assert "https://example.invalid/device" in out  # the Runtime talks to the terminal untouched
    assert_no_secret(out, err)


@posix
def test_login_json_keeps_stdout_a_single_document(box, capfd):
    fake_runtime(box)
    rc = auth_cli.login(as_json=True)
    out, err = output(capfd)
    doc = json.loads(out)
    assert rc == 0 and doc["status"] == "VERIFIED" and doc["logged_in"] is True
    assert doc["email"] == MASKED and doc["runtime"]["version"] == "3.10.0"
    assert "https://example.invalid/device" in err  # the Runtime output went to stderr
    assert_no_secret(out, err)


@posix
def test_login_points_the_runtime_at_the_file_the_loop_reads(box, capfd, monkeypatch):
    custom = box.tmp / "service" / "login.json"
    custom.parent.mkdir()
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(custom))
    fake_runtime(box)
    rc = auth_cli.login(as_json=True)
    out, _ = output(capfd)
    assert rc == 0 and custom.is_file() and not box.login.is_file()
    assert f"auth_file: {custom}" in box.log.read_text()
    assert json.loads(out)["path"] == str(custom)


@posix
def test_login_leaves_the_environment_alone_when_both_use_the_same_file(box, capfd):
    fake_runtime(box)
    auth_cli.login()
    assert "auth_file: \n" in box.log.read_text()


@posix
def test_no_browser_asks_the_runtime_not_to_open_one(box, capfd):
    fake_runtime(box)
    auth_cli.login(no_browser=True)
    assert "browser: true" in box.log.read_text()
    capfd.readouterr()
    auth_cli.login()
    assert "browser: true\n" not in box.log.read_text().split("argv: login google")[-1]


@posix
def test_a_failing_runtime_login_is_not_verified(box, capfd):
    fake_runtime(box, writes=False, exit_code=7)
    rc = auth_cli.login(as_json=True)
    out, _ = output(capfd)
    doc = json.loads(out)
    assert rc == 1 and doc["status"] == "NOT_VERIFIED" and doc["reason_code"] == "runtime_login_failed"
    assert doc["runtime_exit_code"] == 7


@posix
def test_a_runtime_that_says_ok_but_wrote_no_login_is_not_verified(box, capfd):
    fake_runtime(box, writes=False)
    rc = auth_cli.login(as_json=True)
    out, _ = output(capfd)
    doc = json.loads(out)
    assert rc == 1 and doc["status"] == "NOT_VERIFIED" and doc["reason_code"] == "login_missing"


@posix
def test_a_login_that_group_can_read_is_not_verified(box, capfd):
    script = fake_runtime(box)
    script.write_text(script.read_text().replace("umask 077", "umask 022"))
    rc = auth_cli.login(as_json=True)
    out, _ = output(capfd)
    doc = json.loads(out)
    assert rc == 1 and doc["reason_code"] == "login_permissions" and "chmod 600" in doc["fix"]


def test_without_the_runtime_standalone_login_is_unverified_and_says_how_to_install_it(box, capfd):
    rc = auth_cli.login()
    out, err = output(capfd)
    assert rc == 1
    assert "UNVERIFIED" in out and "Runtime" in out
    assert "curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/master/install.sh | sh" in out
    assert "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/master/install.ps1 | iex" in out
    assert "simplicio-loop login" in out
    assert not box.login.exists() and not box.login.parent.exists()  # nothing was created
    capfd.readouterr()
    rc = auth_cli.login(as_json=True)
    doc = json.loads(output(capfd)[0])
    assert rc == 1 and doc["status"] == "UNVERIFIED" and doc["reason_code"] == "standalone_login_unverified"
    assert doc["runtime"]["found"] is False and doc["install"]


# --- logout ----------------------------------------------------------------------------------------------------------


def test_logout_without_yes_deletes_nothing_and_warns_about_the_runtime(box, capfd):
    put_login(box.login)
    rc = auth_cli.logout()
    out, err = output(capfd)
    assert rc == 2 and box.login.exists()
    assert "Runtime" in out + err and "--yes" in out + err and str(box.login) in out + err
    assert_no_secret(out, err)


def test_logout_with_yes_removes_the_shared_file(box, capfd):
    put_login(box.login)
    rc = auth_cli.logout(yes=True)
    out, err = output(capfd)
    assert rc == 0 and not box.login.exists()
    assert "Runtime" in out and "not revoked" in out
    assert_no_secret(out, err)
    rc = auth_cli.logout(yes=True, as_json=True)
    doc = json.loads(output(capfd)[0])
    assert rc == 0 and doc["status"] == "NO_LOGIN"


def test_logout_json(box, capfd):
    put_login(box.login)
    assert auth_cli.logout(as_json=True) == 2
    refused = json.loads(output(capfd)[0])
    assert refused["status"] == "REFUSED" and refused["also_logs_out_runtime"] is True and box.login.exists()
    assert auth_cli.logout(yes=True, as_json=True) == 0
    done = json.loads(output(capfd)[0])
    assert done["status"] == "LOGGED_OUT" and not box.login.exists()


# --- auth status -----------------------------------------------------------------------------------------------------


@posix
def test_status_shows_the_account_expiry_entitlement_and_runtime_without_any_secret(box, capfd):
    put_login(box.login)
    fake_runtime(box)
    rc = auth_cli.status()
    out, err = output(capfd)
    assert rc == 0
    for expected in (MASKED, "pro", "3.10.0", str(box.login), "expires"):
        assert expected in out, expected
    assert_no_secret(out, err)


@posix
def test_status_json_has_no_secret_and_the_documented_keys(box, capfd):
    put_login(box.login)
    fake_runtime(box)
    rc = auth_cli.status(as_json=True)
    out, err = output(capfd)
    doc = json.loads(out)
    assert rc == 0 and doc["schema"] == "simplicio.auth-status/v1"
    assert doc["logged_in"] is True and doc["reason_code"] == "ok" and doc["email"] == MASKED
    assert doc["access_expired"] is False and doc["entitlement"]["tier"] == "pro"
    assert doc["path"] == str(box.login) and doc["shared_with_runtime"] is True
    assert doc["runtime"] == {"found": True, "path": str(box.bin / "simplicio"), "version": "3.10.0"}
    assert "access_token" not in doc and "refresh_token" not in doc
    assert_no_secret(out, err)


def test_status_of_a_missing_login(box, capfd):
    rc = auth_cli.status(as_json=True)
    doc = json.loads(output(capfd)[0])
    assert rc == 1 and doc["logged_in"] is False and doc["reason_code"] == "login_missing"
    assert doc["fix"] == "simplicio-loop login"
    rc = auth_cli.status()
    out, _ = output(capfd)
    assert rc == 1 and "not logged in" in out and "simplicio-loop login" in out


@posix
def test_status_refuses_a_file_others_can_read_and_says_the_fix(box, capfd):
    put_login(box.login, mode=0o644)
    rc = auth_cli.status(as_json=True)
    out, err = output(capfd)
    doc = json.loads(out)
    assert rc == 1 and doc["reason_code"] == "login_permissions" and doc["fix"] == f"chmod 600 {box.login}"
    assert_no_secret(out, err)


def test_status_of_an_expired_login(box, capfd):
    put_login(box.login, login_doc(access_expires_at=1, refresh_token="", refresh_token_expires_at=0))
    rc = auth_cli.status(as_json=True)
    doc = json.loads(output(capfd)[0])
    assert rc == 1 and doc["reason_code"] == "login_expired" and doc["access_expired"] is True
    # an expired access token with a living refresh token is still a usable login
    put_login(box.login, login_doc(access_expires_at=1))
    assert auth_cli.status(as_json=True) == 0
    assert json.loads(output(capfd)[0])["logged_in"] is True
    # ... until the refresh token itself has expired
    put_login(box.login, login_doc(access_expires_at=1, refresh_token_expires_at=2))
    assert auth_cli.status(as_json=True) == 1
    assert json.loads(output(capfd)[0])["reason_code"] == "login_expired"


@posix
def test_status_says_when_the_loop_uses_another_file_than_the_runtime(box, capfd, monkeypatch):
    custom = put_login(box.tmp / "service" / "login.json")
    monkeypatch.setenv("SIMPLICIO_247_LOGIN", str(custom))
    fake_runtime(box)
    auth_cli.status(as_json=True)
    doc = json.loads(output(capfd)[0])
    assert doc["shared_with_runtime"] is False and doc["path"] == str(custom)
    assert doc["runtime_path"] == str(box.login)
    auth_cli.status()
    out, _ = output(capfd)
    assert "DIFFERENT" in out


def test_status_online_runs_the_existing_subscription_check(box, capfd):
    put_login(box.login)
    seen = []

    def check():
        seen.append(1)
        return {"active": True, "reason": "ok", "tier": "pro", "status": "active", "source": "stripe", "plan": "p"}

    assert auth_cli.status(as_json=True, online=False, check=check) == 0
    assert not seen and "subscription" not in json.loads(output(capfd)[0])
    assert auth_cli.status(as_json=True, online=True, check=check) == 0
    assert seen and json.loads(output(capfd)[0])["subscription"]["reason"] == "ok"
    assert auth_cli.status(online=True, check=check) == 0
    assert "subscription: ok" in output(capfd)[0]


def test_status_online_with_an_inactive_subscription_is_exit_1(box, capfd):
    put_login(box.login)
    rc = auth_cli.status(as_json=True, online=True,
                         check=lambda: {"active": False, "reason": "subscription_required", "tier": "free"})
    assert rc == 1
    assert json.loads(output(capfd)[0])["subscription"]["reason"] == "subscription_required"


# --- the command line ------------------------------------------------------------------------------------------------


def test_the_commands_are_wired_into_simplicio_loop(box, capfd):
    assert cli.main(["auth", "status", "--json"]) == 1
    assert json.loads(output(capfd)[0])["reason_code"] == "login_missing"
    assert cli.main(["logout"]) == 2
    assert cli.main(["logout", "--yes", "--json"]) == 0
    assert json.loads(output(capfd)[0].splitlines()[-1])["status"] == "NO_LOGIN"
    assert cli.main(["login", "--json", "--no-browser"]) == 1  # no Runtime on the empty PATH
    assert json.loads(output(capfd)[0].splitlines()[-1])["status"] == "UNVERIFIED"


def test_the_watcher_setup_hint_points_at_simplicio_loop_login():
    from simplicio_loop.watcher247 import onboarding

    assert "simplicio-loop login" in onboarding.LOGIN_COMMAND
    assert onboarding.LOGIN_COMMAND in onboarding._HINTS["login_missing"]
    assert onboarding.LOGIN_COMMAND in onboarding.idle_status("login_missing")["detail"]
