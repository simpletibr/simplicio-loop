"""`simplicio-loop watch247 setup`: first-run credentials of the 24/7 watcher.

Only fake values: a fake `gh` on PATH answers `gh api -i user`, tmp paths hold the env file, the state dir and
login.json. The token is secret, so every test that prints something also checks that it is not in the output.
"""
from __future__ import annotations

import asyncio
import getpass
import io
import json
import os
import re
import stat
import sys
import warnings

import pytest

from simplicio_loop import cli_impl
from simplicio_loop.watcher247 import config, onboarding, proc, subscription
from simplicio_loop.watcher247.__main__ import main as watcher_main

from .fakes import FakeRun, read_json

REAL_SUBSCRIPTION = subscription.mcp_subscription  # captured before the `env` fixture replaces it
EMAIL = "user@example.com"
TOKEN = "ghp_FAKEtoken0000000000000000000000000001"
TOKEN_2 = "ghp_FAKEtoken0000000000000000000000000002"
TOKEN_ADMIN = "ghp_FAKEADMIN00000000000000000000000001"
TOKEN_BAD = "ghp_FAKEBAD000000000000000000000000000001"
TOKEN_FINE = "github_pat_FAKE000000000000000000000000000001"
TOKEN_NET = "ghp_FAKENET000000000000000000000000000001"

