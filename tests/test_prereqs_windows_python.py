"""Python on Windows (#1842): a Python that really runs is accepted, the Microsoft Store alias is not, and a missing Python is
installed with winget when winget runs, else with uv.

Pure: `which`, `matches` and `run` are fakes, so every test here runs on any host. The Windows paths are plain strings.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from simplicio_loop import prereqs

HOME = r"C:\Users\wesley.simplicio"
ALIAS = rf"{HOME}\AppData\Local\Microsoft\WindowsApps\python.exe"
WINGET = rf"{HOME}\AppData\Local\Microsoft\WindowsApps\winget.exe"
REAL = rf"{HOME}\AppData\Local\Programs\Python\Python312\python.exe"
OLD = rf"{HOME}\AppData\Local\Programs\Python\Python39\python.exe"
UV = rf"{HOME}\.local\bin\uv.exe"
STUB = (9009, "Python was not found; run without arguments to install from the Microsoft Store, or disable this shortcut")
WINGET_INSTALL = [WINGET, "install", "-e", "--id", "Python.Python.3.11", "--silent", "--accept-package-agreements",
                  "--accept-source-agreements"]
WINGET_FIX = "winget install -e --id Python.Python.3.11"


GIT = rf"{HOME}\AppData\Local\Programs\Git\cmd\git.exe"
GH = rf"{HOME}\AppData\Local\Programs\GitHub CLI\gh.exe"


class WindowsHost:
    """`which` and `run` of a Windows host. `paths` maps a program name to its first file on PATH (git and gh are there unless a
    test says otherwise); `answers` maps a command line to (exit code, output); a command nobody answered runs nothing (exit None).
    Every command run is recorded."""

    def __init__(self, paths, answers=None):
        self.paths = {"git": GIT, "gh": GH, **paths}
        self.answers = dict(answers or {})
        self.calls = []

    def which(self, name):
        return self.paths.get(name)

    def matches(self, name):
        return [self.paths[name]] if self.paths.get(name) else []

    def run(self, argv, timeout):
        argv = list(argv)
        self.calls.append(argv)
        return self.answers.get(" ".join(argv), (None, ""))

    def ran(self, program):
        return [call for call in self.calls if call[0] == program]


def checks(host, **kw):
    kw.setdefault("platform", "win32")
    kw.setdefault("interpreter", None)
    return {c.name: c for c in prereqs.check_all({"PATH": ""}, which=host.which, run=host.run, **kw)}


def install(host, checks_=None, **kw):
    kw.setdefault("platform", "win32")
    kw.setdefault("machine", "AMD64")
    kw.setdefault("bin_dir", Path("/nonexistent/bin"))
    kw.setdefault("pins", {})
    checks_ = list(checks(host, platform=kw["platform"]).values()) if checks_ is None else checks_
    return prereqs.ensure(checks_, environ={"PATH": ""}, which=host.which, run=host.run, **kw)


@pytest.mark.parametrize("path, alias", [
    (ALIAS, True),
    (rf"{HOME}\AppData\Local\Microsoft\WindowsApps\python3.exe", True),
    (r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\python.exe", True),
    ("/c/Users/x/AppData/Local/Microsoft/WindowsApps/python.exe", True),
    (REAL, False),
    (r"C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12_3.12.4.0_x64__qbz5n2kfra8p0\python.exe", False),
    ("/usr/bin/python3", False),
    (None, False),
    ("", False),
])
def test_only_the_store_alias_folder_is_an_alias(path, alias):
    assert prereqs.is_store_alias(path) is alias


def test_a_store_alias_that_runs_nothing_is_not_a_python_and_the_fix_says_why():
    host = WindowsHost({"python": ALIAS, "python3": ALIAS, "winget": WINGET},
                       {f"{ALIAS} --version": STUB, f"{WINGET} --version": (0, "v1.8.1911")})
    python = checks(host)["python"]
    assert (python.status, python.path, python.version) == ("missing", None, None)
    assert python.fix == f"{ALIAS} is the Microsoft Store alias and runs nothing; {WINGET_FIX}"


def test_without_a_working_winget_the_store_alias_fix_names_the_uv_install():
    host = WindowsHost({"python": ALIAS, "winget": WINGET}, {f"{ALIAS} --version": STUB, f"{WINGET} --version": STUB})
    python = checks(host)["python"]
    assert python.status == "missing"
    assert python.fix == f"{ALIAS} is the Microsoft Store alias and runs nothing; uv python install 3.11"


def test_a_real_python_is_accepted_with_its_version_and_path():
    host = WindowsHost({"python": REAL}, {f"{REAL} --version": (0, "Python 3.12.4")})
    python = checks(host)["python"]
    assert (python.status, python.path, python.version, python.fix) == ("ok", REAL, "3.12.4", "")


def test_a_real_python_after_the_store_alias_on_path_is_still_found():
    host = WindowsHost({"python": ALIAS}, {f"{ALIAS} --version": STUB, f"{REAL} --version": (0, "Python 3.12.4")})
    all_paths = {"python": [ALIAS, REAL], "python3": []}
    found = prereqs.check_all({"PATH": ""}, which=host.which, run=host.run, platform="win32", interpreter=None,
                              matches=lambda name: all_paths[name])
    python = {c.name: c for c in found}["python"]
    assert (python.status, python.path, python.version) == ("ok", REAL, "3.12.4")


def test_a_python_older_than_the_package_minimum_is_outdated_and_not_used():
    host = WindowsHost({"python": OLD}, {f"{OLD} --version": (0, "Python 3.9.13")})
    found = checks(host)
    assert (found["python"].status, found["python"].version, found["python"].minimum) == ("outdated", "3.9.13", "3.11")
    assert found["python"].fix == "uv python install 3.11" and found["uv"].required is True


def test_winget_installs_python_when_it_runs():
    host = WindowsHost({"python": None, "winget": WINGET, "uv": UV},
                       {f"{WINGET} --version": (0, "v1.8.1911"), " ".join(WINGET_INSTALL): (0, "Successfully installed")})
    actions = install(host)
    assert [(a.name, a.result) for a in actions] == [("python", "installed")]
    assert WINGET_INSTALL in host.calls and actions[0].detail.startswith("`winget install -e --id Python.Python.3.11 --silent")
    assert [UV, "python", "install", "3.11"] not in host.calls  # uv is not the route when winget runs


def test_without_winget_python_is_installed_with_uv_python_install():
    host = WindowsHost({"python": None, "uv": UV}, {
        f"{UV} --version": (0, "uv 0.11.15"), f"{UV} python install 3.11": (0, ""), f"{UV} python find 3.11": (0, REAL + "\n")})
    actions = install(host)
    assert [(a.name, a.result, a.detail) for a in actions] == [("python", "installed", REAL)]
    assert [UV, "python", "install", "3.11"] in host.calls and not host.ran(WINGET)


def test_a_winget_that_does_not_run_is_not_used_and_uv_installs_python():
    host = WindowsHost({"python": None, "winget": WINGET, "uv": UV}, {
        f"{WINGET} --version": STUB, f"{UV} --version": (0, "uv 0.11.15"), f"{UV} python install 3.11": (0, ""),
        f"{UV} python find 3.11": (0, REAL)})
    actions = install(host)
    assert [(a.name, a.result) for a in actions] == [("python", "installed")]
    assert [UV, "python", "install", "3.11"] in host.calls and WINGET_INSTALL not in host.calls


def test_a_failed_winget_install_is_a_failed_action_with_its_exit_code_and_nothing_else_runs():
    host = WindowsHost({"python": None, "winget": WINGET, "uv": UV}, {
        f"{WINGET} --version": (0, "v1.8.1911"), " ".join(WINGET_INSTALL): (1, "No applicable installer found")})
    actions = install(host)
    assert [(a.name, a.result) for a in actions] == [("python", "failed")] and "exit 1" in actions[0].detail
    assert "No applicable installer" not in actions[0].detail
    assert [UV, "python", "install", "3.11"] not in host.calls  # no second attempt through uv


def test_dry_run_names_the_winget_command_and_runs_nothing():
    host = WindowsHost({"python": None, "winget": WINGET, "uv": UV}, {f"{WINGET} --version": (0, "v1.8.1911")})
    checks_ = list(checks(host).values())
    host.calls.clear()
    actions = install(host, checks_, dry_run=True)
    assert [(a.name, a.result) for a in actions] == [("python", "would-install")]
    assert WINGET_FIX in actions[0].detail and host.calls == []


@pytest.mark.skipif(os.name == "nt", reason="the fake program is a POSIX executable, found by its mode")
def test_safe_matches_lists_every_folder_on_path_that_has_the_program(tmp_path):
    from simplicio_loop import setup_hardening

    first, second = tmp_path / "first", tmp_path / "second"
    for folder in (first, second):
        folder.mkdir()
        program = folder / "python"
        program.write_text("#!/bin/sh\n")
        program.chmod(0o755)
    matches = setup_hardening.safe_matches({"PATH": f"{first}{os.pathsep}{second}"})
    assert matches("python") == [str(first / "python"), str(second / "python")]
    assert matches("missing-program") == []
