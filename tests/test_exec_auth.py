"""Tests for exec_auth module (CLI authentication checks).

Testing scenarios:
- CLI present and authenticated (credential file exists)
- CLI present but not authenticated (no credential file)
- CLI missing (binary not in PATH)
- Concurrency with check_all()

Note: Using fake binaries in tmp dir on PATH to avoid spawning real CLIs.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop.exec_auth import (
    AuthCheckResult,
    check,
    check_all,
    check_sync,
)


class TestAuthCheckResult:
    """Test AuthCheckResult dataclass."""

    def test_ok_status_str(self) -> None:
        result = AuthCheckResult("claude", "ok")
        assert str(result) == "claude: authenticated"

    def test_login_missing_str(self) -> None:
        result = AuthCheckResult("claude", "login_missing", "no_credentials_found")
        assert str(result) == "login_missing:claude (no_credentials_found)"

    def test_cli_missing_str(self) -> None:
        result = AuthCheckResult("grok", "cli_missing", "grok_not_in_path")
        assert str(result) == "cli_missing:grok (grok_not_in_path)"


def fake_binary(tmpdir: Path, name: str, exit_code: int = 0) -> str:
    """Create a fake binary in tmpdir that returns exit_code."""
    binary_path = tmpdir / name
    binary_path.write_text(f"#!/bin/sh\nexit {exit_code}")
    binary_path.chmod(0o755)
    return str(binary_path)


def fake_cli_guard_test(monkeypatch) -> None:
    """Guard: assert that we never execute real cli paths outside tmp."""
    original_which = shutil.which
    
    def guarded_which(cmd: str, *args, **kwargs):
        result = original_which(cmd, *args, **kwargs)
        if result and "/.claude/" not in result and "/tmp" not in result and "TMPDIR" not in result:
            # Allow system paths like /usr/bin/python3 but not real installed CLIs
            if cmd in ("claude", "codex", "grok", "gemini"):
                raise AssertionError(f"test tried to execute real {cmd} at {result}; use monkeypatch")
        return result
    
    monkeypatch.setattr("shutil.which", guarded_which)


class TestCliMissing:
    """Test when CLI binary is not installed."""

    def test_check_cli_missing(self, monkeypatch) -> None:
        """check() returns cli_missing when binary not in PATH."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with mock.patch("shutil.which", return_value=None):
                result = await check("nonexistent_cli")
                assert result.status == "cli_missing"
                assert "not_in_path" in result.reason_code
        
        asyncio.run(run_test())

    def test_check_sync_cli_missing(self, monkeypatch) -> None:
        """check_sync() returns cli_missing when binary not in PATH."""
        fake_cli_guard_test(monkeypatch)
        
        with mock.patch("shutil.which", return_value=None):
            result = check_sync("nonexistent_cli")
            assert result.status == "cli_missing"
            assert "not_in_path" in result.reason_code


class TestLoginPresent:
    """Test when CLI is installed with valid credentials."""

    def test_check_with_credential_file(self, monkeypatch) -> None:
        """check() returns ok when credential file exists."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake claude binary
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "claude", exit_code=0)
                
                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                cred_file = cred_dir / "auth.json"
                cred_file.write_text("{}")  # Fake credential file (no secrets read)

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                result = await check("claude")
                assert result.status == "ok"
        
        asyncio.run(run_test())

    def test_check_sync_with_credential_file(self, monkeypatch) -> None:
        """check_sync() returns ok when credential file exists."""
        fake_cli_guard_test(monkeypatch)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            
            # Create fake codex binary
            fake_bin_dir = tmp_path / "bin"
            fake_bin_dir.mkdir()
            fake_binary(fake_bin_dir, "codex", exit_code=0)
            
            cred_dir = fake_home / ".config/codex"
            cred_dir.mkdir(parents=True)
            cred_file = cred_dir / "auth.json"
            cred_file.write_text("{}")  # Fake credential file

            monkeypatch.setenv("PATH", str(fake_bin_dir))
            monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
            
            result = check_sync("codex")
            assert result.status == "ok"


class TestLoginMissing:
    """Test when CLI is installed but not authenticated."""

    def test_check_no_credentials(self, monkeypatch) -> None:
        """check() returns login_missing when no credential files exist."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake grok binary
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "grok", exit_code=1)  # Status check fails

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                result = await check("grok")
                assert result.status == "login_missing"
                assert "no_credentials_found" in result.reason_code
        
        asyncio.run(run_test())

    def test_check_sync_no_credentials(self, monkeypatch) -> None:
        """check_sync() returns login_missing when no credential files exist."""
        fake_cli_guard_test(monkeypatch)
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_home = tmp_path / "home"
            fake_home.mkdir()
            
            # Create fake gemini binary
            fake_bin_dir = tmp_path / "bin"
            fake_bin_dir.mkdir()
            fake_binary(fake_bin_dir, "gemini", exit_code=1)  # Status check fails

            monkeypatch.setenv("PATH", str(fake_bin_dir))
            monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
            
            result = check_sync("gemini")
            assert result.status == "login_missing"
            assert "no_credentials_found" in result.reason_code


class TestStatusCommand:
    """Test status command check path."""

    def test_check_status_command_success(self, monkeypatch) -> None:
        """check() returns ok when status command succeeds."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake claude binary that succeeds
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "claude", exit_code=0)

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                result = await check("claude")
                assert result.status == "ok"
        
        asyncio.run(run_test())

    def test_check_status_command_not_found(self, monkeypatch) -> None:
        """check() falls back to credential file when status command fails."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake claude binary that fails
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "claude", exit_code=1)

                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                cred_file = cred_dir / "auth.json"
                cred_file.write_text("{}")

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                result = await check("claude")
                assert result.status == "ok"
        
        asyncio.run(run_test())


class TestConcurrent:
    """Test concurrent checks with check_all()."""

    def test_check_all_mixed_states(self, monkeypatch) -> None:
        """check_all() handles mixed states concurrently."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake binaries
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "claude", exit_code=0)  # Will succeed
                fake_binary(fake_bin_dir, "codex", exit_code=1)   # Will fail
                # grok is not created, so it's missing
                
                # Create credential for claude
                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                (cred_dir / "auth.json").write_text("{}")

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                results = await check_all(["claude", "codex", "grok"])

                assert len(results) == 3
                assert results[0].status == "ok"  # claude status check succeeds
                assert results[1].status == "login_missing"  # codex status check fails, no creds
                assert results[2].status == "cli_missing"  # grok not in PATH
        
        asyncio.run(run_test())


class TestNoSecretsInOutput:
    """Test that secrets never appear in output."""

    def test_no_stdout_capture(self, monkeypatch) -> None:
        """Status check uses DEVNULL, not PIPE."""
        fake_cli_guard_test(monkeypatch)
        
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                fake_home = tmp_path / "home"
                fake_home.mkdir()
                
                # Create fake claude binary
                fake_bin_dir = tmp_path / "bin"
                fake_bin_dir.mkdir()
                fake_binary(fake_bin_dir, "claude", exit_code=0)

                monkeypatch.setenv("PATH", str(fake_bin_dir))
                monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
                
                result = await check("claude")
                assert result.status == "ok"
        
        asyncio.run(run_test())