FAKE_GH = """#!/bin/sh
echo "$@" >> "{log}"
[ -n "$GH_TOKEN" ] && echo "env-token-present" >> "{log}"
scopes="repo, read:org"
case "$GH_TOKEN" in
  ghp_FAKEBAD*)
    printf 'HTTP/2.0 401 Unauthorized\\r\\n\\r\\n{{"message":"Bad credentials"}}\\n'
    echo "gh: Bad credentials (HTTP 401) $GH_TOKEN" >&2
    exit 1;;
  ghp_FAKENET*)
    printf 'error connecting to api.github.com %s\x1b[31m\\n' "$GH_TOKEN" >&2
    exit 1;;
  ghp_FAKEADMIN*) scopes="repo, admin:org, delete_repo, workflow";;
  github_pat_FAKE*)
    printf 'HTTP/2.0 200 OK\\r\\nContent-Type: application/json\\r\\n\\r\\n{{"login":"fake-user"}}\\n'
    exit 0;;
esac
printf 'HTTP/2.0 200 OK\\r\\nX-Oauth-Scopes: %s\\r\\nContent-Type: application/json\\r\\n\\r\\n{{"login":"fake-user"}}\\n' "$scopes"
"""


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """Env file, state dir, login.json and a fake gh, all under tmp_path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh.log"
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH.format(log=gh_log))
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    env_file = tmp_path / "etc" / "watcher.env"
    env_file.parent.mkdir()
    monkeypatch.setenv("SIMPLICIO_247_ENV_FILE", str(env_file))
    monkeypatch.setattr(config, "LOGIN", tmp_path / "home" / ".simplicio" / "login.json")
    original = config.STATE_DIR
    config.set_state_dir(tmp_path / "state")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    yield type("Svc", (), {
        "tmp": tmp_path, "env_file": env_file, "gh_log": gh_log, "login": config.LOGIN,
        "state": tmp_path / "state",
        "gh_calls": lambda self: gh_log.read_text().splitlines() if gh_log.exists() else [],
    })()
    config.set_state_dir(original)


def stdin(monkeypatch, text, tty=False):
    stream = io.StringIO(text)
    stream.isatty = lambda: tty
    monkeypatch.setattr(sys, "stdin", stream)


def run_setup(monkeypatch, token=TOKEN, email=EMAIL, **kwargs):
    stdin(monkeypatch, token + "\n")
    return onboarding.main(email=email, token_stdin=True, **kwargs)


def write_login(svc, email=EMAIL):
    svc.login.parent.mkdir(parents=True, exist_ok=True)
    svc.login.write_text(json.dumps({
        "access_token": "a", "refresh_token": "r", "access_expires_at": 4102444800,
        "verification": {"validated": {"user": {"email": email}}},
    }))
    svc.login.chmod(0o600)  # the login store refuses a file that group or others can read


def active_subscription(monkeypatch, tier="pro"):
    async def fake(method, url, payload=None, headers=None):
        return {"active": True, "entitlement": {
            "active": True, "status": "active", "source": "stripe", "tier": tier, "plan": "p"}}

    monkeypatch.setattr(subscription, "http_json", fake)


def assert_no_secret(capsys, caplog, *secrets):
    out, err = capsys.readouterr()
    text = out + err + caplog.text
    for secret in secrets:
        assert secret not in text


# --- the happy path ---------------------------------------------------------------------------------------------


def test_stdin_flag_stores_the_token_with_mode_600_and_reports_only_login_and_scopes(svc, monkeypatch, capsys, caplog):
    write_login(svc)
    active_subscription(monkeypatch)
    with caplog.at_level("DEBUG"):
        rc = run_setup(monkeypatch)
    out, err = capsys.readouterr()
    assert rc == 0
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN}\n"
    assert stat.S_IMODE(svc.env_file.stat().st_mode) == 0o600
    assert "fake-user" in out and "repo" in out and "read:org" in out
    assert TOKEN not in out + err + caplog.text
    assert "WARN" not in out  # repo + read:org is not broader than needed


def test_the_token_reaches_gh_through_the_child_environment_only(svc, monkeypatch):
    calls = []
    real = proc.run

    async def spy(argv, **kwargs):
        calls.append((list(argv), dict(kwargs.get("env") or {})))
        return await real(argv, **kwargs)

    monkeypatch.setattr(proc, "run", spy)
    run_setup(monkeypatch)
    assert calls and all(TOKEN not in " ".join(argv) for argv, _ in calls)
    assert calls[0][0][:2] == ["gh", "api"]
    assert calls[0][1]["GH_TOKEN"] == TOKEN
    assert "GITHUB_TOKEN" not in calls[0][1]
    assert "env-token-present" in svc.gh_calls()
    assert not any(TOKEN in line for line in svc.gh_calls())


def test_the_token_is_in_no_file_but_the_env_file(svc, monkeypatch, capsys, caplog):
    write_login(svc)
    active_subscription(monkeypatch)
    with caplog.at_level("DEBUG"):
        run_setup(monkeypatch)
    leaks = [p for p in svc.tmp.rglob("*") if p.is_file() and p != svc.env_file and TOKEN in p.read_text(errors="replace")]
    assert leaks == []
    assert_no_secret(capsys, caplog, TOKEN)


def test_a_second_run_replaces_the_token_instead_of_duplicating_it(svc, monkeypatch):
    run_setup(monkeypatch, TOKEN)
    run_setup(monkeypatch, TOKEN_2)
    lines = svc.env_file.read_text().splitlines()
    assert lines == [f"GH_TOKEN={TOKEN_2}"]


def test_other_lines_are_kept_and_the_token_line_keeps_its_place(svc):
    svc.env_file.write_text(f"HOME=/home/x\n# a comment\nGH_TOKEN={TOKEN}\nGH_TOKEN=dup\nPATH=/bin")
    svc.env_file.chmod(0o600)
    onboarding.store_token(svc.env_file, TOKEN_2)
    assert svc.env_file.read_text() == f"HOME=/home/x\n# a comment\nGH_TOKEN={TOKEN_2}\nPATH=/bin\n"
    assert stat.S_IMODE(svc.env_file.stat().st_mode) == 0o600


def test_the_account_email_is_recorded_non_secret_in_the_state_dir(svc, monkeypatch):
    run_setup(monkeypatch)
    record = svc.state / "account.json"
    assert json.loads(record.read_text())["email"] == EMAIL
    assert TOKEN not in record.read_text()
    assert stat.S_IMODE(record.stat().st_mode) == 0o600


# --- the write of the env file ------------------------------------------------------------------------------------


def test_the_write_is_mode_600_even_under_a_hostile_umask(svc):
    old = os.umask(0o277)  # without an explicit chmod the temp file would be 0400
    try:
        onboarding.store_token(svc.env_file, TOKEN)
    finally:
        os.umask(old)
    assert stat.S_IMODE(svc.env_file.stat().st_mode) == 0o600


def test_the_temp_file_is_private_when_the_content_is_written(svc, monkeypatch):
    seen = []
    real_fdopen = os.fdopen

    def spy(fd, *args, **kwargs):
        seen.append(stat.S_IMODE(os.fstat(fd).st_mode))
        return real_fdopen(fd, *args, **kwargs)

    monkeypatch.setattr(os, "fdopen", spy)
    old = os.umask(0o277)
    try:
        onboarding.store_token(svc.env_file, TOKEN)
    finally:
        os.umask(old)
    assert seen == [0o600]


def test_a_symlink_put_in_place_after_the_check_is_never_read_through_or_replaced(svc):
    target = svc.tmp / "secret-elsewhere"
    target.write_text("ROOT_ONLY_SECRET=1\n")
    svc.env_file.write_text("A=1\n")
    svc.env_file.chmod(0o600)
    onboarding.check_target(svc.env_file)  # passes: a regular file
    svc.env_file.unlink()
    svc.env_file.symlink_to(target)  # the race: swapped between check and write
    with pytest.raises(onboarding.Refused, match="symlink"):
        onboarding.store_token(svc.env_file, TOKEN)
    assert target.read_text() == "ROOT_ONLY_SECRET=1\n"  # not written, and not copied into a new file
    assert svc.env_file.is_symlink()
    assert sorted(p.name for p in svc.env_file.parent.iterdir()) == [svc.env_file.name]  # no temp file left


def test_a_fifo_put_in_place_after_the_check_does_not_hang_setup(svc):
    os.mkfifo(svc.env_file)
    with pytest.raises(onboarding.Refused, match="regular file"):
        onboarding.store_token(svc.env_file, TOKEN)


def test_a_failed_replace_leaves_the_old_file_and_no_temp_file(svc, monkeypatch):
    svc.env_file.write_text("A=1\n")
    svc.env_file.chmod(0o600)

    def boom(*args):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        onboarding.store_token(svc.env_file, TOKEN)
    assert svc.env_file.read_text() == "A=1\n"
    assert [p.name for p in svc.env_file.parent.iterdir()] == [svc.env_file.name]


@pytest.mark.parametrize("mode", [0o640, 0o660, 0o604, 0o644, 0o666])
def test_a_group_or_world_readable_env_file_is_refused_with_the_exact_fix(svc, monkeypatch, capsys, caplog, mode):
    svc.env_file.write_text("A=1\n")
    svc.env_file.chmod(mode)
    rc = run_setup(monkeypatch)
    out, err = capsys.readouterr()
    assert rc == 2
    assert f"chmod 600 {svc.env_file}" in out + err
    assert svc.env_file.read_text() == "A=1\n"
    assert svc.gh_calls() == []  # refused before any network call
    assert TOKEN not in out + err + caplog.text


def test_a_symlinked_env_file_is_refused(svc, monkeypatch, capsys):
    target = svc.tmp / "elsewhere.env"
    target.write_text("A=1\n")
    target.chmod(0o600)
    svc.env_file.symlink_to(target)
    assert run_setup(monkeypatch) == 2
    assert target.read_text() == "A=1\n"
    assert "symlink" in "".join(capsys.readouterr())
    assert svc.gh_calls() == []  # refused before the token goes anywhere


def test_a_missing_directory_is_a_clear_error(svc, monkeypatch, capsys):
    monkeypatch.setenv("SIMPLICIO_247_ENV_FILE", str(svc.tmp / "nope" / "watcher.env"))
    assert run_setup(monkeypatch) == 2
    out, err = capsys.readouterr()
    assert "nope" in out + err and TOKEN not in out + err


def test_a_directory_the_user_cannot_write_is_refused_before_any_network_call(svc, monkeypatch, capsys):
    monkeypatch.setattr(os, "access", lambda path, mode: False)
    assert run_setup(monkeypatch) == 2
    out, err = capsys.readouterr()
    assert "run as root" in out + err and TOKEN not in out + err
    assert svc.gh_calls() == [] and not svc.env_file.exists()


# --- hostile input -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("token", [
    "ghp_FAKEtoken00000000000000000\nINJECT=1",
    "ghp_FAKEtoken00000000000000000\r\nINJECT=1",
    "ghp_FAKEtoken0000000000000\x00000000",
    "ghp_FAKEtoken00000000000000000 " + "x",
    "ghp_FAKEtoken00000000000000000$(id)",
    "ghp_FAKE'token0000000000000000000",
    'ghp_FAKE"token0000000000000000000',
    "ghp_FAKEtoken00000000000000\\000",
    "ghp_FAKE#token0000000000000000000",
    "ghp_" + "A" * 5000,
    "short",
    "",
    "   ",
])
def test_a_hostile_token_is_rejected_before_any_call_or_write(svc, monkeypatch, capsys, caplog, token):
    stdin(monkeypatch, token + "\n")
    rc = onboarding.main(email=EMAIL, token_stdin=True)
    out, err = capsys.readouterr()
    assert rc == 2
    assert not svc.env_file.exists()
    assert svc.gh_calls() == []
    assert "INJECT" not in out + err and "\x00" not in out + err
    assert token.strip() == "" or token not in out + err + caplog.text


@pytest.mark.parametrize("email", [
    "user@example.com\nX=1", "user@example.com\x00", "u\x1b[31m@example.com", "a" * 300 + "@example.com",
    "no-at-sign", "a@@example.com", "a b@example.com", "a@example", "@example.com", "a@", "", "  ",
    "a@exa mple.com", "a@example.com;rm -rf", "<a>@example.com",
])
def test_a_hostile_email_is_rejected_before_any_call_or_write(svc, monkeypatch, capsys, email):
    stdin(monkeypatch, TOKEN + "\n")
    rc = onboarding.main(email=email, token_stdin=True)
    out, err = capsys.readouterr()
    assert rc == 2
    assert not svc.env_file.exists() and not (svc.state / "account.json").exists()
    assert svc.gh_calls() == []
    assert "\x1b" not in out + err and "\x00" not in out + err  # the bad value is never echoed to the terminal


# --- how the token and e-mail are read ---------------------------------------------------------------------------


def test_without_a_tty_and_without_the_stdin_flag_setup_refuses(svc, monkeypatch, capsys):
    stdin(monkeypatch, TOKEN + "\n", tty=False)
    rc = onboarding.main(email=EMAIL)
    out, err = capsys.readouterr()
    assert rc == 2
    assert "--github-token-stdin" in out + err
    assert not svc.env_file.exists() and svc.gh_calls() == []
    assert TOKEN not in out + err


def test_the_stdin_flag_without_a_tty_needs_the_email_flag(svc, monkeypatch, capsys):
    stdin(monkeypatch, TOKEN + "\n", tty=False)
    rc = onboarding.main(token_stdin=True)
    assert rc == 2 and "--email" in "".join(capsys.readouterr())
    assert not svc.env_file.exists()


def refused_by_the_parser(svc, capsys, caplog, argv):
    """Run the CLI with ``argv``: it must exit 2 before any call or write, printing nothing of what was typed."""
    def must_not_run(*args, **kwargs):
        raise AssertionError("an action ran with a token slip in argv")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(onboarding, "main", must_not_run)
        patch.setattr("simplicio_loop.watcher247.login_check.main", must_not_run)
        patch.setattr("simplicio_loop.watcher247.__main__.main", must_not_run)
        with pytest.raises(SystemExit) as exit_info:
            cli_impl.main(argv)
    out, err = capsys.readouterr()
    assert exit_info.value.code == 2
    shown = out + err + caplog.text
    for secret in (TOKEN, TOKEN_2, "ghp_FAKE"):
        assert secret not in shown
    assert not svc.env_file.exists() and svc.gh_calls() == []
    return shown


def test_the_token_is_never_accepted_as_a_command_line_value(svc, monkeypatch, capsys, caplog):
    shown = refused_by_the_parser(svc, capsys, caplog, ["watch247", "setup", "--email", EMAIL, "--github-token", TOKEN])
    assert "--github-token-stdin" in shown


def test_the_token_argument_is_refused_even_when_a_token_is_piped_too(svc, monkeypatch, capsys, caplog):
    stdin(monkeypatch, TOKEN_2 + "\n")
    argv = ["watch247", "setup", "--email", EMAIL, "--github-token-stdin", "--github-token", TOKEN]
    refused_by_the_parser(svc, capsys, caplog, argv)


# Every way a token can land in argv by a slip of the keys. argparse repeats the offending value in its own error
# ("ignored explicit argument", "invalid choice", "unrecognized arguments", "ambiguous option"): none may reach the terminal.
TOKEN_SLIPS = [
    pytest.param([f"--github-token-stdin={TOKEN}"], id="stdin-equals-value"),
    pytest.param(["--github-token-stdin="], id="stdin-equals-empty"),
    pytest.param(["--github-token-stdin", TOKEN], id="stdin-then-value"),
    pytest.param([TOKEN, "--github-token-stdin"], id="value-then-stdin"),
    pytest.param(["--github-token-stdin", f"--github-token-stdin={TOKEN}"], id="stdin-twice"),
    pytest.param(["--github-token-s", TOKEN], id="abbrev-s"),
    pytest.param(["--github-token-st", TOKEN], id="abbrev-st"),
    pytest.param(["--github-token-std", TOKEN], id="abbrev-std"),
    pytest.param([f"--github-token-s={TOKEN}"], id="abbrev-s-equals"),
    pytest.param([f"--github-token-stdi={TOKEN}"], id="abbrev-stdi-equals"),
    pytest.param(["--github-token", TOKEN], id="token"),
    pytest.param([f"--github-token={TOKEN}"], id="token-equals"),
    pytest.param(["--github-tok", TOKEN], id="abbrev-tok"),
    pytest.param(["--github-t", TOKEN], id="abbrev-t"),
    pytest.param(["--github", TOKEN], id="abbrev-github"),
    pytest.param([f"--git={TOKEN}"], id="abbrev-git-equals"),
    pytest.param([f"--g={TOKEN}"], id="abbrev-g-equals"),
    pytest.param(["--github-tokens", TOKEN], id="extra-letter"),
    pytest.param([f"--github-tokenstdin={TOKEN}"], id="missing-dash"),
    pytest.param(["--github-token-stdin-x", TOKEN], id="suffix"),
    pytest.param([f"--github-token{TOKEN}"], id="glued"),
    pytest.param([f"--GITHUB-TOKEN={TOKEN}"], id="upper-case"),
    pytest.param([f"--github_token={TOKEN}"], id="underscore"),
    pytest.param([f"--ghp-token={TOKEN}"], id="other-name"),
    pytest.param([f"-github-token={TOKEN}"], id="single-dash"),
    pytest.param(["--token", TOKEN], id="token-flag"),
    pytest.param(["--github-token-s"], id="abbrev-s-alone"),
    pytest.param(["--github-token-std"], id="abbrev-std-alone"),
    pytest.param(["--git"], id="abbrev-git-alone"),
    pytest.param(["--em", EMAIL], id="abbrev-email"),
    pytest.param([TOKEN], id="bare-value"),
    pytest.param(["--", TOKEN], id="after-double-dash"),
    pytest.param(["--email", EMAIL, TOKEN], id="after-email"),
    pytest.param(["--state-dir", TOKEN, f"--github-token-stdin={TOKEN}"], id="state-dir-and-slip"),
]


@pytest.mark.parametrize("slip", TOKEN_SLIPS)
def test_a_token_typed_into_a_mistyped_flag_is_refused_without_being_echoed(svc, monkeypatch, capsys, caplog, slip):
    stdin(monkeypatch, TOKEN_2 + "\n")
    shown = refused_by_the_parser(svc, capsys, caplog, ["watch247", "setup", "--email", EMAIL, *slip])
    assert "--github-token-stdin" in shown  # the way out is named


@pytest.mark.parametrize("slip", TOKEN_SLIPS)
def test_the_slip_is_refused_when_it_comes_before_the_email_and_without_the_setup_word(svc, monkeypatch, capsys, caplog, slip):
    refused_by_the_parser(svc, capsys, caplog, ["watch247", *slip, "setup", "--email", EMAIL])
    refused_by_the_parser(svc, capsys, caplog, ["watch247", *slip])


@pytest.mark.parametrize("slip", [
    pytest.param(["watch247", TOKEN], id="token-as-action"),
    pytest.param(["watch247", "setup", TOKEN], id="token-after-setup"),
    pytest.param(["watch247", "login-check", f"--github-token-stdin={TOKEN}"], id="login-check"),
    pytest.param(["watch247", "--once", f"--github-token={TOKEN}"], id="watcher-loop"),
    pytest.param(["watch247", "--dry-run", "--github-token", TOKEN], id="watcher-dry-run"),
])
def test_no_watch247_action_runs_after_a_token_slip(svc, monkeypatch, capsys, caplog, slip):
    refused_by_the_parser(svc, capsys, caplog, slip)


@pytest.mark.parametrize("slip", [
    pytest.param([f"--github-token-stdin={TOKEN}"], id="stdin-equals-value"),
    pytest.param(["--github-token", TOKEN], id="token"),
    pytest.param([f"--github-token-s={TOKEN}"], id="abbrev"),
])
def test_a_slip_typed_before_the_subcommand_is_not_echoed_either(svc, monkeypatch, capsys, caplog, slip):
    refused_by_the_parser(svc, capsys, caplog, [*slip, "watch247", "setup", "--email", EMAIL])


def test_the_slip_never_reaches_the_terminal_of_the_real_command(svc, tmp_path):
    """End to end, as the user runs it: a subprocess, so the real stdout/stderr and the real exit code."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for slip in ([f"--github-token-stdin={TOKEN}"], ["--github-token-s", TOKEN], ["--github-token-stdin", TOKEN]):
        done = subprocess.run(
            [sys.executable, "-c", "import sys; from simplicio_loop.cli_impl import main; sys.exit(main(sys.argv[1:]))",
             "watch247", "setup", "--email", EMAIL, *slip],
            input=TOKEN_2 + "\n", capture_output=True, text=True, cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": root, "SIMPLICIO_247_ENV_FILE": str(svc.env_file)})
        assert done.returncode == 2, slip
        assert "ghp_FAKE" not in done.stdout + done.stderr, slip
        assert "--github-token-stdin" in done.stdout + done.stderr, slip
    assert not svc.env_file.exists()


def test_the_exact_stdin_flag_and_the_other_options_are_still_accepted(svc, monkeypatch):
    stdin(monkeypatch, TOKEN + "\n")
    argv = ["watch247", "setup", "--email", EMAIL, "--github-token-stdin", "--state-dir", str(svc.state)]
    assert cli_impl.main(argv) == 1
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN}\n"


