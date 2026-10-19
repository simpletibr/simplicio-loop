"""Regression tests for cross-platform Mapper process liveness."""

from __future__ import annotations

import ctypes  # noqa: F401 - loaded before os.name is faked: a first import under "nt" runs Windows-only module code
import errno
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from simplicio_mapper.mapper import process_liveness
from simplicio_mapper.mapper.process_liveness import process_is_alive


class ProcessLivenessTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and Path("/proc").is_dir(), "requires Linux procfs")
    def test_zombie_child_is_not_alive(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import os; os._exit(0)"])
        self.addCleanup(child.wait)

        deadline = time.monotonic() + 5.0
        zombie = False
        while time.monotonic() < deadline:
            try:
                raw = Path(f"/proc/{child.pid}/stat").read_text(encoding="utf-8")
            except FileNotFoundError:
                break
            state = raw[raw.rfind(")") + 2 :].split()[0]
            if state == "Z":
                zombie = True
                break
            time.sleep(0.01)

        self.assertTrue(zombie, "child exited without an observable procfs zombie state")
        self.assertFalse(process_is_alive(child.pid))

    @unittest.skipUnless(hasattr(os, "waitid"), "requires waitid(2)")
    def test_exited_unreaped_child_is_not_alive_without_procfs(self) -> None:
        # macOS has no procfs, and kill(pid, 0) still succeeds for a zombie.
        # WNOWAIT observes the exit without reaping, so the zombie stays in place.
        child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        self.addCleanup(child.wait)
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)

        with mock.patch.object(os.path, "exists", return_value=False):
            self.assertFalse(process_is_alive(child.pid))
        # The probe must not consume the status: the owning Popen still sees the real code.
        self.assertEqual(child.wait(), 3)

    @unittest.skipUnless(os.name == "posix" and shutil.which("ps"), "requires POSIX ps")
    def test_ps_start_token_is_cached_for_own_pid_only(self) -> None:
        # macOS reads start tokens through ``ps``, a subprocess spawn per call. Our own
        # start time is fixed while we run, so it is resolved once. Other pids are read
        # every time because a pid can be reused after its process exits.
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)

        with mock.patch.object(process_liveness.subprocess, "run", wraps=subprocess.run) as run:
            process_liveness._ps_start_token(os.getpid())
            after_first_own = run.call_count
            process_liveness._ps_start_token(os.getpid())
            self.assertEqual(run.call_count, after_first_own, "own start token must be served from cache")
            process_liveness._ps_start_token(sleeper.pid)
            process_liveness._ps_start_token(sleeper.pid)
        self.assertEqual(run.call_count - after_first_own, 2, "other pids must not be cached")


class ProcessExistsTest(unittest.TestCase):
    """``os.kill(pid, 0)`` is the POSIX probe, but on Windows any signal other than the console events is
    TerminateProcess: the shared probes must never send signal 0 there, and must keep EPERM=alive, ESRCH=dead."""

    def _kill_calls_on_windows(self, probe) -> list:
        with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "kill") as kill:
            probe(4242)
        return kill.call_args_list

    def test_windows_probes_never_call_kill(self) -> None:
        for name in ("process_exists", "process_is_alive"):
            with self.subTest(probe=name):
                self.assertEqual(self._kill_calls_on_windows(getattr(process_liveness, name)), [])

    @unittest.skipUnless(os.name == "posix", "kill(pid, 0) is the POSIX probe")
    def test_process_exists_is_kill_zero_on_posix(self) -> None:
        cases = [
            (None, True),  # delivered: the process exists
            (PermissionError(errno.EPERM, "denied"), True),  # EPERM: exists under another user
            (ProcessLookupError(errno.ESRCH, "gone"), False),  # ESRCH: no such process
            (OSError(errno.EINVAL, "invalid"), False),
        ]
        for error, expected in cases:
            with self.subTest(error=error), mock.patch.object(os, "kill", side_effect=error) as kill:
                self.assertIs(process_liveness.process_exists(4242), expected)
                kill.assert_called_once_with(4242, 0)

    def test_process_exists_refuses_pids_that_name_no_process(self) -> None:
        with mock.patch.object(os, "kill") as kill:
            self.assertFalse(process_liveness.process_exists(0))
            self.assertFalse(process_liveness.process_exists(-1))
        kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
