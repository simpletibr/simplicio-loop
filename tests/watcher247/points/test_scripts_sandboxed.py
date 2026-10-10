"""#1680 item 4: `_scripts.sandboxed` binds `state_dir` read-only and the item's clone read-write, with the real bwrap."""
from __future__ import annotations

import asyncio
import inspect
import sys

from simplicio_loop.watcher247.points import _scripts

from ..sandbox_rig import needs_bwrap, scratch

WRITE = "import sys, pathlib; pathlib.Path(sys.argv[1]).write_text('x')"


def test_the_parameter_is_named_state_dir_and_the_docstring_says_it_is_read_only():
    assert "state_dir" in inspect.signature(_scripts.sandboxed).parameters
    assert "writable" not in inspect.signature(_scripts.sandboxed).parameters
    assert "read-only" in _scripts.sandboxed.__doc__


@needs_bwrap
def test_a_script_writes_its_clone_and_gets_erofs_on_a_state_dir_that_is_another_folder(monkeypatch):
    with scratch("sbx-scripts-") as root:
        clone, state = root / "clone", root / "state"
        clone.mkdir()
        state.mkdir()
        monkeypatch.setenv("HOME", str(root))
        mine, theirs = clone / "mine.txt", state / "theirs.txt"
        ok = asyncio.run(_scripts.sandboxed([sys.executable, "-c", WRITE, str(mine)], clone=clone, state_dir=state, timeout=60))
        bad = asyncio.run(_scripts.sandboxed([sys.executable, "-c", WRITE, str(theirs)], clone=clone, state_dir=state, timeout=60))
        assert ok.returncode == 0 and mine.read_text() == "x", ok.stderr
        assert bad.returncode != 0 and "Errno 30" in bad.stderr and not theirs.exists(), bad.stderr