def test_the_other_commands_keep_the_standard_argparse_errors(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli_impl.main(["status", "--repo"])
    assert exit_info.value.code == 2
    assert "expected one argument" in capsys.readouterr().err


def test_interactive_mode_asks_for_a_visible_email_and_a_hidden_token(svc, monkeypatch, capsys, caplog):
    stdin(monkeypatch, "", tty=True)
    asked = {"input": [], "getpass": []}
    monkeypatch.setattr("builtins.input", lambda prompt="": asked["input"].append(prompt) or EMAIL)
    monkeypatch.setattr(getpass, "getpass", lambda prompt="Password: ", stream=None: asked["getpass"].append(prompt) or TOKEN)
    with caplog.at_level("DEBUG"):
        onboarding.main()
    assert len(asked["input"]) == 1 and len(asked["getpass"]) == 1
    assert "e-mail" in asked["input"][0].lower() and "token" in asked["getpass"][0].lower()
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN}\n"
    assert json.loads((svc.state / "account.json").read_text())["email"] == EMAIL
    assert_no_secret(capsys, caplog, TOKEN)


def test_interactive_mode_refuses_when_the_terminal_cannot_hide_the_input(svc, monkeypatch, capsys):
    stdin(monkeypatch, "", tty=True)

    def echoing(prompt="", stream=None):
        warnings.warn("Can not control echo on the terminal.", getpass.GetPassWarning)
        return TOKEN

    monkeypatch.setattr(getpass, "getpass", echoing)
    rc = onboarding.main(email=EMAIL)
    assert rc == 2 and not svc.env_file.exists()
    assert TOKEN not in "".join(capsys.readouterr())


