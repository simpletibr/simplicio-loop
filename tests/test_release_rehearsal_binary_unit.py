"""Fast unit tests for the optional --binary step in scripts/release_rehearsal.py (issue #1576)."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_binary as bb  # noqa: E402
import release_rehearsal as rr  # noqa: E402


def test_binary_step_commands_returns_three_commands(tmp_path):
    """binary_step_commands returns a list of three argv lists for venv, pip install, and build."""
    scratch = tmp_path / "scratch"
    venv = tmp_path / "venv"
    wheel = tmp_path / "wheel.whl"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    version = "3.48.1"

    commands = rr.binary_step_commands(scratch, venv, wheel, out_dir, work_dir, version)

    assert isinstance(commands, list)
    assert len(commands) == 3
    assert all(isinstance(cmd, list) for cmd in commands)

    # Command 1: venv creation
    assert commands[0] == [sys.executable, "-m", "venv", str(venv)]

    # Command 2: pip install wheel and pyinstaller
    venv_python = (venv / "bin" / "python") if os.name != "nt" else (venv / "Scripts" / "python.exe")
    assert commands[1] == [
        str(venv_python), "-m", "pip", "install", "--disable-pip-version-check",
        str(wheel), "pyinstaller"
    ]

    # Command 3: build_binary with --allow-dirty and --version
    assert commands[2] == [
        str(venv_python), str(scratch / "scripts" / "build_binary.py"),
        "--allow-dirty", "--version", version, "--out", str(out_dir), "--work", str(work_dir)
    ]


def test_binary_step_commands_uses_scripts_python_exe_on_windows(tmp_path):
    """On Windows, venv python path uses Scripts/python.exe."""
    scratch = tmp_path / "scratch"
    venv = tmp_path / "venv"
    wheel = tmp_path / "wheel.whl"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    version = "3.48.1"

    commands = rr.binary_step_commands(scratch, venv, wheel, out_dir, work_dir, version)

    # Extract venv_python from commands[1]
    venv_python_str = commands[1][0]
    venv_python = Path(venv_python_str)

    if os.name == "nt":
        assert venv_python.name == "python.exe"
        assert "Scripts" in str(venv_python)
    else:
        assert venv_python.name == "python"
        assert "bin" in str(venv_python)


def test_verify_binary_assets_ok_case(tmp_path):
    """verify_binary_assets returns ok=True when SHA256SUMS exists, file matches, and version matches."""
    version = "3.48.1"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Create a binary asset
    os_name = bb.detect_os()
    arch = bb.detect_arch()
    asset_name = bb.binary_name(version, os_name, arch)
    asset_path = out_dir / asset_name
    asset_path.write_bytes(b"fake binary content")

    # Write SHA256SUMS
    bb.write_checksums(out_dir, version=version)

    result = rr.verify_binary_assets(out_dir, version)

    assert result["ok"] is True
    assert result["asset"] == asset_name
    assert result["sha256"] == hashlib.sha256(b"fake binary content").hexdigest()
    assert result["reason"] == ""


def test_verify_binary_assets_missing_sha256sums(tmp_path):
    """verify_binary_assets returns ok=False when SHA256SUMS is missing."""
    version = "3.48.1"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Create a binary asset but no SHA256SUMS
    os_name = bb.detect_os()
    arch = bb.detect_arch()
    asset_name = bb.binary_name(version, os_name, arch)
    asset_path = out_dir / asset_name
    asset_path.write_bytes(b"fake binary content")

    result = rr.verify_binary_assets(out_dir, version)

    assert result["ok"] is False
    assert result["asset"] is None
    assert result["sha256"] is None
    assert "SHA256SUMS" in result["reason"]


def test_verify_binary_assets_digest_mismatch(tmp_path):
    """verify_binary_assets returns ok=False when file digest doesn't match SHA256SUMS."""
    version = "3.48.1"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Create a binary asset
    os_name = bb.detect_os()
    arch = bb.detect_arch()
    asset_name = bb.binary_name(version, os_name, arch)
    asset_path = out_dir / asset_name
    asset_path.write_bytes(b"fake binary content")

    # Write SHA256SUMS
    bb.write_checksums(out_dir, version=version)

    # Modify the file
    asset_path.write_bytes(b"different content")

    result = rr.verify_binary_assets(out_dir, version)

    assert result["ok"] is False
    assert "digest" in result["reason"].lower()


