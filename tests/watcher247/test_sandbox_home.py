"""#1570: a planner CLI sees an empty HOME plus its own folders, not the whole HOME of the service user.

The experiment of the issue is the test: FAKE-* logins of every family in a fake HOME (outside /tmp, see sandbox_rig), a probe
that reads them from inside the real bwrap. Before: the HOME was read-only and fully readable (every login of every family
readable, and a write into the HOME failed with EROFS, the failure codex, grok and opencode show). After: one login readable.
"""
from __future__ import annotations

import stat
from pathlib import Path

import pytest

from simplicio_loop import exec_planner
from simplicio_loop.watcher247 import host_mode, sandbox

from .sandbox_rig import needs_bwrap, run, scratch

LOGIN = {  # the file each family's login lives in, relative to HOME (measured with the real CLIs, see the PR)
    "claude": ".claude/.credentials.json",
    "codex": ".codex/auth.json",
    "grok": ".grok/auth.json",
    "agy": ".gemini/antigravity-cli/antigravity-oauth-token",
    "opencode": ".local/share/opencode/auth.json",
    "gemini": ".gemini/oauth_creds.json",
}
OTHER_SECRETS = (".ssh/id_ed25519", ".config/gh/hosts.yml", ".aws/credentials", ".simplicio/login.json")
PROBE = 'for p in "$@"; do if cat "$HOME/$p" >/dev/null 2>&1; then echo "$p"; fi; done'


def fill(home: Path, relative: str, text: str) -> Path:
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def rig(monkeypatch):
    """A fake HOME (outside /tmp) with a FAKE login for each family and the secrets a planner must never read; clone and state beside it."""
    with scratch("sbx-home-") as root:
        home = root / "home"
        for family, relative in LOGIN.items():
            fill(home, relative, f"FAKE-{family}")
        for relative in OTHER_SECRETS:
            fill(home, relative, "FAKE-secret")
        clone, state = root / "clone", root / "state"
        clone.mkdir()
        state.mkdir()
        monkeypatch.setenv("HOME", str(home))
        yield home, clone, state


def sandboxed(argv: list[str], *, home: Path, clone: Path, state: Path, family: str | None) -> list[str]:
    extra = {"home": host_mode.home_view(family)} if family else {}  # no family: the layout of main, the control
    return sandbox.wrap(argv, clone=clone, state_dir=state, platform="linux", environ={}, **extra)


def shell(script: str, *args: str) -> list[str]:
    return ["/bin/sh", "-c", script, "sh", *args]


def env_of(home: Path) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home)}


@needs_bwrap
def test_the_old_layout_shows_every_login_of_the_home(rig):
    """The control: with no HOME view the probe reads all six logins and the other secrets, so the next test is not vacuous."""
    home, clone, state = rig
    argv = sandboxed(shell(PROBE, *LOGIN.values(), *OTHER_SECRETS), home=home, clone=clone, state=state, family=None)
    assert set(run(argv, env_of(home)).stdout.split()) == {*LOGIN.values(), *OTHER_SECRETS}


@needs_bwrap
@pytest.mark.parametrize("family", sorted(LOGIN))
def test_a_planner_reads_only_its_own_login(rig, family):
    home, clone, state = rig
    argv = sandboxed(shell(PROBE, *LOGIN.values(), *OTHER_SECRETS), home=home, clone=clone, state=state, family=family)
    result = run(argv, env_of(home))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [LOGIN[family]]  # 1 of 6; none of ssh, gh, aws or the simplicio login


@needs_bwrap
@pytest.mark.parametrize("family", sorted(LOGIN))
def test_the_planner_writes_its_own_folder_and_it_persists(rig, family):
    home, clone, state = rig
    target = Path(LOGIN[family]).parent / "refreshed"
    argv = sandboxed(shell('mkdir -p "$HOME/$(dirname "$1")" && echo renewed > "$HOME/$1"', str(target)),
                     home=home, clone=clone, state=state, family=family)
    result = run(argv, env_of(home))
    assert result.returncode == 0, result.stderr
    assert (home / target).read_text().strip() == "renewed"  # the renewed token reaches the host


