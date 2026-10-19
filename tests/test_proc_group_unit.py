"""The shared process-group helper, on real processes (POSIX only).

A child started with ``session_kwargs()`` leads its own group. ``kill_group`` signals that group by the leader's pid, so
it still reaches the group after the leader was reaped. ``group_alive`` counts a group it may not signal (EPERM) as alive,
and ``reap`` gives up after its budget.
"""

from __future__ import annotations

import asyncio
import errno
import os
import subprocess
import sys
import time

import pytest

from simplicio_loop import proc_group
from tests._procs import GRANDCHILD_LEADER, gone_within

pytestmark = pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")


def _start_leader(pidfile):
    return subprocess.Popen(
        [sys.executable, "-c", GRANDCHILD_LEADER, str(pidfile)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **proc_group.session_kwargs(),
    )


def _until(predicate, budget: float = 5.0) -> bool:
    deadline = time.monotonic() + budget
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_a_child_started_with_session_kwargs_leads_its_own_group():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **proc_group.session_kwargs())
    try:
        assert os.getpgid(child.pid) == child.pid
    finally:
        child.kill()
        child.wait()


def test_kill_group_reaches_members_after_the_leader_was_reaped(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    leader = _start_leader(pidfile)
    leader.wait()  # reaped: getpgid() on its pid now fails, but the grandchild still belongs to the group
    assert proc_group.kill_group(leader.pid) is True
    assert gone_within(int(pidfile.read_text())), "the grandchild outlived the group kill"


def test_group_alive_follows_its_members(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    leader = _start_leader(pidfile)
    leader.wait()
    assert proc_group.group_alive(leader.pid) is True
    proc_group.kill_group(leader.pid)
    assert gone_within(int(pidfile.read_text()))
    assert _until(lambda: not proc_group.group_alive(leader.pid)), "the group is still alive after its last member died"


def test_group_alive_is_false_once_no_member_is_left():
    leader = subprocess.Popen([sys.executable, "-c", "pass"], **proc_group.session_kwargs())
    leader.wait()
    assert proc_group.group_alive(leader.pid) is False


def test_a_group_we_may_not_signal_is_alive(monkeypatch):
    def denied(pgid, sig):
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", denied)
    assert proc_group.group_alive(4242) is True


def test_a_vanished_group_is_not_alive_and_not_an_error(monkeypatch):
    def missing(pgid, sig):
        raise ProcessLookupError(errno.ESRCH, "No such process")

    monkeypatch.setattr(os, "killpg", missing)
    assert proc_group.group_alive(4242) is False
    assert proc_group.kill_group(4242) is False


def test_reap_reports_a_finished_process_and_is_bounded_for_a_running_one():
    async def scenario():
        done = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        running = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)", **proc_group.session_kwargs(),
        )
        try:
            finished = await proc_group.reap(done, 10.0)
            started = time.monotonic()
            bounded = await proc_group.reap(running, 0.2)
            elapsed = time.monotonic() - started
        finally:
            proc_group.kill_tree(running)
            await running.wait()
        return finished, bounded, elapsed

    finished, bounded, elapsed = asyncio.run(scenario())
    assert finished is True
    assert bounded is False and elapsed < 5.0
