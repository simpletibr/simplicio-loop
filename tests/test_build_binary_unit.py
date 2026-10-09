"""Fast unit tests for the pure parts of scripts/build_binary.py (issue #1576).

The real build runs PyInstaller and takes minutes. It is covered by scripts/smoke_binary.py and by
the external_integration test in tests/test_binary_smoke_external.py.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_binary as bb  # noqa: E402

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.mark.parametrize("platform, expected", [
    ("linux", "linux"), ("darwin", "darwin"), ("win32", "windows"), ("cygwin", "windows"),
])
def test_detect_os(platform, expected):
    assert bb.detect_os(platform) == expected


def test_detect_os_refuses_unknown_platforms():
    with pytest.raises(bb.BuildError, match="freebsd"):
        bb.detect_os("freebsd14")


@pytest.mark.parametrize("machine, expected", [
    ("x86_64", "x86_64"), ("AMD64", "x86_64"), ("amd64", "x86_64"),
    ("aarch64", "aarch64"), ("arm64", "aarch64"), ("ARM64", "aarch64"),
])
def test_detect_arch(machine, expected):
    assert bb.detect_arch(machine) == expected


def test_detect_arch_refuses_unknown_machines():
    with pytest.raises(bb.BuildError, match="riscv64"):
        bb.detect_arch("riscv64")


def test_binary_name_follows_the_release_contract():
    assert bb.binary_name("3.48.1", "linux", "x86_64") == "simplicio-loop-v3.48.1-linux-x86_64"
    assert bb.binary_name("3.48.1", "darwin", "aarch64") == "simplicio-loop-v3.48.1-darwin-aarch64"
    assert bb.binary_name("3.48.1", "windows", "x86_64") == "simplicio-loop-v3.48.1-windows-x86_64.exe"


@pytest.mark.parametrize("version, os_name, arch", [
    ("v3.48.1", "linux", "x86_64"), ("", "linux", "x86_64"), ("3.48.1/../x", "linux", "x86_64"),
    ("3.48.1", "macos", "x86_64"), ("3.48.1", "linux", "arm64"),
])
def test_binary_name_refuses_values_outside_the_contract(version, os_name, arch):
    with pytest.raises(bb.BuildError):
        bb.binary_name(version, os_name, arch)


def test_parse_asset_name_is_the_inverse_of_binary_name():
    for os_name in ("linux", "darwin", "windows"):
        for arch in ("x86_64", "aarch64"):
            name = bb.binary_name("3.48.1", os_name, arch)
            assert bb.parse_asset_name(name) == ("3.48.1", os_name, arch)
    assert bb.parse_asset_name("SHA256SUMS") is None
    assert bb.parse_asset_name("simplicio-loop-v3.48.1-linux-x86_64.exe") is None  # .exe is Windows only


def test_project_version_reads_pyproject():
    expected = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert bb.project_version(ROOT) == expected


def test_sha256sums_round_trip_and_sort_by_name():
    text = bb.format_sha256sums({"zeta": DIGEST_B, "alpha": DIGEST_A})
    assert text == f"{DIGEST_A}  alpha\n{DIGEST_B}  zeta\n"
    assert bb.parse_sha256sums(text) == {"alpha": DIGEST_A, "zeta": DIGEST_B}


@pytest.mark.parametrize("line", [
    f"{DIGEST_A} alpha",            # one space
    f"{DIGEST_A}  ",                # no name
    f"{'A' * 64}  alpha",           # upper case hex
    f"{'a' * 63}  alpha",           # short digest
    f"{DIGEST_A}  dir/alpha",       # a path, not a file name
    f"{DIGEST_A}  *alpha",          # sha256sum binary-mode marker
    "not a line",
])
def test_parse_sha256sums_refuses_malformed_lines(line):
    with pytest.raises(bb.BuildError):
        bb.parse_sha256sums(line + "\n")


def test_parse_sha256sums_refuses_a_name_that_appears_twice():
    with pytest.raises(bb.BuildError, match="twice"):
        bb.parse_sha256sums(f"{DIGEST_A}  alpha\n{DIGEST_B}  alpha\n")


def test_write_checksums_hashes_the_assets_in_a_directory(tmp_path):
    payload = b"binary bytes"
    (tmp_path / "simplicio-loop-v1.2.3-linux-x86_64").write_bytes(payload)
    (tmp_path / "notes.txt").write_text("not an asset")
    sums = bb.write_checksums(tmp_path)
    assert sums == tmp_path / "SHA256SUMS"
    assert bb.parse_sha256sums(sums.read_text()) == {
        "simplicio-loop-v1.2.3-linux-x86_64": hashlib.sha256(payload).hexdigest()}
    (tmp_path / "simplicio-loop-v1.2.3-windows-x86_64.exe").write_bytes(b"exe")
    (tmp_path / "simplicio-loop-v1.2.2-linux-aarch64").write_bytes(b"old")
    bb.write_checksums(tmp_path)
    assert len(bb.parse_sha256sums(sums.read_text())) == 3  # rebuilt from every asset in the directory
    bb.write_checksums(tmp_path, version="1.2.3")
    assert set(bb.parse_sha256sums(sums.read_text())) == {
        "simplicio-loop-v1.2.3-linux-x86_64", "simplicio-loop-v1.2.3-windows-x86_64.exe"}


def test_pyinstaller_command_is_deterministic_and_excludes_dev_dependencies(tmp_path):
    args = dict(python="py", mode="onefile", dist=tmp_path / "d", work=tmp_path / "w")
    first = bb.pyinstaller_command(**args)
    assert first == bb.pyinstaller_command(**args)
    assert first[:2] == ["py", str(bb.RUNNER)]
    assert "--onefile" in first and "--onedir" not in first
    assert "--noupx" in first and "--clean" in first
    assert first[first.index("--additional-hooks-dir") + 1] == str(bb.HOOKS_DIR)
    assert first[-1] == str(bb.ENTRY)
    excluded = {first[i + 1] for i, item in enumerate(first) if item == "--exclude-module"}
    assert {"pytest", "_pytest", "setuptools", "coverage", "cryptography"} <= excluded
    assert "--onedir" in bb.pyinstaller_command(**{**args, "mode": "onedir"})
    with pytest.raises(bb.BuildError):
        bb.pyinstaller_command(**{**args, "mode": "zip"})


def test_build_environment_pins_the_sources_of_nondeterminism():
    env = bb.build_environment({"PATH": "/bin", "PYTHONPATH": "/leak", "HOME": "/h"}, epoch=1700000000)
    assert env["SOURCE_DATE_EPOCH"] == "1700000000"
    assert env["PYTHONHASHSEED"] == "0"
    assert env["TZ"] == "UTC"
    assert "PYTHONPATH" not in env
    assert env["PATH"] == "/bin"


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, stdin=subprocess.DEVNULL,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(repo)})


def test_dirty_tree_is_refused_unless_allowed(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "init")
    bb.check_clean_tree(tmp_path, allow_dirty=False)  # clean: no error
    (tmp_path / "a.txt").write_text("2")
    with pytest.raises(bb.BuildError, match="dirty"):
        bb.check_clean_tree(tmp_path, allow_dirty=False)
    bb.check_clean_tree(tmp_path, allow_dirty=True)


def test_source_date_epoch_is_the_commit_time(tmp_path):
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "init")
    committed = int(subprocess.run(["git", "log", "-1", "--format=%ct"], cwd=tmp_path, check=True,
                                   capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout)
    assert bb.source_date_epoch(tmp_path) == committed


def test_packaging_inputs_exist():
    assert bb.ENTRY.is_file() and bb.RUNNER.is_file()
    assert (bb.HOOKS_DIR / "hook-simplicio_loop.py").is_file()
    assert "simplicio_loop.frozen" in bb.ENTRY.read_text(encoding="utf-8")


def test_the_binary_directory_is_never_committed():
    ignored = subprocess.run(["git", "check-ignore", "-q", "dist/binary/simplicio-loop-v1-linux-x86_64"],
                             cwd=ROOT, stdin=subprocess.DEVNULL)
    assert ignored.returncode == 0