@needs_bwrap
def test_the_rest_of_home_is_writable_scratch_that_never_reaches_the_host(rig):
    """The HOME was read-only: opencode died opening ~/.local/share/opencode/log/opencode.log, codex and grok could not create a session."""
    home, clone, state = rig
    argv = sandboxed(shell('mkdir -p "$HOME/.cache/x" && echo t > "$HOME/.cache/x/f" && echo t > "$HOME/.claude.json"'),
                     home=home, clone=clone, state=state, family="codex")
    assert run(argv, env_of(home)).returncode == 0
    assert not (home / ".cache").exists() and not (home / ".claude.json").exists()


@needs_bwrap
def test_opencode_can_open_its_log_in_its_data_folder(rig):
    home, clone, state = rig
    argv = sandboxed(shell('mkdir -p "$HOME/.local/share/opencode/log" && echo l > "$HOME/.local/share/opencode/log/opencode.log"'),
                     home=home, clone=clone, state=state, family="opencode")
    result = run(argv, env_of(home))
    assert result.returncode == 0, result.stderr
    assert (home / ".local/share/opencode/log/opencode.log").read_text().strip() == "l"


# What each CLI's install looks like (measured with the real binaries): where the executable in HOME/.local/bin points.
BINARIES = {
    "claude": (".local/share/claude/versions/2.1.292", ".local/bin/claude"),  # symlink into a tree the sandbox shows read-only
    "codex": (".codex/packages/standalone/current/bin/codex", ".local/bin/codex"),  # symlink into its own read-write folder
    "grok": (".grok/bin/grok", ".local/bin/grok"),
    "agy": (None, ".local/bin/agy"),  # a regular file
}


@needs_bwrap
@pytest.mark.parametrize("family", sorted(BINARIES))
def test_the_planner_binary_in_home_runs(rig, family):
    home, clone, state = rig
    target, link = BINARIES[family]
    real = fill(home, target or link, f"#!/bin/sh\necho {family}-binary-ran\n")
    real.chmod(real.stat().st_mode | stat.S_IEXEC)
    if target:
        (home / link).parent.mkdir(parents=True, exist_ok=True)
        (home / link).symlink_to(real)
    argv = sandboxed([str(home / link)], home=home, clone=clone, state=state, family=family)
    result = run(argv, env_of(home))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{family}-binary-ran"


@needs_bwrap
def test_a_family_without_a_login_still_runs(rig):
    home, clone, state = rig
    for relative in LOGIN.values():
        (home / relative).unlink()
    argv = sandboxed(shell(PROBE, *LOGIN.values()), home=home, clone=clone, state=state, family="codex")
    result = run(argv, env_of(home))
    assert result.returncode == 0 and result.stdout == ""


@needs_bwrap
def test_clone_and_state_inside_home_are_not_hidden_by_the_tmpfs(monkeypatch):
    """The tmpfs goes on first: a clone or a state dir under HOME is bound over it, not under it."""
    with scratch("sbx-home-") as home:
        clone, state = home / "work" / "clone", home / "state"
        clone.mkdir(parents=True)
        state.mkdir()
        (state / "claims.json").write_text("{}")
        monkeypatch.setenv("HOME", str(home))
        argv = sandboxed(shell('echo mine > clone-file && cat "$1"', str(state / "claims.json")), home=home, clone=clone, state=state, family="grok")
        result = run(argv, env_of(home))
        assert result.returncode == 0, result.stderr
        assert (clone / "clone-file").read_text().strip() == "mine"


def test_the_home_tmpfs_comes_before_every_other_bind(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "codex").symlink_to(home / ".codex" / "bin" / "codex")
    clone, state = tmp_path / "clone", tmp_path / "state"
    view = sandbox.HomeView(home, rw=(".codex", ".claude"), ro=(".local/bin/codex",))
    argv = sandbox.wrap(["codex"], clone=clone, state_dir=state, platform="linux", environ={}, home=view)
    assert argv == [
        "bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--tmpfs", str(home),
        "--bind-try", str(home / ".codex"), str(home / ".codex"),  # .claude does not exist: not bound
        "--symlink", str(home / ".codex" / "bin" / "codex"), str(home / ".local" / "bin" / "codex"),
        "--ro-bind", str(state), str(state),
        "--bind", str(clone), str(clone),
        "--chdir", str(clone), "--die-with-parent", "--new-session", "--", "codex",
    ]


