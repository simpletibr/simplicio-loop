"""#1680 item 4: `_scripts.sandboxed` binds `state_dir` read-only and the item's clone read-write, with the real bwrap."""
from __future__ import annotations

import asyncio
import inspect
import json
import sys

from simplicio_loop import evidence_tools as ev
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


# A Playwright stand-in: answers the dry run the probe makes, and writes the run's output folder when it runs the config.
FAKE_PLAYWRIGHT = """#!@PYTHON@
import json, sys
from pathlib import Path

argv = sys.argv[1:]
if argv[:3] == ["install", "--dry-run", "chromium"]:
    print("Chromium (playwright chromium v1)")
    print("  Install location:    @BUILD@")
    sys.exit(0)
config = json.loads(Path(argv[argv.index("--config") + 1]).read_text(encoding="utf-8").split("= ", 1)[1].rsplit(";", 1)[0])
Path(config["outputDir"]).mkdir(parents=True, exist_ok=True)
(Path(config["outputDir"]) / "done.txt").write_text("ran", encoding="utf-8")
print("1 passed")
"""

# The evidence run, as the worker makes it inside the sandbox: a write into the state folder must fail, and the run must still pass.
EVIDENCE_IN_SANDBOX = """
import json, os, sys, tempfile
from pathlib import Path
from simplicio_loop import evidence_tools as ev

state, out, node = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
try:
    (state / "probe.txt").write_text("x")
    wrote_state = True
except OSError:
    wrote_state = False
result = ev.run_spec(state, spec="// the stand-in runner does not read it", config={"outputDir": str(out)},
                     environ=dict(os.environ), which=lambda name: node if name == "node" else None, run=ev.execute)
left = [str(p) for p in Path(tempfile.gettempdir()).glob("simplicio-evidence-run-*")]
print(json.dumps({"wrote_state": wrote_state, "blocked": result.blocked, "code": result.code, "left": left}))
"""


@needs_bwrap
def test_an_evidence_run_works_inside_the_sandbox_while_the_state_dir_stays_read_only():
    """The evidence tools under the 24/7 sandbox: the state folder is read-only, the run folder is the sandbox's own /tmp, and
    the evidence lands in the item's clone."""
    with scratch("sbx-evidence-") as root:
        clone, state = root / "clone", root / "state"
        clone.mkdir()
        build = state / "browsers" / "chromium-1"
        build.mkdir(parents=True)
        (build / "INSTALLATION_COMPLETE").write_text("")
        package = state / "evidence-tools" / "node_modules" / "@playwright" / "test"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"version": ev.PLAYWRIGHT_VERSION}))
        playwright = state / "evidence-tools" / "node_modules" / ".bin" / "playwright"
        playwright.parent.mkdir(parents=True)
        playwright.write_text(FAKE_PLAYWRIGHT.replace("@PYTHON@", sys.executable).replace("@BUILD@", str(build)))
        playwright.chmod(0o755)
        node = root / "bin" / "node"
        node.parent.mkdir()
        node.write_text("#!/bin/sh\necho v22.4.0\n")
        node.chmod(0o755)
        before = sorted(str(p.relative_to(state)) for p in state.rglob("*"))
        done = asyncio.run(_scripts.sandboxed([sys.executable, "-c", EVIDENCE_IN_SANDBOX, str(state), str(clone / "evidence"), str(node)],
                                              clone=clone, state_dir=state, timeout=300))
        assert done.returncode == 0, done.stderr
        seen = json.loads(done.stdout.strip().splitlines()[-1])
        assert seen["wrote_state"] is False  # the state folder is read-only inside the sandbox
        assert (seen["blocked"], seen["code"]) == (None, 0), seen
        assert (clone / "evidence" / "done.txt").read_text(encoding="utf-8") == "ran"  # the evidence lands in the item's clone
        assert seen["left"] == []  # the run folder is removed when the run is over
        assert sorted(str(p.relative_to(state)) for p in state.rglob("*")) == before  # nothing was added to the state folder
