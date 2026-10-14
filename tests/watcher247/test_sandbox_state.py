"""#1656: the state dir is read-only for the item. Real bwrap, the item layout `<state>/work/<repo>.wt/<issue>`.

Before: the state dir was writable and only claims.json, budget.json and an existing STOP were read-only. An item could queue
fixes with free text (fixes.json), hide issues (issues-disabled.json), rewrite status.json and baseline.json, and create STOP,
which stops the watcher. After: nothing in the state dir is writable from inside; the item writes only its worktree, its admin
dir, the shared objects and the mapper base.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import sandbox

from .sandbox_rig import bwrap_skip_reason, run, scratch

pytestmark = pytest.mark.skipif(bool(bwrap_skip_reason()), reason=bwrap_skip_reason() or "bwrap")

CONTROL = ("claims.json", "budget.json", "status.json", "fixes.json", "baseline.json", "issues-disabled.json")
# `: >>` creates a missing file and appends to an existing one: it succeeds exactly where the item can write.
PROBE = 'for p in "$@"; do if ( : >> "$p" ) 2>/dev/null; then echo "W $p"; else echo "R $p"; fi; done'


@pytest.fixture
def layout():
    with scratch("sbx-state-") as root:
        state = root / "state"
        clone, other = state / "work" / "demo.wt" / "31", state / "work" / "demo.wt" / "32"
        common = state / "work" / "demo" / ".git"
        for folder in (clone, other, common / "worktrees" / "31", common / "worktrees" / "32", common / "objects",
                       common / "simplicio", common / "hooks", common / "refs", state / "logs", state / "opencode"):
            folder.mkdir(parents=True)
        for name in CONTROL:
            (state / name).write_text("{}")
        (common / "config").write_text("[core]\n")
        yield state, clone, other, common


def probe(layout, paths: list[Path], *, wrapper=None) -> dict[str, str]:
    state, clone, _other, _common = layout
    argv = ["/bin/sh", "-c", PROBE, "sh", *map(str, paths)]
    argv = (wrapper or (lambda a: sandbox.wrap(a, clone=clone, state_dir=state, platform="linux", environ={})))(argv)
    result = run(argv, {"PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    return {Path(line.split(" ", 1)[1]).as_posix(): line[0] for line in result.stdout.splitlines()}


def test_the_control_probe_can_write_a_state_file_when_the_state_dir_is_bound_read_write(layout):
    """The probe is not vacuous: with the layout of main (state dir read-write) it writes every file the next test needs blocked."""
    state, clone, _other, _common = layout
    paths = [state / name for name in (*CONTROL, "STOP", "newfile")]
    wrapper = lambda a: ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--bind", str(state), str(state), "--chdir", str(clone), "--", *a]  # noqa: E731
    assert set(probe(layout, paths, wrapper=wrapper).values()) == {"W"}


def test_no_file_of_the_state_dir_is_writable_and_stop_cannot_be_created(layout):
    state, _clone, _other, _common = layout
    paths = [state / name for name in (*CONTROL, "STOP", "newfile")] + [state / "logs" / "x.log", state / "opencode" / "cfg.json"]
    verdict = probe(layout, paths)
    assert set(verdict.values()) == {"R"}, verdict
    assert not (state / "STOP").exists() and not (state / "newfile").exists()  # nothing reached the host
    assert (state / "claims.json").read_text() == "{}"


def test_a_stop_that_already_exists_cannot_be_changed_either(layout):
    state, _clone, _other, _common = layout
    (state / "STOP").write_text("operator")
    assert probe(layout, [state / "STOP"]) == {(state / "STOP").as_posix(): "R"}
    assert (state / "STOP").read_text() == "operator"


def test_the_state_dir_cannot_get_a_new_folder_or_lose_one(layout):
    state, clone, _other, _common = layout
    argv = sandbox.wrap(["/bin/sh", "-c", 'mkdir "$1/new" || rmdir "$1/opencode" || rm -r "$1/logs"', "sh", str(state)],
                        clone=clone, state_dir=state, platform="linux", environ={})
    assert run(argv, {"PATH": "/usr/bin:/bin"}).returncode != 0
    assert not (state / "new").exists() and (state / "opencode").is_dir() and (state / "logs").is_dir()


def test_the_item_still_writes_exactly_its_own_worktree_admin_dir_objects_and_mapper_base(layout):
    state, clone, other, common = layout
    writable = [clone / "a.py", common / "worktrees" / "31" / "HEAD", common / "objects" / "pack1", common / "simplicio" / "map.json"]
    blocked = [other / "a.py", common / "worktrees" / "32" / "HEAD", common / "config", common / "hooks" / "pre-commit",
               common / "refs" / "heads-x", state / "work" / "demo" / "base.py"]
    verdict = probe(layout, writable + blocked)
    assert {path: verdict[path.as_posix()] for path in writable} == {path: "W" for path in writable}
    assert {path: verdict[path.as_posix()] for path in blocked} == {path: "R" for path in blocked}


def test_the_host_can_still_write_the_state_dir_while_a_sandboxed_item_runs(layout):
    """Read-only is a property of the sandbox's view, not of the files: the watcher keeps writing status, fixes and STOP."""
    state, clone, _other, _common = layout
    argv = sandbox.wrap(["/bin/sh", "-c", f'echo "$1" > "{clone}/seen"; sleep 1', "sh", "x"], clone=clone, state_dir=state,
                        platform="linux", environ={})
    child = subprocess.Popen(argv, env={"PATH": "/usr/bin:/bin"})
    try:
        (state / "status.json").write_text('{"stopped": false}')
        (state / "STOP").write_text("")
    finally:
        child.wait(timeout=30)
    assert (state / "STOP").exists() and (state / "status.json").read_text() == '{"stopped": false}'


def test_wrap_binds_the_state_dir_read_only(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    state = tmp_path / "state"
    for name in ("claims.json", "budget.json", "STOP"):
        state.mkdir(exist_ok=True)
        (state / name).write_text("{}")
    argv = sandbox.wrap(["x"], clone=tmp_path / "clone", state_dir=state, platform="linux", environ={})
    assert argv == ["bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                    "--ro-bind", str(state), str(state), "--bind", str(tmp_path / "clone"), str(tmp_path / "clone"),
                    "--chdir", str(tmp_path / "clone"), "--die-with-parent", "--new-session", "--", "x"]
    assert "--bind" in argv and str(state) not in [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
