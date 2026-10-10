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


def foreign_dir(tmp_path, monkeypatch):
    """A 755 folder whose owner is neither root nor the current user."""
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    theirs.chmod(0o755)
    if os.geteuid() == 0:
        try:
            os.chown(theirs, 4242, 4242)
        except PermissionError:
            pytest.skip("this system refuses chown to another user; the injected-owner tests cover the decision")
    else:
        monkeypatch.setattr(os, "geteuid", lambda: theirs.stat().st_uid + 1)
    return theirs


@posix_only
def test_a_775_folder_of_the_current_user_is_not_unsafe_like_homebrew(tmp_path):
    brew = tmp_path / "homebrew" / "bin"
    brew.mkdir(parents=True)
    brew.chmod(0o775)  # group write on a folder the user owns: Homebrew installs like this and its admin group is trusted
    assert sh.path_warnings(str(brew), home=str(tmp_path / "home")) == []
    assert sh.safe_path(str(brew), home=str(tmp_path / "home")) == str(brew)


@posix_only
def test_a_sticky_world_writable_folder_is_still_unsafe(tmp_path):
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    tmp.chmod(0o1777)  # like /tmp: anyone can still add a program to it
    assert sh.path_warnings(str(tmp), home=str(tmp_path)) == [(str(tmp), "writable_by_others")]


@posix_only
def test_a_folder_owned_by_someone_else_is_unsafe_even_without_a_write_bit(tmp_path, monkeypatch):
    theirs = foreign_dir(tmp_path, monkeypatch)
    assert sh.path_warnings(str(theirs), home=str(tmp_path)) == [(str(theirs), "foreign_owner")]
    assert sh.safe_path(str(theirs), home=str(tmp_path)) == ""


@posix_only
def test_a_folder_that_does_not_exist_is_not_a_warning(tmp_path):
    assert sh.path_warnings(str(tmp_path / "nope"), home=str(tmp_path)) == []


