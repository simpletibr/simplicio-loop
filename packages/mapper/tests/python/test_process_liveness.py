"""Regression tests for cross-platform Mapper process liveness."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
