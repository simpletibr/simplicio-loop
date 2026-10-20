"""The Linux child-subreaper flag is held by run_bounded for one call, never beyond it (Linux only).

``PR_SET_CHILD_SUBREAPER`` makes a process the parent of its orphaned descendants. ``run_bounded`` needs that only while
its own phase runs. A caller that outlives the call must get later orphans reparented to init again, or they stay
unreaped zombies and their process groups look alive.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator

import pytest

from simplicio_loop import quality_process
from tests._procs import GRANDCHILD_LEADER, gone_within

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper contract")

PR_SET_CHILD_SUBREAPER = 36
PR_GET_CHILD_SUBREAPER = 37
PASS_ARGV = [sys.executable, "-c", "pass"]


def _libc() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _subreaper_flag() -> int:
    flag = ctypes.c_int(-1)
    assert _libc().prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(flag), 0, 0, 0) == 0
    return flag.value


def _set_subreaper(value: int) -> None:
    assert _libc().prctl(PR_SET_CHILD_SUBREAPER, value, 0, 0, 0) == 0


def _parent_pid(pid: int) -> int:
    # /proc/<pid>/stat is "pid (comm) state ppid ...". comm may hold spaces or parentheses, so split after the last ")".
    with open(f"/proc/{pid}/stat") as handle:
        return int(handle.read().rsplit(") ", 1)[1].split()[1])


def _kill_and_reap_if_ours(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        # Reap only when the process is our own child (the bug), so a red run leaves no zombie in pytest.
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


@pytest.fixture
def restored_subreaper_flag() -> Iterator[None]:
    original = _subreaper_flag()
    yield
    _set_subreaper(original)


def test_run_bounded_restores_the_subreaper_flag_it_found_unset(restored_subreaper_flag) -> None:
    _set_subreaper(0)

    result = quality_process.run_bounded(PASS_ARGV, phase="stdlib_test", capture_output=True, timeout_seconds=30)

    assert result.returncode == 0
    assert _subreaper_flag() == 0


def test_run_bounded_without_captured_output_restores_the_flag_too(restored_subreaper_flag) -> None:
    _set_subreaper(0)

    result = quality_process.run_bounded(PASS_ARGV, phase="stdlib_test", timeout_seconds=30)

    assert result.returncode == 0
    assert _subreaper_flag() == 0


def test_run_bounded_keeps_a_flag_its_caller_already_set(restored_subreaper_flag) -> None:
    _set_subreaper(1)

    result = quality_process.run_bounded(PASS_ARGV, phase="stdlib_test", capture_output=True, timeout_seconds=30)

    assert result.returncode == 0
    assert _subreaper_flag() == 1


def test_orphan_created_after_run_bounded_is_not_adopted_by_its_caller(
    tmp_path, restored_subreaper_flag,
) -> None:
    _set_subreaper(0)
    assert quality_process.run_bounded(
        PASS_ARGV, phase="stdlib_test", capture_output=True, timeout_seconds=30,
    ).returncode == 0
    pidfile = tmp_path / "grandchild.pid"
    grandchild: int | None = None
    try:
        with subprocess.Popen(
            [sys.executable, "-c", GRANDCHILD_LEADER, str(pidfile)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        ) as leader:
            leader.wait(timeout=30)
        grandchild = int(pidfile.read_text())
        assert _parent_pid(grandchild) != os.getpid(), "the caller adopted an orphan after run_bounded returned"
    finally:
        if grandchild is not None:
            _kill_and_reap_if_ours(grandchild)
    assert gone_within(grandchild)


def test_overlapping_calls_hold_the_flag_until_the_last_one_returns(restored_subreaper_flag) -> None:
    _set_subreaper(0)
    in_flight = threading.Event()
    release = threading.Event()
    outcome: dict[str, quality_process.CommandResult] = {}

    def hold_until_released() -> str | None:
        in_flight.set()
        return "released by the test" if release.is_set() else None

    def long_call() -> None:
        outcome["result"] = quality_process.run_bounded(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            phase="stdlib_test", capture_output=True, timeout_seconds=60, cancel_check=hold_until_released,
        )

    worker = threading.Thread(target=long_call)
    worker.start()
    try:
        assert in_flight.wait(30), "the long call never reached its cancel check"
        quick = quality_process.run_bounded(PASS_ARGV, phase="stdlib_test", capture_output=True, timeout_seconds=30)
        assert quick.returncode == 0
        assert _subreaper_flag() == 1, "a finished call dropped the subreaper the in-flight call still needs"
    finally:
        release.set()
        worker.join(60)
    assert not worker.is_alive()
    assert outcome["result"].cancelled
    assert _subreaper_flag() == 0


def test_run_bounded_restores_the_flag_when_the_spawn_itself_fails(tmp_path, restored_subreaper_flag) -> None:
    _set_subreaper(0)

    with pytest.raises(OSError):
        quality_process.run_bounded(
            [str(tmp_path / "no-such-binary")], phase="stdlib_test", capture_output=True, timeout_seconds=30,
        )

    assert _subreaper_flag() == 0