def test_probe_env_is_minimal_and_its_path_has_only_safe_entries(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    env = sh.probe_env({"PATH": os.pathsep.join(["rel", str(safe)]), "HOME": str(tmp_path), "GH_TOKEN": "x"})
    assert env == {"PATH": str(safe), "HOME": str(tmp_path)}


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


@posix_only
def test_read_private_text_refuses_a_file_owned_by_someone_else(tmp_path, monkeypatch):
    target = tmp_path / "setup.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    assert sh.read_private_text(target) == "{}"
    monkeypatch.setattr(os, "geteuid", lambda: target.stat().st_uid + 1)
    with pytest.raises(sh.UnsafeFileError, match="owned by"):
        sh.read_private_text(target)


@posix_only
def test_read_private_text_stops_at_max_bytes(tmp_path):
    target = tmp_path / "setup.json"
    target.write_text("x" * 100_000, encoding="utf-8")  # more than one 64 KiB read
    target.chmod(0o600)
    assert len(sh.read_private_text(target, max_bytes=100_000)) == 100_000
    with pytest.raises(sh.UnsafeFileError, match="larger"):
        sh.read_private_text(target, max_bytes=99_999)


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



@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_isolated_git_cwd_never_finds_a_repository_above_it_and_never_prompts(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("TMPDIR", str(repo))  # the isolated folder is created INSIDE a repository
    monkeypatch.setattr("tempfile.tempdir", None)
    with sh.isolated_git_cwd({"PATH": os.environ.get("PATH", "")}) as (cwd, env):
        assert os.path.dirname(cwd) == str(repo)
        found = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd, env=env, capture_output=True, text=True)
        assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert found.returncode != 0


def test_exec_path_is_never_empty_because_an_empty_path_searches_the_current_directory(tmp_path):
    assert sh.exec_path("rel" + os.pathsep + "", home=str(tmp_path)) == os.defpath
    safe = tmp_path / "safe"
    safe.mkdir()
    assert sh.exec_path(os.pathsep.join(["rel", str(safe)]), home=str(tmp_path)) == str(safe)


def make_dir(path, mode):
    path.mkdir()
    path.chmod(mode)
    return path


@posix_only
def test_a_safe_folder_under_a_parent_that_anyone_can_rewrite_is_unsafe(tmp_path):
    parent = make_dir(tmp_path / "open", 0o777)  # no sticky bit: anyone can rename or replace what is inside
    child = make_dir(parent / "bin", 0o755)
    assert sh.path_warnings(str(child), home=str(tmp_path / "h")) == [(str(child), "writable_parent")]


@posix_only
def test_a_sticky_parent_like_tmp_does_not_make_a_private_child_unsafe(tmp_path):
    parent = make_dir(tmp_path / "sticky", 0o1777)
    child = make_dir(parent / "bin", 0o755)
    assert sh.path_warnings(str(child), home=str(tmp_path / "h")) == []


@posix_only
def test_a_symlink_is_judged_by_its_target_and_by_the_folder_that_holds_the_link(tmp_path):
    safe = make_dir(tmp_path / "safe", 0o755)
    link = tmp_path / "link"
    link.symlink_to(safe)
    assert sh.path_warnings(str(link), home=str(tmp_path / "h")) == []  # a link in a private folder to a private folder
    open_dir = make_dir(tmp_path / "open", 0o777)
    loose = open_dir / "link"
    loose.symlink_to(safe)  # the target is fine but anyone can repoint this link
    assert sh.path_warnings(str(loose), home=str(tmp_path / "h")) == [(str(loose), "writable_parent")]
    shared = make_dir(tmp_path / "shared", 0o777)
    to_shared = tmp_path / "to-shared"
    to_shared.symlink_to(shared)
    assert sh.path_warnings(str(to_shared), home=str(tmp_path / "h")) == [(str(to_shared), "writable_by_others")]


@posix_only
@pytest.mark.parametrize("spelling", ["{bin}/", "{home}/.local/./bin", "{home}/.local//bin", "{home}/.local/../.local/bin"])
def test_local_bin_is_found_however_it_is_spelled(tmp_path, spelling):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    entry = spelling.format(home=home, bin=home / ".local" / "bin")
    assert [reason for _, reason in sh.path_warnings(entry, home=str(home))] == ["user_local_bin"]


@posix_only
def test_local_bin_is_found_through_a_symlink_alias_and_when_home_itself_is_a_link(tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(home / ".local" / "bin")
    assert [r for _, r in sh.path_warnings(str(alias), home=str(home))] == ["user_local_bin"]
    home_link = tmp_path / "home-link"
    home_link.symlink_to(home)
    assert [r for _, r in sh.path_warnings(str(home / ".local" / "bin"), home=str(home_link))] == ["user_local_bin"]


@posix_only
def test_an_entry_that_cannot_be_examined_is_unsafe_but_one_that_does_not_exist_is_not(tmp_path, monkeypatch):
    shut = make_dir(tmp_path / "shut", 0o755)
    real_lstat = os.lstat

    def refuse(path, *args, **kwargs):
        if os.fspath(path) == str(shut):
            raise PermissionError(13, "denied", str(path))
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(os, "lstat", refuse)
    monkeypatch.setattr(os, "stat", refuse)
    assert sh.path_warnings(str(shut), home=str(tmp_path / "h")) == [(str(shut), "unreadable")]
    assert sh.path_warnings(str(tmp_path / "missing"), home=str(tmp_path / "h")) == []
    assert sh.safe_path(str(shut), home=str(tmp_path / "h")) == ""


@posix_only
def test_find_ignored_names_the_first_program_of_each_name_in_an_unsafe_entry(tmp_path):
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    (local / "claude").write_text("#!/bin/sh\n")
    (local / "claude").chmod(0o755)
    (local / "codex").write_text("not executable")
    (local / "codex").chmod(0o644)
    safe = make_dir(tmp_path / "safe", 0o755)
    found = sh.find_ignored({"PATH": os.pathsep.join([str(local), str(safe)]), "HOME": str(home)}, ["claude", "codex", "gemini"])
    assert found == {"claude": (str(local / "claude"), "user_local_bin")}


def test_isolated_git_cwd_gives_git_a_path_without_unsafe_entries(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    with sh.isolated_git_cwd({"PATH": os.pathsep.join(["rel", str(safe)]), "HOME": str(tmp_path)}) as (workdir, env):
        assert env["PATH"] == str(safe)


@posix_only
@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0, reason="chown to another user needs root")
def test_a_folder_above_the_entry_that_belongs_to_a_foreign_user_makes_it_unsafe(tmp_path):
    parent = make_dir(tmp_path / "theirs", 0o755)
    child = make_dir(parent / "bin", 0o755)
    try:
        os.chown(parent, 4242, 4242)  # the child stays root's, but its owner can rename it away and put another folder in its place
    except PermissionError:
        pytest.skip("this system refuses chown to another user; the injected-owner tests cover the decision")
    assert sh.path_warnings(str(child), home=str(tmp_path / "h")) == [(str(child), "foreign_owner")]


def owned_by_another_user(monkeypatch, folder):
    """Make `folder` count as owned by someone else, without chown: the ownership test sees its inode."""
    monkeypatch.setattr(sh, "_foreign", lambda info: info.st_ino == folder.stat().st_ino)


@posix_only
def test_a_folder_of_another_owner_is_unsafe_on_any_system(tmp_path, monkeypatch):
    theirs = make_dir(tmp_path / "theirs", 0o755)
    owned_by_another_user(monkeypatch, theirs)
    assert sh.path_warnings(str(theirs), home=str(tmp_path)) == [(str(theirs), "foreign_owner")]


@posix_only
def test_a_folder_above_an_entry_of_another_owner_is_unsafe_on_any_system(tmp_path, monkeypatch):
    parent = make_dir(tmp_path / "theirs", 0o755)
    child = make_dir(parent / "bin", 0o755)
    owned_by_another_user(monkeypatch, parent)
    assert sh.path_warnings(str(child), home=str(tmp_path / "h")) == [(str(child), "foreign_owner")]


INSTALL_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "UV_CA_CERT", "UV_NATIVE_TLS",
    "UV_HTTP_TIMEOUT", "UV_PYTHON_INSTALL_MIRROR", "UV_PYTHON_INSTALL_DIR",
)


@pytest.mark.parametrize("key", INSTALL_KEYS)
def test_install_env_keeps_each_proxy_and_certificate_setting(key):
    assert sh.install_env({"PATH": "/usr/bin", "HOME": "/h", key: "value"})[key] == "value"


@pytest.mark.parametrize("key", INSTALL_KEYS)
def test_probe_env_never_carries_a_proxy_or_certificate_setting(key):
    assert key not in sh.probe_env({"PATH": "/usr/bin", "HOME": "/h", key: "value"})


@pytest.mark.parametrize(
    "key", ["GH_TOKEN", "GITHUB_TOKEN", "UV_PUBLISH_TOKEN", "UV_INDEX_PRIVATE_PASSWORD", "UV_INDEX_PRIVATE_USERNAME", "ANTHROPIC_API_KEY"]
)
def test_install_env_never_carries_a_credential(key):
    assert key not in sh.install_env({"PATH": "/usr/bin", "HOME": "/h", key: "FAKE"})


def test_install_env_keeps_the_proxy_and_still_drops_unsafe_path_entries(tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir()
    env = sh.install_env({"PATH": os.pathsep.join(["rel", str(safe)]), "HOME": str(tmp_path), "HTTPS_PROXY": "http://proxy.example.invalid:3128"})
    assert env == {"PATH": str(safe), "HOME": str(tmp_path), "HTTPS_PROXY": "http://proxy.example.invalid:3128"}
