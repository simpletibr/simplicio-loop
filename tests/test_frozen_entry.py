"""Unit tests for the standalone-binary entry shim (issue #1576)."""
from __future__ import annotations

import importlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import types
from importlib import metadata
from pathlib import Path

import pytest

from simplicio_loop import frozen

ROOT = Path(__file__).resolve().parents[1]
SUFFIX = ".exe" if os.name == "nt" else ""
SCRIPTS = {
    "simplicio-loop": "fake_loop:main",
    "simplicio-mapper": "fake_mapper:main",
    "simplicio-dev-cli": "fake_dev:main",
    "simplicio-cli": "fake_dev:main",
    "simplicio-py": "fake_dev:main",
}


@pytest.fixture
def fake_entry_modules(monkeypatch):
    calls = []

    def make(name, result):
        module = types.ModuleType(name)
        module.main = lambda: calls.append((name, list(sys.argv))) or result
        monkeypatch.setitem(sys.modules, name, module)

    make("fake_loop", 0)
    make("fake_mapper", 7)
    make("fake_dev", None)
    monkeypatch.setattr(sys, "argv", ["original"])
    return calls


@pytest.fixture
def fake_exe(tmp_path):
    exe = tmp_path / "bin" / "simplicio-loop-v3.48.1-linux-x86_64"
    exe.parent.mkdir()
    exe.write_text('#!/bin/sh\necho "ran-as $(basename "$0")"\n')
    exe.chmod(0o755)
    return exe


@pytest.mark.parametrize("argv0, expected", [
    ("/usr/local/bin/simplicio-mapper", "simplicio-mapper"),
    ("simplicio-dev-cli", "simplicio-dev-cli"),
    ("C:\\tools\\Simplicio-Mapper.EXE", "simplicio-mapper"),
    ("./simplicio-loop-v3.48.1-linux-x86_64", "simplicio-loop-v3.48.1-linux-x86_64"),
])
def test_program_name_drops_directory_and_exe_suffix(argv0, expected):
    assert frozen.program_name(argv0) == expected


def test_resolve_entry_picks_operators_and_defaults_to_the_loop():
    assert frozen.resolve_entry("simplicio-mapper", SCRIPTS) == "fake_mapper:main"
    assert frozen.resolve_entry("simplicio-py", SCRIPTS) == "fake_dev:main"
    # A downloaded release asset keeps its long name until it is renamed: it is the loop.
    assert frozen.resolve_entry("simplicio-loop-v3.48.1-linux-x86_64", SCRIPTS) == "fake_loop:main"
    assert frozen.resolve_entry("anything-else", SCRIPTS) == "fake_loop:main"


def test_dispatch_runs_the_operator_with_a_clean_argv(fake_entry_modules):
    code = frozen.dispatch(["/opt/bin/simplicio-mapper", "scan", "."], SCRIPTS)
    assert code == 7
    assert fake_entry_modules == [("fake_mapper", ["simplicio-mapper", "scan", "."])]


def test_dispatch_turns_a_none_return_into_exit_code_zero(fake_entry_modules):
    assert frozen.dispatch(["/opt/bin/simplicio-py", "--version"], SCRIPTS) == 0
    assert fake_entry_modules == [("fake_dev", ["simplicio-py", "--version"])]


def test_dispatch_default_is_the_loop(fake_entry_modules):
    assert frozen.dispatch(["/tmp/whatever", "doctor"], SCRIPTS) == 0
    assert fake_entry_modules == [("fake_loop", ["whatever", "doctor"])]


@pytest.fixture
def started_by_the_bundle(monkeypatch):
    """The marker that adjust_child_environment puts in the environment of a sys.executable child."""
    monkeypatch.setenv(frozen.SELF_SPAWN, "1")