def test_the_command_is_wired_into_the_cli(svc, monkeypatch):
    stdin(monkeypatch, TOKEN + "\n")
    rc = cli_impl.main(["watch247", "setup", "--email", EMAIL, "--github-token-stdin", "--state-dir", str(svc.state)])
    assert rc == 1  # no login.json yet: the token is stored, the login is the next step
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN}\n"


# --- what gh says about the token --------------------------------------------------------------------------------


def test_a_rejected_token_is_not_stored(svc, monkeypatch, capsys, caplog):
    with caplog.at_level("DEBUG"):
        rc = run_setup(monkeypatch, TOKEN_BAD)
    out, err = capsys.readouterr()
    assert rc == 1
    assert not svc.env_file.exists()
    assert "401" in out + err
    assert TOKEN_BAD not in out + err + caplog.text  # gh echoed it on stderr: it must be redacted


def test_a_gh_failure_without_an_http_status_is_shown_without_the_token_or_control_characters(svc, monkeypatch, capsys, caplog):
    with caplog.at_level("DEBUG"):
        rc = run_setup(monkeypatch, TOKEN_NET)
    out, err = capsys.readouterr()
    assert rc == 1 and not svc.env_file.exists()
    assert "error connecting" in out and "***" in out
    assert TOKEN_NET not in out + err + caplog.text and "\x1b" not in out + err