def test_a_file_where_a_folder_is_expected_is_never_bound(tmp_path, monkeypatch):
    """A bound single file breaks the CLI's atomic rename (EBUSY): only folders are bound read-write."""
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude").write_text("not a folder")
    view = sandbox.HomeView(home, rw=(".claude",))
    argv = sandbox.wrap(["claude"], clone=tmp_path / "c", state_dir=tmp_path / "s", platform="linux", environ={}, home=view)
    assert "--bind-try" not in argv and str(home / ".claude") not in argv


def test_a_hidden_folder_is_covered_after_the_folders_around_it(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    home = tmp_path / "home"
    (home / ".gemini" / "antigravity-cli").mkdir(parents=True)
    view = sandbox.HomeView(home, rw=(".gemini",), hide=(".gemini/antigravity-cli",))
    argv = sandbox.wrap(["gemini"], clone=tmp_path / "c", state_dir=tmp_path / "s", platform="linux", environ={}, home=view)
    start = argv.index("--bind-try")
    assert argv[start:start + 6] == ["--bind-try", str(home / ".gemini"), str(home / ".gemini"),
                                     "--tmpfs", str(home / ".gemini" / "antigravity-cli"), "--ro-bind"]


@pytest.mark.parametrize("bad", ["missing", "file", "root", "relative"])
def test_wrap_fails_closed_when_home_cannot_be_mounted(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(sandbox.shutil, "which", lambda binary: "/usr/bin/bwrap")
    (tmp_path / "file").write_text("x")
    home = {"missing": tmp_path / "nowhere", "file": tmp_path / "file", "root": Path("/"), "relative": Path("home")}[bad]
    with pytest.raises(sandbox.SandboxUnavailable) as caught:
        sandbox.wrap(["codex"], clone=tmp_path / "c", state_dir=tmp_path / "s", platform="linux", environ={},
                     home=sandbox.HomeView(home, rw=(".codex",)))
    assert caught.value.reason_code == "sandbox_unavailable"


def test_there_is_no_home_view_without_a_sandbox(tmp_path):
    """The opt-out runs the argv as it is: no bwrap, no HOME view, no error about HOME."""
    argv = sandbox.wrap(["codex"], clone=tmp_path, state_dir=tmp_path, platform="linux",
                        environ={"SIMPLICIO_247_ALLOW_UNSANDBOXED": "1"}, which=lambda binary: None,
                        home=sandbox.HomeView(tmp_path / "nowhere"))
    assert argv == ["codex"]


# --- host_mode: the single table ---------------------------------------------------------------------------------

def test_the_table_covers_exactly_the_planner_families():
    assert set(host_mode.FAMILY_HOME) == set(exec_planner.SUPPORTED_FAMILIES)
    assert set(host_mode.FAMILY_HOME) == set(LOGIN)


def test_the_table_has_only_folders_and_binaries_under_home():
    for family, entry in host_mode.FAMILY_HOME.items():
        assert entry["rw"], f"{family} has no login folder"
        for name in (*entry["rw"], *entry.get("ro", ()), *entry.get("hide", ())):
            assert not Path(name).is_absolute() and ".." not in Path(name).parts, name
        for name in entry["rw"]:
            assert not Path(name).suffix == ".json", f"{family}: {name} is a file; only folders are bound read-write"


def test_the_planner_argv_starts_with_the_family_name():
    """host_mode picks the HOME view from argv[0], because exec_planner hands the wrapper only the argv."""
    for family in exec_planner.SUPPORTED_FAMILIES:
        assert exec_planner.build_argv(family, "planning", "p", "default", "/x", "low")[0] == family


def test_planner_wrap_gives_each_family_its_own_home_view(tmp_path, monkeypatch):
    seen = {}

    def spy(argv, **kwargs):
        seen[argv[0]] = kwargs
        return list(argv)

    monkeypatch.setattr(sandbox, "wrap", spy)
    monkeypatch.setenv("HOME", str(tmp_path))
    wrap = host_mode.planner_wrap(tmp_path / "item")
    for family in exec_planner.SUPPORTED_FAMILIES:
        wrap([family, "-p", "x"])
        view = seen[family]["home"]
        assert view.home == tmp_path and view.rw == host_mode.FAMILY_HOME[family]["rw"]
        assert seen[family]["clone"] == tmp_path / "item"
    with pytest.raises(KeyError):  # an unknown CLI gets no view at all: fail closed, never the whole HOME
        wrap(["unknown-cli"])
