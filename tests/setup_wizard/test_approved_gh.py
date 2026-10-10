"""The approved `gh` of `setup` (#1688, follow-ups of #1683): the hash is taken when the file is installed, and it is
checked again right before the file runs. The swaps here are real file writes; a marker file proves which `gh` ran."""
from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import os
import tarfile
import types

import pytest

from simplicio_loop import github_cred, prereqs, setup_cli

from .fakes import TOKEN, Fakes, run, summary_file
from .test_flow import install_gh, installed_gh_fakes, recorded, trusted_of

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX modes and symlinks")

GOOD = "#!/bin/sh\ntouch '{marker}'\necho " + TOKEN + "\n"


def script(marker):
    return GOOD.format(marker=marker).encode()


@pytest.fixture
def offline(monkeypatch):
    """GitHub always accepts the token and no real `git` credential helper is asked."""
    monkeypatch.setattr(github_cred, "validate", lambda token, **kw: ("octocat", ("repo", "workflow")))
    monkeypatch.setattr(github_cred, "_from_git", lambda *a, **k: None)


def real_resolve_seams(fakes, before=None):
    """The seams of `fakes`, but with the real `github_cred.resolve`: `gh` is really executed. `before` runs just before it."""
    def resolve(environ, **kw):
        if before:
            before()
        return github_cred.resolve(environ, **kw)
    return dataclasses.replace(fakes.seams(), resolve=resolve)


def go(fakes, home, seams, **options):
    out = io.StringIO()
    code = setup_cli.run(setup_cli.Options(**options), environ={"HOME": str(home), "PATH": "/usr/bin"}, seams=seams, out=out)
    return code, out.getvalue()


def test_the_approved_gh_really_runs_when_nothing_changed(home, offline):
    marker = home / "ran-A"
    install_gh(home, script(marker))
    run(installed_gh_fakes(), home)
    later = Fakes()
    code, text = go(later, home, real_resolve_seams(later))
    assert marker.exists(), text  # the control: the approved file is the one that gives the login
    assert json.loads(summary_file(home).read_text())["github"]["source"] == "gh"


def test_a_gh_swapped_after_the_approval_and_before_the_login_never_runs(home, offline):
    ran_a, ran_b = home / "ran-A", home / "ran-B"
    gh = install_gh(home, script(ran_a))
    run(installed_gh_fakes(), home)  # setup.json now approves the hash of A
    approved = recorded(home)["gh"]
    assert approved == hashlib.sha256(script(ran_a)).hexdigest()
    ran_a.unlink(missing_ok=True)

    def swap():
        gh.write_bytes(script(ran_b))  # B takes the place of A after the approval was read, before the exec

    later = Fakes()
    code, text = go(later, home, real_resolve_seams(later, before=swap))
    assert not ran_b.exists() and not ran_a.exists(), text
    assert json.loads(summary_file(home).read_text())["github"]["status"] != "ok"


def test_a_gh_swapped_after_the_install_is_never_approved_or_run(home, offline):
    ran_b = home / "ran-B"
    gh = install_gh(home, script(home / "ran-A"))
    fakes = installed_gh_fakes()
    fakes.after_ensure = lambda: gh.write_bytes(script(ran_b))  # the rest of `ensure` after the install is the old window
    code, text = go(fakes, home, real_resolve_seams(fakes))
    assert not ran_b.exists(), text
    assert recorded(home) == {}
    assert trusted_of(fakes) == [{}]  # B is not even asked for its version


def test_the_hash_of_a_fresh_install_is_the_one_taken_at_the_install_not_when_ensure_returns(home):
    original = script(home / "ran-A")
    gh = install_gh(home, original)
    fakes = installed_gh_fakes()
    fakes.after_ensure = lambda: gh.write_bytes(b"#!/bin/sh\nexit 0\n")
    run(fakes, home)
    assert recorded(home) == {}  # the bytes now on disk are not the bytes that were installed


