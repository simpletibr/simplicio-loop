"""Shared helpers for tests that start real child processes and need to see them stopped."""

import os
import time

# A leader that starts a sleeping grandchild (the same process group), writes the grandchild's pid to the file named by
# its first argument, and exits at once. The grandchild outlives its leader and keeps the leader's group alive.
GRANDCHILD_LEADER = (
    "import subprocess, sys\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "with open(sys.argv[1], 'w') as handle:\n"
    "    handle.write(str(child.pid))\n"
)


def gone_within(pid: int, budget: float = 5.0) -> bool:
    """True once ``pid`` no longer exists. A zombie still exists for kill(2), so this waits for its parent or launchd to reap it."""
    deadline = time.monotonic() + budget
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
