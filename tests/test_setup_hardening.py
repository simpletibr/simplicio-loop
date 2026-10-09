"""Setup hardening primitives (#1637)."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from simplicio_loop import setup_hardening as sh

posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")


def test_minimal_env_drops_tokens():
    source = {"PATH": "/usr/bin", "GH_TOKEN": "x", "GITHUB_TOKEN": "y", "LANG": "C"}
    assert sh.minimal_env(source) == {"PATH": "/usr/bin", "LANG": "C"}


def test_path_warnings_flags_relative_and_local_bin(tmp_path):
    home = tmp_path / "home"
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True)
    safe = tmp_path / "safe"
    safe.mkdir()
    safe.chmod(0o755)
    value = os.pathsep.join(["bin", "", str(local_bin), str(safe)])
    reasons = dict(sh.path_warnings(value, home=str(home)))
    assert reasons["bin"] == "relative"
    assert reasons[""] == "relative"
    assert reasons[str(local_bin)] == "user_local_bin"
    assert str(safe) not in reasons
    assert sh.safe_path(value, home=str(home)) == str(safe)


@posix_only
def test_path_warnings_flags_world_writable_dir(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    warnings = sh.path_warnings(str(shared), home=str(tmp_path))
    assert warnings == [(str(shared), "writable_by_others")]


@pytest.mark.parametrize(
    "url",
    [
        "https://raw.githubusercontent.com/cli/cli/trunk/x",
        "https://gist.githubusercontent.com/u/x",
        "http://github.com/cli/cli/releases/download/v1/gh.tgz",
        "https://github.com:8443/x",
        "https://user:pw@github.com/x",
        "https://evil.example/x",
    ],
)
def test_download_allowlist_rejects(url):
    assert not sh.is_allowed_download(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/astral-sh/uv/releases/download/0.5.0/uv.tar.gz",
        "https://release-assets.githubusercontent.com/github-production-release-asset/1",
        "https://objects.githubusercontent.com/github-production-release-asset-2e65be/1",
    ],
)
def test_download_allowlist_accepts_release_hosts(url):
    assert sh.is_allowed_download(url)


def test_redirect_without_location_is_refused():
    with pytest.raises(sh.RedirectError, match="no Location"):
        sh.redirect_target("https://github.com/x", 302, {})


def test_redirect_resolves_relative_and_checks_host():
    target = sh.redirect_target("https://github.com/a/b", 302, {"Location": "/c"})
    assert target == "https://github.com/c"
    with pytest.raises(sh.RedirectError, match="allowlist"):
        sh.redirect_target(
            "https://github.com/a", 301, {"Location": "https://raw.githubusercontent.com/x"}
        )


@posix_only
def test_read_private_text_accepts_private_file(tmp_path):
    target = tmp_path / "setup.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    assert sh.read_private_text(target) == "{}"


@posix_only
def test_read_private_text_refuses_fifo_without_blocking(tmp_path):
    fifo = tmp_path / "setup.json"
    os.mkfifo(fifo)
    with pytest.raises(sh.UnsafeFileError, match="regular"):
        sh.read_private_text(fifo)


@posix_only
def test_read_private_text_refuses_symlink(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    real.chmod(0o600)
    link = tmp_path / "setup.json"
    link.symlink_to(real)
    with pytest.raises(sh.UnsafeFileError):
        sh.read_private_text(link)


@posix_only
def test_read_private_text_refuses_shared_writable(tmp_path):
    target = tmp_path / "setup.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o666)
    with pytest.raises(sh.UnsafeFileError, match="writable"):
        sh.read_private_text(target)


def test_read_private_text_missing_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        sh.read_private_text(tmp_path / "absent.json")


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_isolated_git_cwd_is_outside_any_repository():
    source = {"PATH": os.environ.get("PATH", ""), "GH_TOKEN": "x"}
    with sh.isolated_git_cwd(source) as (cwd, env):
        assert "GH_TOKEN" not in env
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode != 0
