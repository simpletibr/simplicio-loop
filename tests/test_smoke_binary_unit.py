"""Unit tests for pure functions in scripts/smoke_binary.py and new helpers for dashboard/env/task checks (issue #1576)."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import pytest

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
    (tmp_path / "a" / "__pycache__").mkdir()
    (tmp_path / "a" / "__pycache__" / "x.cpython-313.pyc").write_text("a cache that the wheel side writes")
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
    def test_a_refused_port_is_closed(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        assert sb.port_is_closed(port, timeout=0.5) is True

    def test_a_listening_port_is_open(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            assert sb.port_is_closed(listener.getsockname()[1], timeout=0.3) is False

    def test_it_waits_for_a_server_that_is_stopping(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        threading.Timer(0.3, listener.close).start()
        assert sb.port_is_closed(port, timeout=5.0) is True


class TestServersOf:
    def _proc(self, root, pid, cmdline, exe):
        (root / str(pid)).mkdir()
        (root / str(pid) / "cmdline").write_bytes(cmdline.replace(" ", "\0").encode())
        (root / str(pid) / "exe").symlink_to(exe)

    def test_only_servers_that_run_this_binary_count(self, tmp_path):
        mine, other = tmp_path / "mine", tmp_path / "other"
        mine.write_text("x")
        other.write_text("y")
        root = tmp_path / "proc"
        root.mkdir()
        self._proc(root, 10, "mine -m simplicio_loop.dashboard.server --port 1", mine)
        self._proc(root, 11, "other -m simplicio_loop.dashboard.server --port 2", other)
        self._proc(root, 12, "mine -c pass", mine)
        assert sb.servers_of(mine, str(root)) == [10]

    def test_a_process_that_vanished_is_skipped(self, tmp_path):
        mine = tmp_path / "mine"
        mine.write_text("x")
        root = tmp_path / "proc"
        root.mkdir()
        self._proc(root, 10, "mine -m simplicio_loop.dashboard.server", tmp_path / "gone")  # exe link is dangling
        assert sb.servers_of(mine, str(root)) == []
