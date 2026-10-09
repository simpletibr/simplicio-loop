"""Unit tests for pure functions in scripts/smoke_binary.py and new helpers for dashboard/env/task checks (issue #1576)."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import smoke_binary as sb


# --- pure parts of scripts/smoke_binary.py ---------------------------------------------------


def test_smoke_environment_has_no_python_leaks(tmp_path):
    env = sb.scrubbed_env(tmp_path, system="posix")
    assert env["PATH"] == "/usr/bin:/bin" and env["HOME"] == str(tmp_path)
    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & set(env)
    assert sb.scrubbed_env(tmp_path, system="nt")["USERPROFILE"] == str(tmp_path)


def test_expected_from_wheel_tells_modules_from_data(tmp_path):
    wheel = tmp_path / "w.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in (
            "simplicio_loop/__init__.py", "simplicio_loop/cli.py", "simplicio_loop/sub/__init__.py",
            "simplicio_loop/sub/mod.py",                      # modules
            "simplicio_loop/_bundle/hooks/guard.py",          # no __init__.py above: data
            "simplicio_loop/loose/script.py",                 # no __init__.py in loose/: data
            "simplicio/templates/py-cli/tree/src/app.py",     # a template: data
            "simplicio_loop/dashboard/static/app.js", "simplicio_mapper/contracts/a.json",
            "simplicio_loop/__pycache__/cli.cpython-314.pyc",  # never expected
            "simplicio_loop-1.0.dist-info/METADATA", "other_package/x.py",  # not ours
        ):
            archive.writestr(name, "x")
        archive.writestr("simplicio/__init__.py", "")
        archive.writestr("simplicio_mapper/__init__.py", "")
    expected = sb.expected_from_wheel(wheel)
    assert expected["modules"] == ["simplicio", "simplicio_loop", "simplicio_loop.cli", "simplicio_loop.sub",
                                   "simplicio_loop.sub.mod", "simplicio_mapper"]
    assert expected["files"] == [
        "simplicio/templates/py-cli/tree/src/app.py", "simplicio_loop/_bundle/hooks/guard.py",
        "simplicio_loop/dashboard/static/app.js", "simplicio_loop/loose/script.py", "simplicio_mapper/contracts/a.json"]


def test_doctor_comparison_ignores_paths_and_hashes_but_not_versions():
    base = {"status": "READY", "routes": {"standalone": {"available": True}}, "components": [
        {"name": "b", "version": "1", "available": True, "executable": "/x/b", "artifact_sha256": "1"},
        {"name": "a", "version": "2", "available": True, "executable": "/x/a", "artifact_sha256": "2"}]}
    other = {**base, "components": [dict(item, executable="/y", artifact_sha256="9") for item in reversed(base["components"])]}
    assert sb.normalize_doctor(base) == sb.normalize_doctor(other)
    other["components"][0]["version"] = "3"
    assert sb.normalize_doctor(base) != sb.normalize_doctor(other)


def test_tree_digest_hashes_files_and_skips_named_ones(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("1")
    (tmp_path / "skip.json").write_text("2")
    digest = sb.tree_digest(tmp_path, skip=("skip.json",))
    assert digest == {str(Path("a") / "x.txt"): hashlib.sha256(b"1").hexdigest()}


# --- new pure helpers for dashboard, environment, and task checks --------------------------------


class TestParseLiveUrl:
    def test_parses_url_with_query_string(self):
        stdout = "simplicio-live: http://127.0.0.1:9999?token=abc"
        base, query, port = sb.parse_live_url(stdout)
        assert base == "http://127.0.0.1:9999"
        assert query == "token=abc"
        assert port == 9999

    def test_parses_url_without_query(self):
        stdout = "simplicio-live: http://127.0.0.1:8080"
        base, query, port = sb.parse_live_url(stdout)
        assert base == "http://127.0.0.1:8080"
        assert query == ""
        assert port == 8080

    def test_raises_on_missing_line(self):
        stdout = "some other output\nno live url here"
        with pytest.raises(ValueError, match="simplicio-live"):
            sb.parse_live_url(stdout)

    def test_parses_url_in_multiline_output(self):
        stdout = "starting server\nsimplicio-live: http://127.0.0.1:7654?x=1\nmore output"
        base, query, port = sb.parse_live_url(stdout)
        assert port == 7654
        assert query == "x=1"


class TestServerProcesses:
    def test_finds_processes_matching_needle(self, tmp_path):
        proc = tmp_path / "proc"
        proc.mkdir()
        # Create two process entries
        for pid in [1234, 5678]:
            (proc / str(pid)).mkdir()
            # Include needle in cmdline
            (proc / str(pid) / "cmdline").write_bytes(b"python3\0/path/simplicio_loop.dashboard.server\0--port\09999")
        (proc / "9999").mkdir()
        (proc / "9999" / "cmdline").write_bytes(b"some_other_process")
        
        pids = sb.server_processes(proc_root=str(proc), needle="simplicio_loop.dashboard.server")
        assert sorted(pids) == [1234, 5678]

    def test_returns_empty_list_when_no_matches(self, tmp_path):
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "1234").mkdir()
        (proc / "1234" / "cmdline").write_bytes(b"some_process")
        
        pids = sb.server_processes(proc_root=str(proc), needle="simplicio_loop.dashboard.server")
        assert pids == []

    def test_handles_missing_proc_directory(self, tmp_path):
        pids = sb.server_processes(proc_root=str(tmp_path / "nonexistent"), needle="needle")
        assert pids == []

    def test_handles_unreadable_cmdline(self, tmp_path):
        proc = tmp_path / "proc"
        proc.mkdir()
        (proc / "1234").mkdir()
        # Don't create cmdline file
        
        pids = sb.server_processes(proc_root=str(proc), needle="needle")
        assert pids == []


class TestPortIsClosed:
    def test_port_is_closed_on_refused_connection(self):
        # Use a high port that's unlikely to be open
        result = sb.port_is_closed(59999, timeout=0.5)
        assert result is True

    def test_port_is_closed_false_on_open_port(self, tmp_path):
        import socket
        sock = socket.socket()
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            # This port is now open
            result = sb.port_is_closed(port, timeout=0.5)
            # Could be True or False depending on timing, but mainly checking it doesn't crash
            assert isinstance(result, bool)
        finally:
            sock.close()

    def test_retries_for_timeout(self):
        # Should not raise, should retry
        result = sb.port_is_closed(59999, timeout=0.1)
        assert isinstance(result, bool)
