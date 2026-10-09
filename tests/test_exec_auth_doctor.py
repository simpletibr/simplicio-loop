"""Tests for exec_auth doctor check integration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


def test_chk_exec_clls_integration():
    """Test that chk_exec_clls is properly integrated in doctor.py."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    
    import doctor
    
    # Verify chk_exec_clls exists
    assert hasattr(doctor, "chk_exec_clls"), "chk_exec_clls not found in doctor.py"
    
    # Verify it's in the CHECKS list
    check_names = [c.__name__ for c in doctor.CHECKS]
    assert "chk_exec_clls" in check_names, "chk_exec_clls not in CHECKS list"
    
    # Call it and verify result structure
    result = doctor.chk_exec_clls()
    assert isinstance(result, dict)
    assert "name" in result
    assert "tier" in result
    assert "status" in result
    assert "msg" in result
    assert result["name"] == "exec CLIs auth"
    assert result["tier"] == "OPTIONAL"
    assert result["status"] in (doctor.OK, doctor.WARN, doctor.FAIL)


def test_exec_auth_reason_codes():
    """Test that exec auth returns proper reason codes."""
    from simplicio_loop.exec_auth import check_sync
    
    # Test with mocked shutil.which
    from unittest import mock
    
    with mock.patch("shutil.which", return_value=None):
        result = check_sync("nonexistent")
        assert "_not_in_path" in result.reason_code or result.status == "cli_missing"
    
    # Verify reason codes follow the expected pattern
    with mock.patch("shutil.which", return_value="/bin/test"):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        
        with TemporaryDirectory() as tmpdir:
            fake_home = Path(tmpdir)
            with mock.patch("pathlib.Path.home", return_value=fake_home):
                result = check_sync("test")
                # Should be login_missing with no_credentials_found reason
                assert result.status == "login_missing"
                assert "no_credentials_found" in result.reason_code


if __name__ == "__main__":
    pytest.main(["-v", __file__])