def test_dash_m_runs_a_bundled_module(monkeypatch, started_by_the_bundle):
    seen = {}

    def fake_run_module(name, *, run_name, alter_sys):
        seen.update(name=name, run_name=run_name, alter_sys=alter_sys, argv=list(sys.argv))

    monkeypatch.setattr(frozen.runpy, "run_module", fake_run_module)
    monkeypatch.setattr(sys, "argv", ["original"])
    assert frozen.dispatch(["/x/simplicio-loop", "-m", "simplicio.cli", "task", "--json"], SCRIPTS) == 0
    assert seen == {"name": "simplicio.cli", "run_name": "__main__", "alter_sys": True,
                    "argv": ["simplicio.cli", "task", "--json"]}


def test_dash_c_runs_code_and_keeps_the_exit_code(monkeypatch, started_by_the_bundle):
    monkeypatch.setattr(sys, "argv", ["original"])
    with pytest.raises(SystemExit) as exit_info:
        frozen.dispatch(["/x/simplicio-loop", "-c", "import sys; sys.exit(len(sys.argv))", "a", "b"], SCRIPTS)
    assert exit_info.value.code == 3  # argv is ["-c", "a", "b"], like python -c


def test_a_python_file_runs_like_python_script_py(monkeypatch, tmp_path, started_by_the_bundle):
    """The dashboard command starts the bundled server as `sys.executable <script>`."""
    script = tmp_path / "server.py"
    script.write_text(
        "import json, sys\n"
        "json.dump({'argv': sys.argv, 'name': __name__, 'path0': sys.path[0]}, open(sys.argv[1], 'w'))\n"
    )
    out = tmp_path / "out.json"
    monkeypatch.setattr(sys, "argv", ["original"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert frozen.dispatch(["/x/simplicio-loop", str(script), str(out), "--port", "1"], SCRIPTS) == 0
    seen = __import__("json").loads(out.read_text())
    assert seen == {"argv": [str(script), str(out), "--port", "1"], "name": "__main__", "path0": str(tmp_path)}


def test_a_py_name_that_is_not_a_file_goes_to_the_loop(fake_entry_modules, started_by_the_bundle):
    assert frozen.dispatch(["/x/simplicio-loop", "missing.py"], SCRIPTS) == 0
    assert fake_entry_modules == [("fake_loop", ["simplicio-loop", "missing.py"])]


@pytest.mark.parametrize("args", [
    ["-m", "json.tool"], ["-c", "raise SystemExit(9)"], ["script.py"],
])
def test_without_the_marker_a_user_never_runs_code_through_the_loop(fake_entry_modules, tmp_path, monkeypatch, args):
    """`simplicio-loop fix.py` is a task. Only the bundle starting itself as sys.executable runs code."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("raise SystemExit(9)\n")
    monkeypatch.delenv(frozen.SELF_SPAWN, raising=False)
    assert frozen.dispatch(["/x/simplicio-loop", *args], SCRIPTS) == 0
    assert fake_entry_modules == [("fake_loop", ["simplicio-loop", *args])]


@pytest.mark.parametrize("operator", frozen.OPERATOR_NAMES)
@pytest.mark.parametrize("args", [["-m", "json.tool"], ["-c", "raise SystemExit(9)"], ["script.py"]])
def test_an_operator_name_never_runs_code_even_with_the_marker(fake_entry_modules, started_by_the_bundle,
                                                              tmp_path, monkeypatch, operator, args):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "script.py").write_text("raise SystemExit(9)\n")
    frozen.dispatch([f"/x/{operator}", *args], SCRIPTS)
    assert fake_entry_modules[0][1] == [operator, *args]  # the operator received the arguments


def test_the_marker_is_used_once_and_does_not_reach_the_next_children(fake_entry_modules, started_by_the_bundle):
    frozen.dispatch(["/x/simplicio-loop", "doctor"], SCRIPTS)
    assert frozen.SELF_SPAWN not in os.environ


def test_operator_names_are_console_scripts_of_the_project_and_importable():
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert set(frozen.OPERATOR_NAMES) == {"simplicio-mapper", "simplicio-dev-cli", "simplicio-cli", "simplicio-py"}
    for name in frozen.OPERATOR_NAMES:
        module, attr = declared[name].split(":")
        assert callable(getattr(importlib.import_module(module), attr)), name


def test_console_scripts_reads_the_distribution_entry_points():
    try:
        metadata.distribution("simplicio-loop")
    except metadata.PackageNotFoundError:
        pytest.skip("simplicio-loop is not installed in this environment")
    scripts = frozen.console_scripts()
    for name in ("simplicio-loop", *frozen.OPERATOR_NAMES):
        assert ":" in scripts[name], name


def test_ensure_operator_dir_links_every_operator_to_the_executable(tmp_path, fake_exe):
    home = tmp_path / "home"
    directory = frozen.ensure_operator_dir(fake_exe, home)
    assert directory.is_relative_to(home / ".simplicio-loop" / "bin")
    if os.name != "nt":
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700  # no one else may swap a link
    # The loop is linked too: doctor, hooks and printed commands start it by name.
    for name in ("simplicio-loop", *frozen.OPERATOR_NAMES):
        link = directory / (name + SUFFIX)
        assert os.path.samefile(link, fake_exe), name


def test_ensure_operator_dir_is_idempotent_and_repairs_a_stale_link(tmp_path, fake_exe):
    home = tmp_path / "home"
    directory = frozen.ensure_operator_dir(fake_exe, home)
    mapper = directory / ("simplicio-mapper" + SUFFIX)
    before = os.lstat(mapper)
    assert frozen.ensure_operator_dir(fake_exe, home) == directory
    assert os.lstat(mapper).st_ino == before.st_ino  # untouched when still right

    other = tmp_path / "other"
    other.write_text("x")
    mapper.unlink()
    mapper.symlink_to(other) if os.name != "nt" else shutil.copy2(other, mapper)
    assert frozen.ensure_operator_dir(fake_exe, home) == directory
    assert os.path.samefile(mapper, fake_exe)


def test_operator_dir_is_keyed_by_executable_path(tmp_path, fake_exe):
    home = tmp_path / "home"
    copy = fake_exe.with_name("copy")
    shutil.copy2(fake_exe, copy)
    first = frozen.ensure_operator_dir(fake_exe, home)
    assert frozen.ensure_operator_dir(fake_exe, home) == first
    assert frozen.ensure_operator_dir(copy, home) != first


def test_prepare_environment_puts_the_operators_first_on_path_once(tmp_path, fake_exe):
    environ = {"PATH": os.pathsep.join(["/usr/bin", "/bin"])}
    first = frozen.prepare_environment(fake_exe, environ, tmp_path / "home")
    second = frozen.prepare_environment(fake_exe, environ, tmp_path / "home")
    assert first == second
    assert environ["PATH"].split(os.pathsep) == [str(first), "/usr/bin", "/bin"]
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in environ  # only self-spawns get it, see adjust_child_environment


@pytest.mark.skipif(os.name == "nt", reason="runs a POSIX shell script")
def test_operators_resolve_through_path_and_see_their_own_name(tmp_path, fake_exe):
    environ = {"PATH": "/usr/bin:/bin"}
    frozen.prepare_environment(fake_exe, environ, tmp_path / "home")
    for name in ("simplicio-loop", *frozen.OPERATOR_NAMES):
        assert shutil.which(name, path=environ["PATH"]), name
        out = subprocess.run([name], env=environ, capture_output=True, text=True, check=True).stdout
        assert out.strip() == f"ran-as {name}"


def test_main_only_touches_path_in_a_frozen_build(monkeypatch, tmp_path, fake_exe, fake_entry_modules):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setattr(frozen, "console_scripts", lambda: SCRIPTS)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert frozen.main(["simplicio-mapper"]) == 7
    assert os.environ["PATH"] == "/usr/bin:/bin"
    assert "PYINSTALLER_RESET_ENVIRONMENT" not in os.environ
    assert not (tmp_path / "home").exists()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)  # main wraps it: restore at teardown
    assert frozen.main(["simplicio-mapper"]) == 7
    assert os.environ["PATH"].split(os.pathsep)[0].startswith(str(tmp_path / "home"))


def _frozen_main_env(monkeypatch, home, fake_exe):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(frozen, "console_scripts", lambda: SCRIPTS)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)  # main wraps it: restore at teardown
    monkeypatch.setattr(frozen.atexit, "register", lambda *a, **k: None)


def test_a_home_that_cannot_hold_the_links_uses_a_private_temporary_directory(monkeypatch, tmp_path, fake_exe,
                                                                             fake_entry_modules, capsys):
    home = tmp_path / "home"
    home.write_text("a file, not a directory")
    _frozen_main_env(monkeypatch, home, fake_exe)

    assert frozen.main(["simplicio-loop", "--version"]) == 0  # --version must always work

    first = Path(os.environ["PATH"].split(os.pathsep)[0])
    assert first.name.startswith("simplicio-loop-bin-") and first.parent == Path(tempfile.gettempdir())
    assert os.path.samefile(first / ("simplicio-mapper" + SUFFIX), fake_exe)
    assert "private temporary directory" in capsys.readouterr().err
    shutil.rmtree(first, ignore_errors=True)


def test_when_no_directory_can_be_made_the_program_still_runs(monkeypatch, tmp_path, fake_exe, fake_entry_modules,
                                                              capsys):
    home = tmp_path / "home"
    home.write_text("a file, not a directory")
    _frozen_main_env(monkeypatch, home, fake_exe)
    monkeypatch.setattr(frozen.tempfile, "mkdtemp", lambda **kw: (_ for _ in ()).throw(OSError("no space")))

    assert frozen.main(["simplicio-loop", "--version"]) == 0

    assert os.environ["PATH"] == "/usr/bin:/bin"
    assert "cannot link the operators" in capsys.readouterr().err


@pytest.fixture
def popen_spy(monkeypatch):
    """Replace Popen.__init__ with a spy. adjust_child_environment wraps the spy; monkeypatch restores both."""
    seen = []

    def spy(self, args, *positional, **keywords):
        self._child_created = False  # lets Popen.__del__ run on an object that never started
        seen.append((args, keywords.get("env")))

    monkeypatch.setattr(subprocess.Popen, "__init__", spy)
    return seen


def test_a_child_that_is_this_executable_unpacks_its_own_files(popen_spy, monkeypatch):
    """A one-file child shares the temporary directory of its parent, and the parent deletes it on exit.

    The dashboard server outlives its parent, so a start through sys.executable gets a fresh unpack.
    """
    monkeypatch.setenv("KEEP", "yes")
    frozen.adjust_child_environment("/opt/simplicio-loop")
    subprocess.Popen(["/opt/simplicio-loop", "-m", "simplicio_loop.dashboard.server"])
    subprocess.Popen(["/opt/simplicio-loop", "-c", "pass"], env={"A": "b"})
    subprocess.Popen(args=["/opt/simplicio-loop", "x"])

    (_, first_env), (_, second_env), (_, third_env) = popen_spy
    assert first_env["PYINSTALLER_RESET_ENVIRONMENT"] == "1" and first_env["KEEP"] == "yes"
    assert second_env == {"A": "b", "PYINSTALLER_RESET_ENVIRONMENT": "1", frozen.SELF_SPAWN: "1"}
    assert third_env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert first_env[frozen.SELF_SPAWN] == third_env[frozen.SELF_SPAWN] == "1"  # allows -m, -c and FILE.py


def test_other_children_are_left_alone(popen_spy):
    """The operators start by name, run short and share the unpack of the parent: that is fast."""
    frozen.adjust_child_environment("/opt/simplicio-loop")
    subprocess.Popen(["simplicio-mapper", "scan"])
    subprocess.Popen(["/usr/bin/git", "status"], env={"A": "b"})
    subprocess.Popen("/opt/simplicio-loop --version", shell=True)
    subprocess.Popen("/opt/simplicio-loop", shell=True)  # the same text, but a shell runs it: not marked
    subprocess.Popen([])

    assert [env for _, env in popen_spy] == [None, {"A": "b"}, None, None, None]


def test_adjust_child_environment_wraps_popen_only_once(popen_spy):
    frozen.adjust_child_environment("/opt/simplicio-loop")
    wrapped = subprocess.Popen.__init__
    frozen.adjust_child_environment("/opt/simplicio-loop")
    assert subprocess.Popen.__init__ is wrapped


BUNDLE = "/tmp/_MEI4242"


def test_children_get_back_the_library_path_of_the_user(popen_spy, monkeypatch):
    """The bootloader puts its temporary directory on LD_LIBRARY_PATH. `git` must not load libz from it."""
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{BUNDLE}:/opt/user/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/user/lib")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", BUNDLE)  # no ORIG: the variable did not exist before
    frozen.adjust_child_environment("/opt/simplicio-loop", BUNDLE)
    subprocess.Popen(["/usr/bin/git", "status"])
    subprocess.Popen(["/usr/bin/git", "status"], env={"LD_LIBRARY_PATH": BUNDLE + ":/x", "KEEP": "1"})
    subprocess.Popen(["simplicio-mapper"])

    first, second, third = (env for _, env in popen_spy)
    assert first["LD_LIBRARY_PATH"] == "/opt/user/lib" and "DYLD_LIBRARY_PATH" not in first
    assert second == {"LD_LIBRARY_PATH": "/x", "KEEP": "1"}  # no ORIG in this env: drop the bundle entry only
    assert third["LD_LIBRARY_PATH"] == "/opt/user/lib"  # the operator bootloader adds its own entry again


def test_a_library_path_without_the_bundle_is_not_touched(popen_spy, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/user/lib")
    frozen.adjust_child_environment("/opt/simplicio-loop", BUNDLE)
    subprocess.Popen(["/usr/bin/git", "status"])
    subprocess.Popen(["/usr/bin/git", "status"], env={"LD_LIBRARY_PATH": "/x"})
    assert [env for _, env in popen_spy] == [None, {"LD_LIBRARY_PATH": "/x"}]


def test_the_bundle_path_alone_is_removed_when_the_user_had_none(popen_spy, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", BUNDLE)
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    frozen.adjust_child_environment("/opt/simplicio-loop", BUNDLE)
    subprocess.Popen(["/usr/bin/git", "status"])
    assert "LD_LIBRARY_PATH" not in popen_spy[0][1]


# --- the link directory is private (review of PR #1581) -----------------------------------------

posix_only = pytest.mark.skipif(os.name == "nt", reason="owner and mode checks are POSIX")


def _leaf(home, exe):
    return frozen.ensure_operator_dir(exe, home)


@posix_only
def test_every_level_is_private_even_with_umask_000(tmp_path, fake_exe):
    old = os.umask(0)
    try:
        leaf = _leaf(tmp_path / "home", fake_exe)
    finally:
        os.umask(old)
    for level in (leaf, leaf.parent, leaf.parent.parent):
        assert stat.S_IMODE(level.stat().st_mode) == 0o700, level


@posix_only
def test_a_loose_parent_of_the_user_loses_group_and_other_write(tmp_path, fake_exe):
    """umask 002 is the default on many systems: other code of the loop makes this directory 775."""
    home = tmp_path / "home"
    (home / ".simplicio-loop" / "bin").mkdir(parents=True)
    (home / ".simplicio-loop").chmod(0o777)
    (home / ".simplicio-loop" / "bin").chmod(0o775)
    leaf = _leaf(home, fake_exe)
    assert stat.S_IMODE((home / ".simplicio-loop").stat().st_mode) == 0o755
    assert stat.S_IMODE((home / ".simplicio-loop" / "bin").stat().st_mode) == 0o755
    assert leaf.parent == home / ".simplicio-loop" / "bin"


@posix_only
def test_an_open_leaf_that_the_user_owns_is_closed_and_cleaned(tmp_path, fake_exe):
    """A fake `git` in a 0777 directory must never stay on PATH."""
    home = tmp_path / "home"
    leaf = _leaf(home, fake_exe)
    leaf.chmod(0o777)
    (leaf / "git").write_text("#!/bin/sh\necho PWNED\n")
    (leaf / "git").chmod(0o755)
    (leaf / ".simplicio-mapper.99.tmp").write_text("left by a crashed run")

    assert _leaf(home, fake_exe) == leaf

    assert stat.S_IMODE(leaf.stat().st_mode) == 0o700
    assert sorted(item.name for item in leaf.iterdir()) == sorted(
        name + SUFFIX for name in ("simplicio-loop", *frozen.OPERATOR_NAMES))


@posix_only
def test_a_leaf_with_a_directory_inside_is_refused(tmp_path, fake_exe):
    home = tmp_path / "home"
    leaf = _leaf(home, fake_exe)
    (leaf / "sub").mkdir()
    with pytest.raises(frozen.UnsafeDirectory, match="directory inside"):
        _leaf(home, fake_exe)


@posix_only
def test_a_symlinked_leaf_is_refused_and_nothing_is_written_through_it(tmp_path, fake_exe):
    home = tmp_path / "home"
    leaf = _leaf(home, fake_exe)
    evil = tmp_path / "evil"
    evil.mkdir()
    shutil.rmtree(leaf)
    leaf.symlink_to(evil)
    with pytest.raises(frozen.UnsafeDirectory, match="symbolic link"):
        _leaf(home, fake_exe)
    assert list(evil.iterdir()) == []


@posix_only
def test_a_symlinked_parent_is_refused(tmp_path, fake_exe):
    home = tmp_path / "home"
    (home).mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (home / ".simplicio-loop").symlink_to(elsewhere)
    with pytest.raises(frozen.UnsafeDirectory, match="symbolic link"):
        _leaf(home, fake_exe)
    assert list(elsewhere.iterdir()) == []


@posix_only
@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="needs root to give a directory away")
@pytest.mark.parametrize("level", ["leaf", "parent"])
def test_a_directory_of_another_user_is_refused(tmp_path, fake_exe, level):
    home = tmp_path / "home"
    leaf = _leaf(home, fake_exe)
    os.chown(leaf if level == "leaf" else leaf.parent, 65534, 65534)
    with pytest.raises(frozen.UnsafeDirectory, match="another user"):
        _leaf(home, fake_exe)


@posix_only
def test_an_unsafe_leaf_falls_back_to_a_private_temporary_directory(monkeypatch, tmp_path, fake_exe, capsys):
    home = tmp_path / "home"
    leaf = _leaf(home, fake_exe)
    evil = tmp_path / "evil"
    evil.mkdir()
    shutil.rmtree(leaf)
    leaf.symlink_to(evil)
    registered = []
    monkeypatch.setattr(frozen.atexit, "register", lambda function, *args: registered.append((function, args)))
    environ = {"PATH": "/usr/bin:/bin"}

    directory = frozen.prepare_environment(fake_exe, environ, home)

    assert directory != leaf and directory.parent == Path(tempfile.gettempdir())
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert environ["PATH"].split(os.pathsep)[0] == str(directory)
    assert os.path.samefile(directory / "simplicio-mapper", fake_exe)
    assert list(evil.iterdir()) == []
    assert "symbolic link" in capsys.readouterr().err
    function, args = registered[0]  # removed when the program ends
    function(*args)
    assert not directory.exists()
