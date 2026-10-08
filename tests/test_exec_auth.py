"""Tests for exec_auth module (CLI authentication checks).

Testing scenarios:
- CLI present and authenticated (credential file exists)
- CLI present but not authenticated (no credential file)
- CLI missing (binary not in PATH)
- Concurrency with check_all()

Note: Using asyncio.run() instead of pytest-asyncio decorator
for compatibility with project test setup.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from simplicio_loop.exec_auth import (
    AuthCheckResult,
    check,
    check_all,
    check_sync,
    _check_sync_impl,
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


class TestCliMissing:
    """Test when CLI binary is not installed."""

    def test_check_cli_missing(self) -> None:
        """check() returns cli_missing when binary not in PATH."""
        async def run_test():
            with mock.patch("shutil.which", return_value=None):
                result = await check("nonexistent_cli")
                assert result.status == "cli_missing"
                assert "not_in_path" in result.reason_code
        
        asyncio.run(run_test())

    def test_check_sync_cli_missing(self) -> None:
        """check_sync() returns cli_missing when binary not in PATH."""
        with mock.patch("shutil.which", return_value=None):
            result = check_sync("nonexistent_cli")
            assert result.status == "cli_missing"
            assert "not_in_path" in result.reason_code


class TestLoginPresent:
    """Test when CLI is installed with valid credentials."""

    def test_check_with_credential_file(self) -> None:
        """check() returns ok when credential file exists."""
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                fake_home = Path(tmpdir)
                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                cred_file = cred_dir / "auth.json"
                cred_file.write_text("{}")  # Fake credential file (no secrets read)

                with mock.patch("shutil.which", return_value="/usr/bin/claude"):
                    with mock.patch("pathlib.Path.home", return_value=fake_home):
                        result = await check("claude")
                        assert result.status == "ok"
        
        asyncio.run(run_test())

    def test_check_sync_with_credential_file(self) -> None:
        """check_sync() returns ok when credential file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_home = Path(tmpdir)
            cred_dir = fake_home / ".config/codex"
            cred_dir.mkdir(parents=True)
            cred_file = cred_dir / "auth.json"
            cred_file.write_text("{}")  # Fake credential file

            with mock.patch("shutil.which", return_value="/usr/bin/codex"):
                with mock.patch("pathlib.Path.home", return_value=fake_home):
                    result = check_sync("codex")
                    assert result.status == "ok"


class TestLoginMissing:
    """Test when CLI is installed but not authenticated."""

    def test_check_no_credentials(self) -> None:
        """check() returns login_missing when no credential files exist."""
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                fake_home = Path(tmpdir)

                with mock.patch("shutil.which", return_value="/usr/bin/grok"):
                    with mock.patch("pathlib.Path.home", return_value=fake_home):
                        result = await check("grok")
                        assert result.status == "login_missing"
                        assert "no_credentials_found" in result.reason_code
        
        asyncio.run(run_test())

    def test_check_sync_no_credentials(self) -> None:
        """check_sync() returns login_missing when no credential files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_home = Path(tmpdir)

            with mock.patch("shutil.which", return_value="/usr/bin/gemini"):
                with mock.patch("pathlib.Path.home", return_value=fake_home):
                    result = check_sync("gemini")
                    assert result.status == "login_missing"
                    assert "no_credentials_found" in result.reason_code


class TestStatusCommand:
    """Test status command check path."""

    def test_check_status_command_success(self) -> None:
        """check() returns ok when status command succeeds."""
        async def run_test():
            async def mock_create_subprocess_exec(*args, **kwargs):
                """Mock process that returns 0 (success)."""
                class MockProc:
                    async def wait(self):
                        return 0

                return MockProc()

            with mock.patch("shutil.which", return_value="/usr/bin/claude"):
                with mock.patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=mock_create_subprocess_exec,
                ):
                    result = await check("claude")
                    assert result.status == "ok"
        
        asyncio.run(run_test())

    def test_check_status_command_not_found(self) -> None:
        """check() falls back to credential file when status command fails."""
        async def run_test():
            async def mock_create_subprocess_exec(*args, **kwargs):
                raise FileNotFoundError()

            with tempfile.TemporaryDirectory() as tmpdir:
                fake_home = Path(tmpdir)
                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                cred_file = cred_dir / "auth.json"
                cred_file.write_text("{}")

                with mock.patch("shutil.which", return_value="/usr/bin/claude"):
                    with mock.patch("pathlib.Path.home", return_value=fake_home):
                        with mock.patch(
                            "asyncio.create_subprocess_exec",
                            side_effect=mock_create_subprocess_exec,
                        ):
                            result = await check("claude")
                            assert result.status == "ok"
        
        asyncio.run(run_test())


class TestConcurrent:
    """Test concurrent checks with check_all()."""

    def test_check_all_mixed_states(self) -> None:
        """check_all() handles mixed states concurrently."""
        async def run_test():
            with tempfile.TemporaryDirectory() as tmpdir:
                fake_home = Path(tmpdir)
                # Create credential for claude
                cred_dir = fake_home / ".config/claude"
                cred_dir.mkdir(parents=True)
                (cred_dir / "auth.json").write_text("{}")

                def mock_which(cmd):
                    if cmd == "claude":
                        return "/usr/bin/claude"
                    elif cmd == "codex":
                        return "/usr/bin/codex"
                    else:
                        return None

                with mock.patch("shutil.which", side_effect=mock_which):
                    with mock.patch("pathlib.Path.home", return_value=fake_home):
                        results = await check_all(["claude", "codex", "grok"])

                assert len(results) == 3
                assert results[0].status == "ok"  # claude has credentials
                assert results[1].status == "login_missing"  # codex missing credentials
                assert results[2].status == "cli_missing"  # grok not in PATH
        
        asyncio.run(run_test())


class TestNoSecretsInOutput:
    """Test that secrets never appear in output."""

    def test_no_stdout_capture(self) -> None:
        """Status check uses DEVNULL, not PIPE."""
        async def run_test():
            async def mock_create_subprocess_exec(*args, **kwargs):
                # Verify that stdout and stderr are DEVNULL
                assert kwargs.get("stdout") == asyncio.subprocess.DEVNULL
                assert kwargs.get("stderr") == asyncio.subprocess.DEVNULL

                class MockProc:
                    async def wait(self):
                        return 0

                return MockProc()

            with mock.patch("shutil.which", return_value="/usr/bin/claude"):
                with mock.patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=mock_create_subprocess_exec,
                ):
                    result = await check("claude")
                    assert result.status == "ok"
        
        asyncio.run(run_test())

    def test_sync_no_stdout_capture(self) -> None:
        """Sync status check uses capture_output, no logs printed."""
        class MockResult:
            returncode = 0
            stdout = b""  # Should not contain secrets
            stderr = b""

        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            with mock.patch(
                "subprocess.run",
                return_value=MockResult(),
            ) as mock_run:
                result = check_sync("claude")
                assert result.status == "ok"
                # Verify capture_output was used
                assert mock_run.called
                call_kwargs = mock_run.call_args[1]
                assert call_kwargs.get("capture_output") is True


if __name__ == "__main__":
    pytest.main(["-v", __file__])
