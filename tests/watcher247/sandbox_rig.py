"""Rig for the real-bwrap sandbox tests: a scratch directory OUTSIDE /tmp.

`sandbox.wrap` mounts a tmpfs on /tmp, so anything a test keeps under /tmp is hidden inside the sandbox for that reason alone
and "the secret is not readable" would prove nothing. The scratch directory lives under /var/tmp.
"""
from __future__ import annotations

import functools
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

SCRATCH_BASE = Path("/var/tmp")
BARE = ["bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "true"]


@functools.lru_cache(maxsize=None)
def bwrap_skip_reason() -> str:
    """Why the real-bwrap tests cannot run here; empty when they can. Probed once per session.

    The text is a `CAPABILITY_UNAVAILABLE[...]` reason, so `scripts/check.py` counts the skip under capability_unavailable.
    Inside an item sandbox (the watcher runs the verify there) the kernel refuses a nested namespace.
    """
    if sys.platform != "linux" or shutil.which("bwrap") is None:
        return "CAPABILITY_UNAVAILABLE[bwrap_missing]: needs Linux with bwrap"
    if not SCRATCH_BASE.is_dir():
        return f"CAPABILITY_UNAVAILABLE[bwrap_missing]: needs {SCRATCH_BASE} outside /tmp"
    try:
        result = subprocess.run(BARE, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "CAPABILITY_UNAVAILABLE[nested_bwrap]: bwrap did not return within 10s"
    if result.returncode == 0:
        return ""
    return f"CAPABILITY_UNAVAILABLE[nested_bwrap]: bwrap cannot create its namespaces here: {result.stderr.strip()}"


def needs_bwrap(test):
    """Marker for a test that starts its own bwrap: skipped, with the reason, where the probe says it cannot run."""
    reason = bwrap_skip_reason()
    return pytest.mark.skipif(bool(reason), reason=reason or "bwrap")(test)


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
