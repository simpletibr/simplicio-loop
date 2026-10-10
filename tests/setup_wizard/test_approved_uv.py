"""The approved `uv` of `setup` (#1688, review fix): it is checked again right before it runs, in every place that starts it.

The places that start an approved `gh` or `uv`, and the test of each:
- `prereqs.check_all` (`--version`, `python find`), first call of `_prereq_step`: test_the_first_check_never_runs_a_swapped_uv
- `prereqs.check_all`, second call after an install: test_flow (the same `_pinned` wrapper, with the fresh hash)
- `prereqs.ensure` -> `_install_python` (`python install`): test_a_uv_swapped_before_the_python_install_never_runs
- `prereqs.ensure` -> `_install_python` (`python find`): test_a_uv_swapped_after_the_python_install_never_runs_to_find
- `prereqs.ensure` -> `_install_python` with a uv written by this run: test_a_uv_installed_now_and_swapped_never_runs
- `github_cred.resolve` -> `_from_gh` (`gh auth token`): test_approved_gh
`sudo`, `apt` and `brew` are not approved files: `_pinned` lets them through (test_pinned_lets_other_programs_through).
The swaps are real file writes. A marker that only the swapped file writes proves what ran."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import os
import tarfile

import pytest

from simplicio_loop import prereqs, setup_cli

from .fakes import Fakes, check, run
from .test_approved_gh import go
from .test_flow import install_tool, recorded

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")


def good(home):
    return f"#!/bin/sh\ntouch '{home}/A-'\"$2\"\necho /usr/bin/python3\n".encode()


def evil(home):
    return f"#!/bin/sh\ntouch '{home}/PWNED'\necho /usr/bin/python3\n".encode()


def approved_uv(home, content):
    """A `uv` that an earlier setup installed: setup.json holds the hash of `content`."""
    uv = install_tool(home, "uv", content)
    first = Fakes()
    first.actions = [prereqs.Action(name="uv", result="installed", detail="0.5.0")]
    run(first, home)
    assert recorded(home) == {"uv": hashlib.sha256(content).hexdigest()}
    return uv


def python_missing(uv):
    fakes = Fakes()
    fakes.checks = [check("python", "missing", fix="uv python install 3.12"), dataclasses.replace(check("uv"), path=str(uv))]
    return fakes


def real_ensure_seams(fakes, before=None):
    """The seams of `fakes`, but with the real `prereqs.ensure`: `uv` is really executed. `before` runs just before it."""
    def ensure(checks, **kw):
        if before:
            before()
        return prereqs.ensure(checks, **kw)
    return dataclasses.replace(fakes.seams(), ensure=ensure)


def test_the_approved_uv_really_runs_when_nothing_changed(home):
    uv = approved_uv(home, good(home))
    later = python_missing(uv)
    code, text = go(later, home, real_ensure_seams(later))
    assert (home / "A-install").exists() and (home / "A-find").exists(), text  # the control: the approved file is the one that runs
    assert "python: installed /usr/bin/python3" in text


def test_a_uv_swapped_before_the_python_install_never_runs(home):
    uv = approved_uv(home, good(home))
    later = python_missing(uv)
    code, text = go(later, home, real_ensure_seams(later, before=lambda: uv.write_bytes(evil(home))))
    assert not (home / "PWNED").exists(), text
    assert not (home / "A-install").exists()
    assert "did not finish (exit None)" in text  # the refusal looks like a program that did not start


def test_a_uv_swapped_after_the_python_install_never_runs_to_find(home):
    spare = home / "spare"
    script = f"#!/bin/sh\ntouch '{home}/A-'\"$2\"\n[ \"$2\" = install ] && mv '{spare}' '{home}/.local/bin/uv'\necho /usr/bin/python3\n".encode()
    uv = approved_uv(home, script)
    spare.write_bytes(evil(home))
    spare.chmod(0o755)
    later = python_missing(uv)
    code, text = go(later, home, real_ensure_seams(later))
    assert (home / "A-install").exists()  # the approved file ran for the install and swapped itself
    assert uv.read_bytes() == evil(home)
    assert not (home / "PWNED").exists() and not (home / "A-find").exists(), text


def test_the_first_check_never_runs_a_swapped_uv(home):
    uv = approved_uv(home, good(home))
    later = Fakes()
    later.checks = [check("python")]

    def check_all(environ, **kw):
        uv.write_bytes(evil(home))  # after the approval was read, before the first look at the tools
        return prereqs.check_all(environ, **kw)

    code, text = go(later, home, dataclasses.replace(later.seams(), check_all=check_all))
    assert not (home / "PWNED").exists(), text


def test_ensure_gets_the_pinned_run_and_the_check_gets_it_too(home):
    uv = approved_uv(home, good(home))
    later = python_missing(uv)
    go(later, home, later.seams())
    calls = {c[0]: c[1] for c in later.calls if c[0] in ("check_all", "ensure")}
    assert callable(calls["ensure"]["run"]) and callable(calls["check_all"]["run"])


def test_pinned_lets_other_programs_through(home):
    uv = approved_uv(home, good(home))
    seen = []
    pinned = setup_cli._pinned({"HOME": str(home)}, {"uv": hashlib.sha256(good(home)).hexdigest()},
                               lambda argv, *a, **k: seen.append((list(argv), a)) or (0, "ok"))
    assert pinned(["sudo", "-n", "apt-get", "install", "-y", "git"], 600.0) == (0, "ok")
    assert pinned(["brew", "install", "git"]) == (0, "ok")
    assert seen == [(["sudo", "-n", "apt-get", "install", "-y", "git"], (600.0,)), (["brew", "install", "git"], ())]
    uv.write_bytes(evil(home))
    assert pinned([str(uv), "--version"], 5.0) == (None, "")
    assert len(seen) == 2  # the swapped file never reached the function that starts programs


# --- a uv written by this very run ----------------------------------------------------------------------------------------

TAG = "0.6.0"


def uv_release(binary):
    """(download, pins) of a uv release whose archive holds `binary`, pinned for linux amd64."""
    archive, sums_url, archive_url, member = prereqs._release_files("uv", TAG, "linux", "amd64")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(binary)
        tar.addfile(info, io.BytesIO(binary))
    blob = buffer.getvalue()
    pins = {"uv": {"tag": TAG, "assets": {"linux-amd64": {"archive": archive, "sha256": hashlib.sha256(blob).hexdigest()}}}}

    def get(url):
        if url == sums_url:
            return f"{hashlib.sha256(blob).hexdigest()}  {archive}\n".encode()
        return blob

    return get, pins


def test_a_uv_installed_now_and_swapped_never_runs(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    original = prereqs._install_release

    def install_then_swap(tool, where, dry_run):
        action = original(tool, where, dry_run)
        where.exe(tool).write_bytes(evil(tmp_path))  # after the hash was taken, before the file runs
        return action

    monkeypatch.setattr(prereqs, "_install_release", install_then_swap)
    missing = [prereqs.Check(name="python", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")]
    get, pins = uv_release(good(tmp_path))
    actions = prereqs.ensure(missing, environ={"HOME": str(tmp_path), "PATH": ""}, get=get, bin_dir=bin_dir, pins=pins,
                             platform="linux", machine="x86_64", which=lambda name: None, run=prereqs.run_command)
    assert not (tmp_path / "PWNED").exists(), actions
    assert not (tmp_path / "A-install").exists()
    assert [a.name for a in actions] == ["uv", "python"] and actions[1].result == "failed"