def test_verify_binary_assets_wrong_version(tmp_path):
    """verify_binary_assets returns ok=False when no asset matches the given version."""
    version = "3.48.1"
    other_version = "3.47.0"
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    # Create a binary asset with a different version
    os_name = bb.detect_os()
    arch = bb.detect_arch()
    asset_name = bb.binary_name(other_version, os_name, arch)
    asset_path = out_dir / asset_name
    asset_path.write_bytes(b"fake binary content")

    # Write SHA256SUMS
    bb.write_checksums(out_dir)

    result = rr.verify_binary_assets(out_dir, version)

    assert result["ok"] is False
    assert result["asset"] is None
    assert "version" in result["reason"].lower()


def test_verify_binary_assets_refuses_a_second_entry(tmp_path):
    """A rehearsal builds one executable: another entry in SHA256SUMS is an error."""
    version = "3.48.1"
    for name in (bb.binary_name(version, bb.detect_os(), bb.detect_arch()),
                 bb.binary_name("3.48.0", bb.detect_os(), bb.detect_arch())):
        (tmp_path / name).write_bytes(name.encode())
    bb.write_checksums(tmp_path)

    result = rr.verify_binary_assets(tmp_path, version)

    assert result["ok"] is False
    assert "exactly one" in result["reason"]


def _fake_pipeline(monkeypatch, out_dir, version, *, version_output=None, fail_at=None):
    """Replace subprocess.run: the third command writes an asset and SHA256SUMS like build_binary."""
    asset = bb.binary_name(version, bb.detect_os(), bb.detect_arch())
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if fail_at is not None and len(calls) == fail_at + 1:
            return subprocess.CompletedProcess(command, 3, "", "boom\nlast line")
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, version_output or f"simplicio-loop {version}\n", "")
        if any(str(part).endswith("build_binary.py") for part in command):
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / asset).write_bytes(b"fake executable")
            bb.write_checksums(out_dir, version)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    monkeypatch.setattr(rr, "build_sbom", lambda scratch, **kwargs: {"ok": True, "artifact": str(kwargs["artifact"])})
    return calls


def test_run_binary_step_succeeds_and_writes_the_sbom(tmp_path, monkeypatch):
    version = "3.48.1"
    calls = _fake_pipeline(monkeypatch, tmp_path / "binary", version)
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version) is True

    step = receipt["steps"]["binary"]
    assert step["ok"] is True and step["returncodes"] == [0, 0, 0]
    assert step["asset"].startswith("simplicio-loop-v3.48.1-")
    assert (tmp_path / "binary" / "sbom-binary.json").is_file()
    assert len(calls) == 4  # venv, pip, build, --version


def test_run_binary_step_reports_the_failing_command(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch, tmp_path / "binary", "3.48.1", fail_at=1)
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", "3.48.1") is False

    step = receipt["steps"]["binary"]
    assert step["ok"] is False and step["returncodes"] == [0, 3]
    assert step["stderr_tail"] == ["boom", "last line"]


def test_run_binary_step_refuses_a_wrong_version_output(tmp_path, monkeypatch):
    _fake_pipeline(monkeypatch, tmp_path / "binary", "3.48.1", version_output="simplicio-loop 9.9.9\n")
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", "3.48.1") is False
    assert "9.9.9" in receipt["steps"]["binary"]["reason"]


def test_argparse_accepts_binary_flag():
    """The --binary flag is accepted by the argument parser and defaults to False."""
    parser = rr.build_parser()

    # Test with --binary
    args_with_binary = parser.parse_args(["run", "--binary"])
    assert args_with_binary.binary is True

    # Test without --binary (default)
    args_without_binary = parser.parse_args(["run"])
    assert args_without_binary.binary is False