@pytest.mark.parametrize("make", [
    lambda t: "bad " + "".join(t[i:i + 3] + "\x1b[0m" for i in range(0, len(t), 3)),  # colour between its characters
    lambda t: "bad " + "".join(c + "\r" for c in t),  # a carriage return after each character
    lambda t: "bad " + "\x00".join(t),  # NUL between the characters
    lambda t: "\x1b]0;" + t + "\x07 title",  # terminal title (OSC)
    lambda t: "bad \x1b[31m" + t + "\x1b[0m end",  # colour around it
    lambda t: "progress 100%\r" + t + "\rDONE",  # a spinner line
    lambda t: "bad é" + t + "é",
    lambda t: "part1 " + t[:8] + "\npart2 " + t[8:],  # echoed in two pieces
])
def test_gh_text_is_cleaned_before_the_token_is_redacted(make):
    shown = onboarding._plain(make(TOKEN), TOKEN)
    letters = re.sub(r"[^A-Za-z0-9_-]", "", shown)  # what a reader sees once the noise between its characters is ignored
    assert TOKEN[:12] not in letters and TOKEN[12:] not in letters
    assert TOKEN[:8] not in shown and TOKEN[-8:] not in shown
    assert all(" " <= c <= "~" for c in shown) and len(shown) <= 200


