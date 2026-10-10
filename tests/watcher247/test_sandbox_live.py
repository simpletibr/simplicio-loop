"""Live check: the argv sandbox.wrap builds really runs under bwrap.

Writable: the clone. Read-only: the rest of the root filesystem. /tmp is a private tmpfs
inside the sandbox, so a write there succeeds but never reaches the host.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from simplicio_loop.watcher247 import sandbox

from .sandbox_rig import needs_bwrap


@needs_bwrap
def test_wrapped_argv_writes_only_inside_clone(tmp_path):
    clone = tmp_path / "clone"
    state = tmp_path / "state"
    clone.mkdir()
    state.mkdir()
    host_probe = Path(__file__).resolve().parent / "sbx-host-probe"  # outside /tmp, so the tmpfs cannot hide it
    probe = (
        "touch ./inside && echo inside-ok; "
        "touch /usr/sbx-probe 2>/dev/null && echo root-WRITABLE || echo root-readonly; "
        f"touch /tmp/private 2>/dev/null && echo tmp-private; "
        f"touch {host_probe} 2>/dev/null && echo host-WRITABLE || echo host-readonly"
    )
    argv = sandbox.wrap(["sh", "-c", probe], clone=clone, state_dir=state, platform="linux", environ={})
    result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "inside-ok" in result.stdout
    assert "root-readonly" in result.stdout and "root-WRITABLE" not in result.stdout
    assert "host-readonly" in result.stdout and "host-WRITABLE" not in result.stdout
    assert (clone / "inside").exists()
    assert not host_probe.exists()