def test_an_install_without_a_hash_taken_at_the_install_is_not_approved(home):
    install_gh(home)
    fakes = Fakes()
    ensure = fakes.seams().ensure
    seams = dataclasses.replace(fakes.seams(), ensure=lambda checks, **kw: [dataclasses.replace(a, sha256=None)
                                                                            for a in ensure(checks, **kw)])
    fakes.actions = [prereqs.Action(name="gh", result="installed", detail="2.60.0")]
    go(fakes, home, seams)
    assert recorded(home) == {}


# --- prereqs.ensure: the real install hashes what it wrote --------------------------------------------------------------

BASE = "https://github.com/cli/cli/releases/download/v1.2.3/"
ARCHIVE = "gh_1.2.3_linux_amd64.tar.gz"
BINARY = b"#!/bin/sh\necho gh\n"


def archive_bytes():
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("gh_1.2.3_linux_amd64/bin/gh")
        info.size = len(BINARY)
        tar.addfile(info, io.BytesIO(BINARY))
    return buffer.getvalue()


ARCHIVE_BYTES = archive_bytes()
PINS = {"gh": {"tag": "v1.2.3", "assets": {"linux-amd64": {"archive": ARCHIVE, "sha256": hashlib.sha256(ARCHIVE_BYTES).hexdigest()}}}}


def fake_get(url):
    if url.endswith("checksums.txt"):
        return f"{hashlib.sha256(ARCHIVE_BYTES).hexdigest()}  {ARCHIVE}\n".encode()
    return ARCHIVE_BYTES


def test_ensure_returns_the_sha256_of_the_bytes_it_installed(tmp_path):
    missing = [prereqs.Check(name="gh", status="missing", required=True, path=None, version=None, minimum=None, fix="", auto="user")]
    actions = prereqs.ensure(missing, environ={"HOME": str(tmp_path), "PATH": ""}, get=fake_get, bin_dir=tmp_path / "bin",
                             platform="linux", machine="x86_64", which=lambda name: None, run=lambda argv, timeout=0: (0, ""),
                             pins=PINS)
    assert [(a.name, a.result) for a in actions] == [("gh", "installed")]
    assert actions[0].sha256 == hashlib.sha256(BINARY).hexdigest()
    assert "sha256" not in actions[0].as_dict()  # the report on the screen and in --json keeps its shape


# --- mutants ------------------------------------------------------------------------------------------------------------


def test_the_github_step_hands_the_approved_file_to_the_login(home):
    gh = install_gh(home)
    run(installed_gh_fakes(), home)
    later = Fakes()
    run(later, home)
    resolve = [c for c in later.calls if c[0] == "resolve"][0][1]
    assert resolve["trusted"] == {"gh": str(gh)}


def test_a_file_that_is_not_approved_is_not_handed_to_the_login(home):
    install_gh(home)
    fakes = Fakes()
    run(fakes, home)
    assert [c for c in fakes.calls if c[0] == "resolve"][0][1]["trusted"] == {}


def foreign(path, monkeypatch):
    """Make `os.stat` report that `path` belongs to a user that is neither root nor the current one."""
    stranger = 12345 + (os.geteuid() == 12345)
    real = os.stat

    def stat(target, *args, **kwargs):
        info = real(target, *args, **kwargs)
        if os.fspath(target) == str(path):
            return types.SimpleNamespace(st_mode=info.st_mode, st_uid=stranger)
        return info

    monkeypatch.setattr(os, "stat", stat)


def test_a_folder_of_another_user_is_not_private(tmp_path, monkeypatch):
    folder = tmp_path / "bin"
    folder.mkdir(mode=0o755)
    assert setup_cli._private_dir(folder) is True
    foreign(folder, monkeypatch)
    assert setup_cli._private_dir(folder) is False


def test_nothing_is_approved_in_a_user_bin_that_belongs_to_another_user(home, monkeypatch):
    gh = install_gh(home)
    run(installed_gh_fakes(), home)
    assert recorded(home) == {"gh": hashlib.sha256(gh.read_bytes()).hexdigest()}
    foreign(gh.parent, monkeypatch)
    later = Fakes()
    run(later, home)
    assert trusted_of(later)[0] == {}
