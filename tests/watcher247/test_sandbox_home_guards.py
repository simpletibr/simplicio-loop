"""#1680 findings 1 to 3: the empty HOME of a planner cannot be undone by the state dir, a link, or a `..` in a HomeView.

Measured by the independent review of #1677 with the real bwrap: a state dir that is HOME or holds it re-exposes HOME (the
`--ro-bind state_dir` comes after the tmpfs; the probe read `.ssh/id`), a HOME that is an absolute symbolic link gave the opaque
`Can't mount tmpfs on /newroot/...`, and `HomeView(rw=("../../clone",))` bound a path outside HOME. Each one now stops in `wrap`
with `SandboxUnavailable` before any bwrap starts.
"""
from __future__ import annotations

import os
import signal
from pathlib import Path

import pytest

from simplicio_loop.watcher247 import sandbox

from .sandbox_rig import needs_bwrap, run, scratch


@pytest.fixture(autouse=True)
def linux_with_bwrap(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")


def wrap(tmp_path: Path, view: sandbox.HomeView, state: Path) -> list[str]:
    clone = tmp_path / "clone"
    clone.mkdir(exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return sandbox.wrap(["true"], clone=clone, state_dir=state, platform="linux", environ={}, home=view)


def test_a_state_dir_that_is_the_home_is_refused(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(sandbox.SandboxUnavailable, match="state dir"):
        wrap(tmp_path, sandbox.HomeView(home), home)


def test_a_state_dir_that_holds_the_home_is_refused(tmp_path):
    home = tmp_path / "var" / "lib" / "user"
    home.mkdir(parents=True)
    with pytest.raises(sandbox.SandboxUnavailable, match="state dir"):
        wrap(tmp_path, sandbox.HomeView(home), tmp_path / "var")


def test_a_state_dir_given_through_a_link_to_the_folder_that_holds_the_home_is_refused(tmp_path):
    holder = tmp_path / "holder"
    home = holder / "home"  # HOME itself is a canonical path
    home.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(holder)  # the state dir is named through a link: only its real path shows that it holds HOME
    with pytest.raises(sandbox.SandboxUnavailable, match="state dir"):
        wrap(tmp_path, sandbox.HomeView(home), alias)


def test_a_state_dir_inside_the_home_or_beside_it_is_accepted(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    inside = wrap(tmp_path, sandbox.HomeView(home), home / "service" / "state")  # the layout of a service that keeps its state in HOME
    beside = wrap(tmp_path, sandbox.HomeView(home), tmp_path / "state")
    for argv in (inside, beside):
        assert ["--tmpfs", str(home)] in [argv[i:i + 2] for i in range(len(argv) - 1)]  # the empty HOME is there in both layouts


def test_a_home_that_is_a_symbolic_link_is_refused_with_a_clear_reason(tmp_path):
    real = tmp_path / "real-home"
    real.mkdir()
    link = tmp_path / "home"
    link.symlink_to(real)
    with pytest.raises(sandbox.SandboxUnavailable, match="symbolic link"):
        wrap(tmp_path, sandbox.HomeView(link), tmp_path / "state")


def test_a_home_with_a_link_in_the_middle_of_its_path_is_refused(tmp_path):
    real = tmp_path / "real"
    (real / "user").mkdir(parents=True)
    (tmp_path / "alias").symlink_to(real)
    with pytest.raises(sandbox.SandboxUnavailable, match="symbolic link"):
        wrap(tmp_path, sandbox.HomeView(tmp_path / "alias" / "user"), tmp_path / "state")


def test_a_home_behind_a_relative_link_is_accepted(tmp_path):
    """`/home -> var/home` on ostree hosts: bwrap mounts the empty HOME fine behind a RELATIVE link (measured in the real bwrap test)."""
    (tmp_path / "real" / "user" / ".claude").mkdir(parents=True)
    (tmp_path / "link").symlink_to("real")  # relative target
    home = tmp_path / "link" / "user"
    argv = wrap(tmp_path, sandbox.HomeView(home, rw=(".claude",)), tmp_path / "state")
    assert ["--tmpfs", str(home)] in [argv[i:i + 2] for i in range(len(argv) - 1)]
    final = tmp_path / "final"
    final.symlink_to("real/user")  # the HOME itself is a relative link
    argv = wrap(tmp_path, sandbox.HomeView(final), tmp_path / "state")
    assert ["--tmpfs", str(final)] in [argv[i:i + 2] for i in range(len(argv) - 1)]


def test_a_relative_link_that_leads_to_an_absolute_one_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "hop").symlink_to(real)  # absolute target
    (tmp_path / "entry").symlink_to("hop")  # relative target, but it ends in the absolute link
    with pytest.raises(sandbox.SandboxUnavailable, match="absolute target"):
        wrap(tmp_path, sandbox.HomeView(tmp_path / "entry"), tmp_path / "state")


def test_a_loop_of_links_in_the_home_path_is_refused(tmp_path):
    (tmp_path / "a").symlink_to("b")
    (tmp_path / "b").symlink_to("a")

    def stuck(signum, frame):
        raise AssertionError("the guard followed a loop of links without a limit")

    previous = signal.signal(signal.SIGALRM, stuck)  # a guard without a hop limit would hang here: fail fast instead
    signal.alarm(10)
    try:
        with pytest.raises(sandbox.SandboxUnavailable):
            wrap(tmp_path, sandbox.HomeView(tmp_path / "a" / "user"), tmp_path / "state")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_a_home_with_a_dot_dot_in_its_text_is_refused_with_its_own_reason(tmp_path):
    (tmp_path / "home").mkdir()
    with pytest.raises(sandbox.SandboxUnavailable, match=r"'\.\.'"):
        wrap(tmp_path, sandbox.HomeView(tmp_path / "x" / ".." / "home"), tmp_path / "state")


@needs_bwrap
def test_a_home_behind_a_relative_link_runs_in_a_real_bwrap_with_the_secret_hidden(monkeypatch):
    with scratch("sbx-rel-") as root:
        (root / "real" / "user" / ".claude").mkdir(parents=True)
        (root / "real" / "user" / ".ssh").mkdir()
        (root / "real" / "user" / ".claude" / "login").write_text("FAKE-login")
        (root / "real" / "user" / ".ssh" / "id").write_text("FAKE-secret")
        (root / "link").symlink_to("real")
        home, clone, state = root / "link" / "user", root / "clone", root / "state"
        clone.mkdir()
        state.mkdir()
        monkeypatch.undo()
        argv = sandbox.wrap(["/bin/sh", "-c", f'cat "{home}/.claude/login"; echo; cat "{home}/.ssh/id" 2>/dev/null || echo HIDDEN'],
                            clone=clone, state_dir=state, platform="linux", environ={}, home=sandbox.HomeView(home, rw=(".claude",)))
        done = run(argv, {})
        assert done.returncode == 0, done.stderr
        assert done.stdout.split() == ["FAKE-login", "HIDDEN"]


@pytest.mark.parametrize("field", ["rw", "ro", "hide"])
@pytest.mark.parametrize("name", ["../../clone", "a/../../b", "..", "/etc", "", ".", "a/.."])
def test_a_home_view_entry_outside_the_home_is_refused(tmp_path, field, name):
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(sandbox.SandboxUnavailable, match="HomeView"):
        wrap(tmp_path, sandbox.HomeView(home, **{field: (name,)}), tmp_path / "state")


@needs_bwrap
def test_the_shapes_wrap_refuses_really_leak_the_home_in_a_real_bwrap(monkeypatch):
    """The control: the argv `wrap` used to build for a state dir that holds HOME and for `rw=('../..')` reads a FAKE secret of HOME.

    Not a mock of the leak: the same bwrap arguments, started for real. `wrap` now refuses both shapes before any bwrap starts.
    """
    monkeypatch.undo()  # this module's autouse fixture faked `which`; the real bwrap is needed here
    with scratch("sbx-guards-") as root:
        holder = root / "holder"
        home = holder / "home"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id").write_text("FAKE-secret")
        (holder / "clone").mkdir()
        probe = ["/bin/sh", "-c", f'cat "{home}/.ssh/id" 2>/dev/null || echo HIDDEN']
        base = ["bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", str(home)]
        hidden = run([*base, "--", *probe], {})
        leaked = run([*base, "--ro-bind", str(holder), str(holder), "--", *probe], {})  # state dir = the folder that holds HOME
        assert hidden.stdout.strip() == "HIDDEN"  # the empty HOME alone hides it
        assert leaked.stdout.strip() == "FAKE-secret"  # the read-only bind of the state dir gives it back
        monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
        with pytest.raises(sandbox.SandboxUnavailable):
            sandbox.wrap(["true"], clone=holder / "clone", state_dir=holder, platform="linux", environ={}, home=sandbox.HomeView(home))
        with pytest.raises(sandbox.SandboxUnavailable):
            sandbox.wrap(["true"], clone=holder / "clone", state_dir=root / "state", platform="linux", environ={},
                         home=sandbox.HomeView(home, rw=("../../clone",)))


def test_a_clean_home_view_still_binds_its_folders(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "claude").write_text("x")
    argv = wrap(tmp_path, sandbox.HomeView(home, rw=(".claude",), ro=(".local/bin/claude",)), tmp_path / "state")
    assert ["--bind-try", str(home / ".claude"), str(home / ".claude")] == argv[argv.index("--bind-try"):][:3]
    assert ["--ro-bind-try", str(home / ".local/bin/claude"), str(home / ".local/bin/claude")] == argv[argv.index("--ro-bind-try"):][:3]
    assert os.path.realpath(home) == str(home)


def test_task1_oserror_on_readlink_is_converted_to_sandbox_unavailable(tmp_path, monkeypatch):
    """#1680 task 1: OSError during _absolute_link_in walk is caught and converted to SandboxUnavailable."""
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to("real")  # relative link


    def broken_readlink(path):
        # Raise FileNotFoundError on any readlink call
        raise FileNotFoundError(f"disappeared: {path}")

    monkeypatch.setattr(os, "readlink", broken_readlink)
    with pytest.raises(sandbox.SandboxUnavailable, match="disappeared"):
        sandbox._absolute_link_in(tmp_path / "link")


def test_task2_absolute_link_inside_relative_target_is_refused(tmp_path):
    """#1680 task 2: A relative link whose target contains an absolute link is refused.

    Mutant A6: putting the target parts at the end of pending instead of the front.
    Correct code: walks entry -> hop2 (absolute) and refuses.
    Mutant: walks remaining 'user' first (not a link), then hop2 as user/hop2 (not a link) and accepts.
    Structure: real/user/ exists, hop2 = absolute symlink to real, entry = relative symlink to hop2, HOME = tmp_path/entry/user
    """
    (tmp_path / "real" / "user").mkdir(parents=True)  # real directory
    (tmp_path / "hop2").symlink_to(str(tmp_path / "real"))  # absolute symlink to real
    (tmp_path / "entry").symlink_to("hop2")  # relative symlink to hop2
    with pytest.raises(sandbox.SandboxUnavailable, match="absolute target"):
        wrap(tmp_path, sandbox.HomeView(tmp_path / "entry" / "user"), tmp_path / "state")


def test_task3_loop_of_links_has_distinct_error_message(tmp_path):
    """#1680 task 3: Error message for loops says 'loop of symbolic links', not 'absolute target'."""
    (tmp_path / "a").symlink_to("b")
    (tmp_path / "b").symlink_to("a")

    def stuck(signum, frame):
        raise AssertionError("guard followed loop without limit")

    previous = signal.signal(signal.SIGALRM, stuck)
    signal.alarm(10)
    try:
        with pytest.raises(sandbox.SandboxUnavailable, match="loop of symbolic links"):
            wrap(tmp_path, sandbox.HomeView(tmp_path / "a" / "user"), tmp_path / "state")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_task3_absolute_link_has_correct_error_message(tmp_path):
    """#1680 task 3: Error message for absolute link says 'absolute target'."""
    (tmp_path / "hop").symlink_to("/tmp")
    with pytest.raises(sandbox.SandboxUnavailable, match="absolute target"):
        wrap(tmp_path, sandbox.HomeView(tmp_path / "hop" / "user"), tmp_path / "state")


def test_task1_permission_error_on_is_symlink_is_converted_to_sandbox_unavailable(tmp_path, monkeypatch):
    """#1680 task 1: PermissionError on is_symlink (Python 3.11-3.13) is caught and converted to SandboxUnavailable."""
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to("real")

    original_is_symlink = sandbox.Path.is_symlink
    calls = [0]

    def broken_is_symlink(self):
        calls[0] += 1
        if calls[0] == 1:  # First call to is_symlink raises PermissionError
            raise PermissionError(f"access denied: {self}")
        return original_is_symlink(self)

    monkeypatch.setattr(sandbox.Path, "is_symlink", broken_is_symlink)
    with pytest.raises(sandbox.SandboxUnavailable, match="access denied"):
        sandbox._absolute_link_in(tmp_path / "link")


# --- #1680 findings 2 and 3 with the REAL bwrap: the guards refuse before any bwrap starts --------------------------------------------

@needs_bwrap
def test_a_home_reached_through_an_absolute_link_is_refused_where_the_real_bwrap_cannot_mount_it(monkeypatch):
    """Finding 2: the failure the guard exists for, measured with the real bwrap, and the refusal `wrap` gives instead."""
    monkeypatch.undo()  # the autouse fixture fakes bwrap's presence; these tests run the real one
    with scratch("sbx-abs-") as root:
        (root / "real" / "user").mkdir(parents=True)
        (root / "link").symlink_to(root / "real")  # ABSOLUTE target
        home, clone, state = root / "link" / "user", root / "clone", root / "state"
        clone.mkdir()
        state.mkdir()
        raw = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", str(home), "--", "true"]
        control = run(raw, {})
        assert control.returncode != 0 and "Can't" in control.stderr, control.stderr  # bwrap alone fails on the absolute link
        with pytest.raises(sandbox.SandboxUnavailable, match="absolute target"):
            sandbox.wrap(["true"], clone=clone, state_dir=state, platform="linux", environ={}, home=sandbox.HomeView(home, rw=(".claude",)))


@needs_bwrap
def test_an_entry_that_is_an_absolute_link_out_of_the_home_does_not_expose_the_home_secret(monkeypatch):
    """Finding 2, the entry side: an `ro` entry that links out of HOME is recreated as a symlink inside the empty HOME, and the
    HOME's own secret stays hidden behind that tmpfs."""
    monkeypatch.undo()
    with scratch("sbx-entry-") as root:
        home, outside = root / "home", root / "outside"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id").write_text("FAKE-secret")
        outside.mkdir()
        (outside / "note").write_text("FAKE-outside")
        (home / ".claude").symlink_to(outside)  # ABSOLUTE target, outside HOME
        clone, state = root / "clone", root / "state"
        clone.mkdir()
        state.mkdir()
        probe = f'cat "{home}/.claude/note" 2>/dev/null || echo NO-LINK; cat "{home}/.ssh/id" 2>/dev/null || echo HIDDEN'
        argv = sandbox.wrap(["/bin/sh", "-c", probe], clone=clone, state_dir=state, platform="linux", environ={}, home=sandbox.HomeView(home, ro=(".claude",)))
        done = run(argv, {})
        assert done.returncode == 0, done.stderr
        assert "FAKE-secret" not in done.stdout and "HIDDEN" in done.stdout, done.stdout


@needs_bwrap
@pytest.mark.parametrize(("field", "flag"), [("rw", "--bind-try"), ("ro", "--ro-bind-try")])
def test_a_dot_dot_entry_that_points_back_into_the_home_would_expose_its_secret_and_is_refused(monkeypatch, field, flag):
    """Finding 3: `../home/.ssh` is the HOME's own `.ssh`, spelt with a `..`. Bound after the empty HOME it hands the secret back:
    the control below reads it with the real bwrap, and `wrap` refuses that entry before any bwrap starts."""
    monkeypatch.undo()
    with scratch("sbx-dotdot-") as root:
        home, clone, state = root / "home", root / "clone", root / "state"
        (home / ".ssh").mkdir(parents=True)
        (home / ".ssh" / "id").write_text("FAKE-secret")
        clone.mkdir()
        state.mkdir()
        probe = ["/bin/sh", "-c", f'cat "{home}/.ssh/id" 2>/dev/null || echo HIDDEN']
        base = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", str(home)]
        entry = f"{home}/../home/.ssh"
        assert run([*base, "--", *probe], {}).stdout.strip() == "HIDDEN"  # the empty HOME alone hides it
        assert run([*base, flag, entry, entry, "--", *probe], {}).stdout.strip() == "FAKE-secret"  # the `..` entry gives it back
        with pytest.raises(sandbox.SandboxUnavailable, match="HomeView"):
            sandbox.wrap(["true"], clone=clone, state_dir=state, platform="linux", environ={}, home=sandbox.HomeView(home, **{field: ("../home/.ssh",)}))
