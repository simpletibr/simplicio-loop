"""A hung login check is bounded by its timeout, and the whole process group it started is killed.

The fake CLIs start a background grandchild before they hang. A kill aimed only at the leader misses that grandchild:
on the count path the grandchild also holds the stdout pipe, so the check used to wait for it (about 30s here).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import stat
import time
from pathlib import Path

import pytest

from simplicio_loop import exec_auth

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the fake CLIs are POSIX shell scripts")

TIMEOUT = 2.0  # the check's status timeout
MARGIN = 2.0  # generous on purpose: a loaded host is slow to start the fake; the bound only has to tell 2s from 30s


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    """Fake CLIs in their own bin dir, first on PATH; an empty HOME, so no credential file can answer for them."""
    home = tmp_path / "home"
    home.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(exec_auth, "_STATUS_TIMEOUT", TIMEOUT)
    pidfile = tmp_path / "grandchild.pid"
    yield bindir, pidfile
    if pidfile.exists():  # a failing run must not leave the 30s grandchild behind
        with contextlib.suppress(OSError, ValueError, ProcessLookupError):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)


def write_cli(bindir: Path, name: str, body: str) -> None:
    script = bindir / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def hang_with_grandchild(bindir: Path, name: str, pidfile: Path, *, leader_exits: bool = False) -> None:
    """A background `sleep 30` inherits stdout and records its pid; the leader then hangs, or exits 0 at once."""
    sleep = shutil.which("sleep")
    tail = "exit 0" if leader_exits else f"{sleep} 30"
    write_cli(bindir, name, f'{sleep} 30 &\necho $! > "{pidfile}"\n{tail}')


def gone_within(pid: int, budget: float = 5.0) -> bool:
    """True once `pid` no longer runs (its group was killed and launchd or init has reaped it)."""
    deadline = time.monotonic() + budget
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def test_hung_status_check_is_bounded_and_kills_its_process_group(fake_cli):
    bindir, pidfile = fake_cli
    hang_with_grandchild(bindir, "claude", pidfile)

    started = time.monotonic()
    result = asyncio.run(exec_auth.check("claude"))
    elapsed = time.monotonic() - started

    assert result.status == "login_missing"  # fails closed
    assert elapsed < TIMEOUT + MARGIN, f"a hung status check returned after {elapsed:.2f}s"
    assert pidfile.exists(), "the fake CLI never started its grandchild"
    assert gone_within(int(pidfile.read_text())), "the grandchild outlived the check"


def test_hung_count_check_is_bounded_and_kills_its_process_group(fake_cli):
    bindir, pidfile = fake_cli
    hang_with_grandchild(bindir, "opencode", pidfile)  # the grandchild also holds the stdout pipe the count is read from

    started = time.monotonic()
    result = asyncio.run(exec_auth.check("opencode"))
    elapsed = time.monotonic() - started

    assert result.status == "login_missing"  # fails closed
    assert elapsed < TIMEOUT + MARGIN, f"a hung count check returned after {elapsed:.2f}s"
    assert pidfile.exists(), "the fake CLI never started its grandchild"
    assert gone_within(int(pidfile.read_text())), "the grandchild outlived the check"


def test_count_check_kills_leftover_grandchild_once_its_leader_already_exited(fake_cli):
    bindir, pidfile = fake_cli
    hang_with_grandchild(bindir, "opencode", pidfile, leader_exits=True)  # leader exits 0; its grandchild keeps stdout

    started = time.monotonic()
    result = asyncio.run(exec_auth.check("opencode"))
    elapsed = time.monotonic() - started

    assert result.status == "login_missing"  # fails closed
    assert elapsed < TIMEOUT + MARGIN, f"a count check with an exited leader returned after {elapsed:.2f}s"
    assert pidfile.exists(), "the fake CLI never started its grandchild"
    assert gone_within(int(pidfile.read_text())), "the grandchild outlived the check"
