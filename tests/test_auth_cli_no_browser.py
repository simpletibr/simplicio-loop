"""`simplicio-loop login --no-browser` (#1670): a Runtime that opens the browser and ignores BROWSER must not open it."""
import json
import os
import signal
import subprocess
import threading
from pathlib import Path

import pytest

from simplicio_loop import auth_cli

# the code is percent-encoded so that it does not appear verbatim in the address
URL = "https://example.test/simplicio/login?user_code=ABCD%2D1234"
CODE = "ABCD-1234"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX opener stand-ins")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    real_bin = tmp_path / "real-bin"
    real_bin.mkdir()
    called = tmp_path / "xdg-open-called"
    opener = real_bin / "xdg-open"
    opener.write_text(f'#!/bin/sh\necho "$@" > "{called}"\n')
    opener.chmod(0o755)
    monkeypatch.setattr(auth_cli.auth, "runtime_binary", lambda *args, **kwargs: Path("/bin/true"))
    env = {"PATH": f"{real_bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home")}
    return env, called


def _runtime_that_opens_the_browser(command, env, stdout):
    """Imitates Runtime 3.10.0: calls xdg-open and ignores BROWSER."""
    subprocess.call(["xdg-open", URL], env=env)
    return 0


def test_without_the_option_the_fake_runtime_opens_the_browser(sandbox):
    env, called = sandbox
    auth_cli.login(as_json=True, environ=env, run=_runtime_that_opens_the_browser)
    assert called.exists()


def test_no_browser_does_not_call_the_opener_and_reports_url_and_code_in_json(sandbox, capsys):
    env, called = sandbox
    auth_cli.login(as_json=True, no_browser=True, environ=env, run=_runtime_that_opens_the_browser)
    doc = json.loads(capsys.readouterr().out)
    assert not called.exists()
    assert doc["sign_in_url"] == URL
    assert doc["user_code"] == CODE


def test_no_browser_reports_url_and_code_in_text(sandbox, capsys):
    env, called = sandbox
    auth_cli.login(no_browser=True, environ=env, run=_runtime_that_opens_the_browser)
    out = capsys.readouterr().out
    assert not called.exists()
    assert f"Open this address in a browser to sign in: {URL}" in out
    assert f"Code: {CODE}" in out.splitlines()


def test_no_browser_that_cannot_be_honored_exits_2_with_the_reason(sandbox, monkeypatch, capsys):
    env, called = sandbox
    monkeypatch.setattr(auth_cli, "_can_block_browser", lambda: False)

    def never(command, env, stdout):
        raise AssertionError("the Runtime must not run")

    code = auth_cli.login(as_json=True, no_browser=True, environ=env, run=never)
    doc = json.loads(capsys.readouterr().out)
    assert code == 2
    assert doc["reason_code"] == "no_browser_unsupported"
    assert "Runtime" in doc["detail"]
    assert not called.exists()


# --- review fixes (#1670) --------------------------------------------------------------------------------------------


def _shim_dir(env):
    return Path(env["PATH"].split(os.pathsep)[0])


def _login_json(env, run, capsys):
    code = auth_cli.login(as_json=True, no_browser=True, environ=env, run=run)
    return code, json.loads(capsys.readouterr().out)


def _calling(*argv_list):
    """A Runtime that runs the stand-ins by their absolute path, with the given argument lists."""
    def run(command, env, stdout):
        for argv in argv_list:
            subprocess.call([str(_shim_dir(env) / argv[0]), *argv[1:]], env=env)
        return 0
    return run


