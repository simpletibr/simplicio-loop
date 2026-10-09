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


def test_binary_step_commands_returns_one_command(tmp_path):
    """binary_step_commands returns a single argv list for the build_binary command."""
    scratch = tmp_path / "scratch"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    version = "3.48.1"

    commands = rr.binary_step_commands(scratch, out_dir, work_dir, version)

    assert isinstance(commands, list)
    assert len(commands) == 1
    assert isinstance(commands[0], list)

    # The single command: build_binary with --allow-dirty, --version, --out, --work, --python
    command = commands[0]
    assert command[1] == "scripts/build_binary.py" or str(scratch / "scripts" / "build_binary.py") in str(command)
    assert "--allow-dirty" in command
    assert "--version" in command
    assert version in command
    assert "--out" in command
    assert str(out_dir) in command
    assert "--work" in command
    assert str(work_dir) in command
    assert "--python" in command
    assert sys.executable in command


def test_binary_step_commands_uses_sys_executable_as_python(tmp_path):
    """binary_step_commands uses sys.executable as the --python argument."""
    scratch = tmp_path / "scratch"
    out_dir = tmp_path / "out"
    work_dir = tmp_path / "work"
    version = "3.48.1"

    commands = rr.binary_step_commands(scratch, out_dir, work_dir, version)

    command = commands[0]
    # Find the --python argument
    try:
        python_idx = command.index("--python")
        assert command[python_idx + 1] == sys.executable
    except (ValueError, IndexError):
        pytest.fail("--python argument or its value not found in command")


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


def test_run_binary_step_sbom_failure_returns_false_and_sets_reason(tmp_path, monkeypatch):
    """R5: if build_sbom returns ok=False, run_binary_step returns False and sets reason."""
    version = "3.48.1"
    out_dir = tmp_path / "binary"

    def fake_run(command, **kwargs):
        if any(str(part).endswith("build_binary.py") for part in command):
            out_dir.mkdir(parents=True, exist_ok=True)
            asset = bb.binary_name(version, bb.detect_os(), bb.detect_arch())
            (out_dir / asset).write_bytes(b"fake executable")
            bb.write_checksums(out_dir, version)
            return subprocess.CompletedProcess(command, 0, "", "")
        elif command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, f"simplicio-loop {version}\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    def fake_sbom_failure(scratch, **kwargs):
        return {"ok": False, "error": "SBOM generation failed"}

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    monkeypatch.setattr(rr, "build_sbom", fake_sbom_failure)
    
    receipt = {"steps": {}}
    result = rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version)

    assert result is False
    assert receipt["steps"]["binary"]["ok"] is False
    assert "SBOM of the executable failed" in receipt["steps"]["binary"]["reason"]


def test_run_binary_step_deterministic_environment(tmp_path, monkeypatch):
    """R6: the build command runs with SOURCE_DATE_EPOCH, PYTHONHASHSEED, TZ, no PYTHONPATH."""
    version = "3.48.1"
    out_dir = tmp_path / "binary"
    captured_env = {}

    def fake_run(command, **kwargs):
        if any(str(part).endswith("build_binary.py") for part in command):
            captured_env.update(kwargs.get("env", {}))
            out_dir.mkdir(parents=True, exist_ok=True)
            asset = bb.binary_name(version, bb.detect_os(), bb.detect_arch())
            (out_dir / asset).write_bytes(b"fake executable")
            bb.write_checksums(out_dir, version)
            return subprocess.CompletedProcess(command, 0, "", "")
        elif command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, f"simplicio-loop {version}\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    monkeypatch.setattr(rr, "build_sbom", lambda scratch, **kwargs: {"ok": True})
    
    # Set PYTHONPATH in os.environ to verify it's dropped
    test_pythonpath = "/some/path"
    original_pythonpath = os.environ.get("PYTHONPATH")
    try:
        os.environ["PYTHONPATH"] = test_pythonpath
        
        receipt = {"steps": {}}
        rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version)

        # Verify the environment passed to the build command
        assert captured_env.get("SOURCE_DATE_EPOCH") == "1700000000"
        assert captured_env.get("PYTHONHASHSEED") == "0"
        assert captured_env.get("TZ") == "UTC"
        assert "PYTHONPATH" not in captured_env
    finally:
        if original_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = original_pythonpath


def test_run_binary_step_succeeds_and_writes_the_sbom(tmp_path, monkeypatch):
    version = "3.48.1"
    out_dir = tmp_path / "binary"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if any(str(part).endswith("build_binary.py") for part in command):
            out_dir.mkdir(parents=True, exist_ok=True)
            asset = bb.binary_name(version, bb.detect_os(), bb.detect_arch())
            (out_dir / asset).write_bytes(b"fake executable")
            bb.write_checksums(out_dir, version)
            return subprocess.CompletedProcess(command, 0, "", "")
        elif command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, f"simplicio-loop {version}\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    monkeypatch.setattr(rr, "build_sbom", lambda scratch, **kwargs: {"ok": True, "artifact": str(kwargs["artifact"])})
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version) is True

    step = receipt["steps"]["binary"]
    assert step["ok"] is True
    assert step["asset"].startswith("simplicio-loop-v3.48.1-")
    assert (tmp_path / "binary" / "sbom-binary.json").is_file()
    assert len(calls) == 2  # build_binary and --version


def test_run_binary_step_reports_the_failing_command(tmp_path, monkeypatch):
    """When the build command fails, run_binary_step reports the failure."""
    version = "3.48.1"
    out_dir = tmp_path / "binary"
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        if len(calls) == 1:  # First call to build_binary fails
            return subprocess.CompletedProcess(command, 3, "", "boom\nlast line")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version) is False

    step = receipt["steps"]["binary"]
    assert step["ok"] is False
    assert step["stderr_tail"] == ["boom", "last line"]


def test_run_binary_step_refuses_a_wrong_version_output(tmp_path, monkeypatch):
    """When --version output doesn't match, run_binary_step fails."""
    version = "3.48.1"
    out_dir = tmp_path / "binary"

    def fake_run(command, **kwargs):
        if any(str(part).endswith("build_binary.py") for part in command):
            out_dir.mkdir(parents=True, exist_ok=True)
            asset = bb.binary_name(version, bb.detect_os(), bb.detect_arch())
            (out_dir / asset).write_bytes(b"fake executable")
            bb.write_checksums(out_dir, version)
        elif command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "simplicio-loop 9.9.9\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    monkeypatch.setattr(rr, "_git", lambda repo, *args: "1700000000")
    monkeypatch.setattr(rr, "build_sbom", lambda scratch, **kwargs: {"ok": True})
    receipt = {"steps": {}}

    assert rr.run_binary_step(tmp_path, tmp_path / "scratch", tmp_path, receipt, tmp_path / "w.whl", "sha", version) is False
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
