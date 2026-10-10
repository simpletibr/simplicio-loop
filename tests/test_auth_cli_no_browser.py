"""`simplicio-loop login --no-browser` (#1670): a Runtime that opens the browser and ignores BROWSER must not open it."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import auth_cli

URL = "https://example.test/simplicio/login?user_code=ABCD-1234"

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
    assert doc["user_code"] == "ABCD-1234"


def test_no_browser_reports_url_and_code_in_text(sandbox, capsys):
    env, called = sandbox
    auth_cli.login(no_browser=True, environ=env, run=_runtime_that_opens_the_browser)
    out = capsys.readouterr().out
    assert not called.exists()
    assert URL in out
    assert "ABCD-1234" in out


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