@pytest.mark.parametrize("path", [None, ""])
def test_missing_or_empty_path_leaves_no_empty_entry_and_runs_nothing_from_the_cwd(tmp_path, monkeypatch, capsys, path):
    monkeypatch.setattr(auth_cli.auth, "runtime_binary", lambda *args, **kwargs: Path("/bin/true"))
    planted = tmp_path / "cwd"
    planted.mkdir()
    ran = tmp_path / "planted-ran"
    (planted / "dirname").write_text(f'#!/bin/sh\necho x > "{ran}"\n')
    (planted / "dirname").chmod(0o755)
    env = {"HOME": str(tmp_path / "home")}
    if path is not None:
        env["PATH"] = path
    seen = {}

    def run(command, child, stdout):
        seen["path"] = child["PATH"]
        subprocess.call([str(_shim_dir(child) / "xdg-open"), URL], env=child, cwd=planted)
        return 0

    _, doc = _login_json(env, run, capsys)
    assert "" not in seen["path"].split(os.pathsep)
    assert not ran.exists()
    assert doc["sign_in_url"] == URL


def test_a_non_empty_path_is_kept_after_the_stand_ins(sandbox, capsys):
    env, _ = sandbox
    seen = {}

    def run(command, child, stdout):
        seen["path"] = child["PATH"]
        return 0

    _login_json(env, run, capsys)
    assert seen["path"].split(os.pathsep)[1:] == env["PATH"].split(os.pathsep)


@pytest.mark.parametrize("url", ["http://[::1/login?user_code=A", "https://[::1/x"])
def test_a_malformed_address_is_no_sign_in_not_a_crash(sandbox, capsys, url):
    env, _ = sandbox
    _, doc = _login_json(env, _calling(["xdg-open", url]), capsys)
    assert "sign_in_url" not in doc and "user_code" not in doc
    assert doc["runtime_exit_code"] == 0 and "status" in doc


def test_invalid_bytes_in_the_sign_in_file_are_no_sign_in_not_a_crash(sandbox, capsys):
    env, _ = sandbox

    def run(command, child, stdout):
        (_shim_dir(child) / "sign-in-url").write_bytes(b"\xff\xfe")
        return 0

    _, doc = _login_json(env, run, capsys)
    assert "sign_in_url" not in doc and doc["runtime_exit_code"] == 0


def _spy_on_the_directory(seen, inner):
    def run(command, child, stdout):
        seen["dir"] = _shim_dir(child)
        assert seen["dir"].is_dir()
        return inner(command, child, stdout)
    return run


def test_the_temp_dir_is_removed_after_success(sandbox, capsys):
    env, _ = sandbox
    seen = {}
    _login_json(env, _spy_on_the_directory(seen, _runtime_that_opens_the_browser), capsys)
    assert not seen["dir"].exists()


def test_the_temp_dir_is_removed_when_the_runtime_raises(sandbox):
    env, _ = sandbox
    seen = {}

    def boom(command, child, stdout):
        (_shim_dir(child) / "sign-in-url").write_text(URL)
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        auth_cli.login(as_json=True, no_browser=True, environ=env, run=_spy_on_the_directory(seen, boom))
    assert not seen["dir"].exists()


def _sentinel(signum, frame):
    raise AssertionError("the sentinel handler must not be called")


@pytest.fixture
def sentinel_handlers():
    """Handlers of our own, so that a handler leaked by another test cannot hide a missing restore."""
    saved = {s: signal.signal(s, _sentinel) for s in (signal.SIGTERM, signal.SIGHUP)}
    yield
    for s, handler in saved.items():
        signal.signal(s, handler)


def test_the_handlers_come_back_after_success(sandbox, sentinel_handlers):
    env, _ = sandbox
    auth_cli.login(as_json=True, no_browser=True, environ=env, run=_runtime_that_opens_the_browser)
    assert signal.getsignal(signal.SIGTERM) is _sentinel and signal.getsignal(signal.SIGHUP) is _sentinel


