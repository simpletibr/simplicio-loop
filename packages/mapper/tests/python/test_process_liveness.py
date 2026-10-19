"""Regression tests for cross-platform Mapper process liveness."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
