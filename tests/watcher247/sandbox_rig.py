"""Rig for the real-bwrap sandbox tests: a scratch directory OUTSIDE /tmp.

`sandbox.wrap` mounts a tmpfs on /tmp, so anything a test keeps under /tmp is hidden inside the sandbox for that reason alone
and "the secret is not readable" would prove nothing. The scratch directory lives under /var/tmp.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCRATCH_BASE = Path("/var/tmp")
BARE = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "true"]


def bwrap_skip_reason() -> str:
    """Why the real-bwrap tests cannot run on this host; empty when they can."""
    if sys.platform != "linux" or shutil.which("bwrap") is None:
        return "needs Linux with bwrap"
    if not SCRATCH_BASE.is_dir():
        return f"needs {SCRATCH_BASE} outside /tmp"
    result = subprocess.run(BARE, capture_output=True, text=True, timeout=60)
    return "" if result.returncode == 0 else f"bwrap cannot create its namespaces here: {result.stderr.strip()}"


@contextmanager
def scratch(prefix: str) -> Iterator[Path]:
    """A new directory under /var/tmp, removed (only this one) afterwards."""
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=SCRATCH_BASE))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run(argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=60)