def test_a_missing_gh_is_a_clear_error(svc, monkeypatch, capsys):
    stdin(monkeypatch, TOKEN + "\n")
    monkeypatch.setenv("PATH", str(svc.tmp / "empty"))
    rc = onboarding.main(email=EMAIL, token_stdin=True)
    assert rc == 1 and "gh" in "".join(capsys.readouterr())
    assert not svc.env_file.exists()


def test_broad_scopes_warn_and_do_not_fail(svc, monkeypatch, capsys):
    write_login(svc)
    active_subscription(monkeypatch)
    rc = run_setup(monkeypatch, TOKEN_ADMIN)
    out = capsys.readouterr().out
    assert rc == 0 and svc.env_file.read_text() == f"GH_TOKEN={TOKEN_ADMIN}\n"
    assert "WARN" in out
    for scope in ("admin:org", "delete_repo", "workflow"):
        assert scope in out
    assert "fine-grained" in out
    assert TOKEN_ADMIN not in out


def test_a_fine_grained_token_has_no_scope_header_and_no_warning(svc, monkeypatch, capsys):
    run_setup(monkeypatch, TOKEN_FINE)
    out = capsys.readouterr().out
    assert "WARN" not in out and "fine-grained" in out
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN_FINE}\n"


@pytest.mark.parametrize("scope,broad", [
    ("repo", False), ("read:org", False), ("public_repo", False),
    ("admin:org", True), ("admin:repo_hook", True), ("delete_repo", True), ("workflow", True),
    ("write:packages", True), ("delete:packages", True), ("codespace", True),
])
def test_scope_classification(scope, broad):
    assert onboarding.is_broad(scope) is broad