@pytest.mark.parametrize("name", ["SIGTERM", "SIGHUP"])
def test_the_temp_dir_is_removed_on_a_termination_signal_and_the_handlers_come_back(sandbox, sentinel_handlers, name):
    env, _ = sandbox
    sig = getattr(signal, name)
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    seen = {}

    def killed(command, child, stdout):
        (_shim_dir(child) / "sign-in-url").write_text(URL)
        os.kill(os.getpid(), sig)
        raise AssertionError("the signal must interrupt the login")

    with pytest.raises(BaseException) as raised:
        auth_cli.login(as_json=True, no_browser=True, environ=env, run=_spy_on_the_directory(seen, killed))
    assert not isinstance(raised.value, AssertionError)
    assert not seen["dir"].exists()
    assert {s: signal.getsignal(s) for s in before} == before


def test_without_the_option_the_signal_handlers_are_not_touched(sandbox):
    env, _ = sandbox
    seen = {}

    def run(command, child, stdout):
        seen["term"] = signal.getsignal(signal.SIGTERM)
        return 0

    before = signal.getsignal(signal.SIGTERM)
    auth_cli.login(as_json=True, environ=env, run=run)
    assert seen["term"] == before


def test_no_browser_works_outside_the_main_thread(sandbox, capsys):
    env, _ = sandbox
    result = {}

    def work():
        try:
            result["code"] = auth_cli.login(as_json=True, no_browser=True, environ=env,
                                            run=_runtime_that_opens_the_browser)
        except BaseException as exc:  # noqa: BLE001 - the test reports whatever happened
            result["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert "error" not in result
    assert json.loads(capsys.readouterr().out)["sign_in_url"] == URL


def test_calls_without_an_address_are_ignored_and_the_first_address_wins(sandbox, capsys):
    env, _ = sandbox
    run = _calling(["gio", "mount", "-l"], ["xdg-open", URL], ["gio", "trash", "x"], ["xdg-open", "https://other.test/a"])
    _, doc = _login_json(env, run, capsys)
    assert doc["sign_in_url"] == URL


def test_a_call_with_no_address_leaves_no_sign_in(sandbox, capsys):
    env, _ = sandbox
    _, doc = _login_json(env, _calling(["gio", "mount", "-l"], ["xdg-open", "file:///etc/passwd"]), capsys)
    assert "sign_in_url" not in doc


@pytest.mark.parametrize("url", [
    "https://example.test/\x1b]0;pwned\x07",
    "https://example.test/\x1b[2J",
    "https://example.test/a\nFAKE LINE",
    "https://example.test/a b",
    "https://example.test/café",
    "ftp://example.test/a",
])
def test_an_address_that_is_not_printable_ascii_http_is_no_address(sandbox, capsys, url):
    env, _ = sandbox

    def run(command, child, stdout):  # the stand-in refuses it, and so does the reader of the file
        subprocess.call([str(_shim_dir(child) / "xdg-open"), url], env=child, stderr=subprocess.DEVNULL)
        (_shim_dir(child) / "sign-in-url").write_text(url + "\n", encoding="utf-8")
        return 0

    auth_cli.login(no_browser=True, environ=env, run=run)
    out = capsys.readouterr().out
    assert "\x1b" not in out and "FAKE LINE" not in out and "Open this address" not in out and "Code:" not in out


def test_the_stand_in_itself_prints_nothing_raw_to_the_terminal(sandbox, tmp_path):
    env, _ = sandbox
    err = tmp_path / "err"

    def run(command, child, stdout):
        with open(err, "wb") as handle:
            subprocess.call([str(_shim_dir(child) / "xdg-open"), "https://example.test/\x1b[2J"], env=child, stderr=handle)
        return 0

    auth_cli.login(as_json=True, no_browser=True, environ=env, run=run)
    assert b"\x1b" not in err.read_bytes()


def test_a_code_with_escape_sequences_is_not_printed(sandbox, capsys):
    env, _ = sandbox
    url = "https://example.test/login?user_code=%1B%5B2J%0AFAKE"
    auth_cli.login(no_browser=True, environ=env, run=_calling(["xdg-open", url]))
    out = capsys.readouterr().out
    assert "\x1b" not in out and "FAKE" not in out.replace(url, "")
    assert "Code:" not in out
