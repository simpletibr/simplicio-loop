"""Unit tests for the standalone-binary entry shim (issue #1576)."""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
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


def test_dash_m_runs_a_bundled_module(monkeypatch):
    seen = {}

    def fake_run_module(name, *, run_name, alter_sys):
        seen.update(name=name, run_name=run_name, alter_sys=alter_sys, argv=list(sys.argv))

    monkeypatch.setattr(frozen.runpy, "run_module", fake_run_module)
    monkeypatch.setattr(sys, "argv", ["original"])
    assert frozen.dispatch(["/x/simplicio-loop", "-m", "simplicio.cli", "task", "--json"], SCRIPTS) == 0
    assert seen == {"name": "simplicio.cli", "run_name": "__main__", "alter_sys": True,
                    "argv": ["simplicio.cli", "task", "--json"]}


def test_dash_c_runs_code_and_keeps_the_exit_code(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["original"])
    with pytest.raises(SystemExit) as exit_info:
        frozen.dispatch(["/x/simplicio-loop", "-c", "import sys; sys.exit(len(sys.argv))", "a", "b"], SCRIPTS)
    assert exit_info.value.code == 3  # argv is ["-c", "a", "b"], like python -c


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
    assert not (tmp_path / "home").exists()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe))
    assert frozen.main(["simplicio-mapper"]) == 7
    assert os.environ["PATH"].split(os.pathsep)[0].startswith(str(tmp_path / "home"))