# --- the Simplicio account ----------------------------------------------------------------------------------------


def test_without_login_json_setup_prints_the_exact_command_for_the_service_user(svc, monkeypatch, capsys):
    rc = run_setup(monkeypatch)
    out = capsys.readouterr().out
    assert rc == 1
    assert "login_missing" in out
    assert "sudo -u simplicio-loop -H simplicio-loop login" in out
    assert "systemctl restart simplicio-loop-247" in out  # the new token loads at service start


def test_an_active_subscription_for_the_same_account_is_ok(svc, monkeypatch, capsys):
    write_login(svc, "User@Example.com")  # the compare ignores case
    active_subscription(monkeypatch)
    assert run_setup(monkeypatch) == 0
    assert "Simplicio subscription: ok" in capsys.readouterr().out


def test_a_login_of_another_account_is_reported_without_printing_either_address(svc, monkeypatch, capsys):
    write_login(svc, "someone-else@example.org")
    active_subscription(monkeypatch)
    rc = run_setup(monkeypatch)
    out, err = capsys.readouterr()
    assert rc == 1
    assert "account_mismatch" in out
    assert "someone-else@example.org" not in out + err


def test_a_free_tier_reports_subscription_required(svc, monkeypatch, capsys):
    write_login(svc)
    active_subscription(monkeypatch, tier="free")
    assert run_setup(monkeypatch) == 1
    assert "subscription_required" in capsys.readouterr().out


