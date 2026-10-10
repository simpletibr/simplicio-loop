"""The opencode deny config must be readable inside the sandbox (a bwrap tmpfs on /tmp hides anything written there)."""
from __future__ import annotations

import asyncio
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from simplicio_loop import exec_planner
from simplicio_loop.watcher247 import sandbox

from .sandbox_rig import needs_bwrap

STUB = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    cfg = os.environ.get("OPENCODE_CONFIG", "")
    try:
        deny = json.load(open(cfg))["permission"]["bash"] == "deny"
    except Exception:
        deny = False
    try:  # records what it saw; the sandbox keeps the state dir (this folder) read-only, which is not what is under test
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.txt"), "w") as handle:
            handle.write(cfg)
    except OSError:
        pass
    if not deny:
        sys.exit(3)
    print(json.dumps({"operations": []}))
''')


@pytest.fixture
def rig(tmp_path, monkeypatch):
    state, clone, bin_dir = tmp_path / "state", tmp_path / "clone", tmp_path / "state" / "bin"
    for path in (state, clone, bin_dir):
        path.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "opencode"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/local/bin:/usr/bin:/bin")
    return state, clone, bin_dir


def plan(clone, **kwargs):
    return asyncio.run(exec_planner.run_planner("opencode", "planning", "task", cwd=str(clone), repo_root=clone, **kwargs))


def test_config_is_written_in_the_given_dir_and_removed_afterwards(rig):
    state, clone, bin_dir = rig
    result = plan(clone, config_dir=state / "opencode")
    assert result.reason_code == "ok"
    seen = Path((bin_dir / "seen.txt").read_text())
    assert seen.parent == state / "opencode" and seen.name.startswith("simplicio-opencode-")
    assert not seen.exists()


@needs_bwrap
def test_config_is_readable_inside_the_sandbox(rig):
    state, clone, bin_dir = rig
    wrap = lambda argv: sandbox.wrap(argv, clone=clone, state_dir=state)  # noqa: E731
    result = plan(clone, config_dir=state / "opencode", wrap=wrap)
    assert result.reason_code == "ok", result.error  # the stub exits 3 when it cannot read the deny rules


@needs_bwrap
def test_config_in_tmp_is_hidden_by_the_sandbox(tmp_path):
    """The failure the fix prevents: a file under the sandbox's /tmp tmpfs does not exist inside it."""
    clone, state = tmp_path / "clone", tmp_path / "state"
    clone.mkdir()
    state.mkdir()
    host_tmp = Path("/tmp") / f"sbx-opencode-probe-{tmp_path.name}.json"
    host_tmp.write_text("{}")
    (state / "cfg.json").write_text("{}")
    try:
        hidden = sandbox.wrap(["sh", "-c", f'test -r "{host_tmp}"'], clone=clone, state_dir=state)
        assert subprocess.run(hidden).returncode != 0
        bound = sandbox.wrap(["sh", "-c", 'test -r "$OPENCODE_CONFIG"'], clone=clone, state_dir=state)
        env = {**os.environ, "OPENCODE_CONFIG": str(state / "cfg.json")}
        assert subprocess.run(bound, env=env).returncode == 0
    finally:
        host_tmp.unlink()