def test_a_root_run_keeps_the_owner_of_login_json(svc, monkeypatch):
    write_login(svc)
    active_subscription(monkeypatch)
    before = svc.login.stat()
    chowned = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(os, "chown", lambda path, uid, gid, follow_symlinks=True:
                        chowned.append((str(path), uid, gid, follow_symlinks)))
    run_setup(monkeypatch)
    # follow_symlinks=False: a symlink put at login.json during the network call is chowned itself, never its target
    assert chowned == [(str(svc.login), before.st_uid, before.st_gid, False)]


def test_check_reports_the_account_step_after_the_login_without_asking_for_a_token(svc, monkeypatch, capsys):
    run_setup(monkeypatch)  # records the e-mail; login.json does not exist yet
    capsys.readouterr()
    write_login(svc)
    active_subscription(monkeypatch)
    svc.gh_log.unlink()
    stdin(monkeypatch, "", tty=False)
    assert onboarding.main(check_only=True) == 0  # the e-mail comes from account.json
    assert "Simplicio subscription: ok" in capsys.readouterr().out
    assert svc.gh_calls() == []  # no gh call: the token is not touched
    assert svc.env_file.read_text() == f"GH_TOKEN={TOKEN}\n"


def test_check_needs_a_recorded_or_given_email(svc, monkeypatch, capsys):
    assert onboarding.main(check_only=True) == 2
    assert "--email" in capsys.readouterr().out
    write_login(svc, "someone-else@example.org")
    active_subscription(monkeypatch)
    assert onboarding.main(email=EMAIL, check_only=True) == 1
    assert "account_mismatch" in capsys.readouterr().out
    assert onboarding.main(email="bad\nvalue", check_only=True) == 2


def test_check_is_wired_into_the_cli(svc, monkeypatch, capsys):
    write_login(svc)
    active_subscription(monkeypatch)
    assert cli_impl.main(["watch247", "setup", "--check", "--email", EMAIL, "--state-dir", str(svc.state)]) == 0
    assert "Simplicio subscription: ok" in capsys.readouterr().out
    assert not svc.env_file.exists() and svc.gh_calls() == []


# --- the watcher without credentials ------------------------------------------------------------------------------


def test_a_watcher_without_a_github_token_stays_idle_and_says_what_to_run(env, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fake = env(FakeRun({"simplicio-a": []}))
    rc = asyncio.run(watcher_main(once=True))
    status = read_json(config.STATUS)
    assert rc == 0  # no crash: Restart=always would loop on one
    assert fake.calls == []
    assert status["phase"] == "setup_required"
    assert status["reason_code"] == "github_token_missing"
    assert status["command"] == "simplicio-loop watch247 setup"


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_github_token_counts_as_missing(env, monkeypatch, value):
    monkeypatch.setenv("GH_TOKEN", value)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    env(FakeRun({"simplicio-a": []}))
    asyncio.run(watcher_main(once=True))
    assert read_json(config.STATUS)["reason_code"] == "github_token_missing"


def test_github_token_in_the_environment_lets_the_tick_run(env, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    fake = env(FakeRun({"simplicio-a": []}))
    asyncio.run(watcher_main(once=True))
    assert fake.ran("gh", "repo", "list")  # gh was asked for the repos
    assert read_json(config.STATUS)["phase"] != "setup_required"


def test_a_dry_run_without_a_github_token_writes_nothing(env, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    fake = env(FakeRun({"simplicio-a": []}))
    assert asyncio.run(watcher_main(once=True, dry_run=True)) == 0
    assert fake.calls == [] and not config.STATUS.exists()


def test_a_watcher_without_login_json_says_login_missing_and_the_command(env, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LOGIN", tmp_path / "no-such-login.json")
    monkeypatch.setattr(subscription, "mcp_subscription", REAL_SUBSCRIPTION)
    fake = env(FakeRun({"simplicio-a": []}))
    assert asyncio.run(watcher_main(once=True)) == 0
    status = read_json(config.STATUS)
    assert fake.calls == []
    assert status["phase"] == "setup_required" and status["reason_code"] == "login_missing"
    assert status["command"] == "simplicio-loop watch247 setup"


def test_the_status_never_carries_a_token(env, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    monkeypatch.setattr(subscription, "mcp_subscription", REAL_SUBSCRIPTION)
    monkeypatch.setattr(config, "LOGIN", config.ROOT / "no-such-login.json")
    env(FakeRun({"simplicio-a": []}))
    asyncio.run(watcher_main(once=True))
    assert TOKEN not in config.STATUS.read_text()
