"""issue #1474: the mapper index and the turbo verify never block the event loop.

Both run as ``asyncio.create_subprocess_exec`` children in their own process group under
``asyncio.wait_for``; a timeout kills the whole group, not just the direct child. The fake
processes are real slow shell scripts, so the process boundary itself is not mocked.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, map_service_mapper as msm, turbo_cli
from simplicio_loop.turbo_run import TurboRun


def _verify(root, command):
    """The verify runs inside a run, so its command events have a run directory to land in."""
    return turbo_cli._run_verify(root, command, TurboRun(root, "host"))


async def _ticks_during(coro):
    """Await ``coro`` while a sibling task counts loop turns; a blocked loop counts none."""
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        result = await coro
    finally:
        task.cancel()
    return result, ticks


def _is_gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return True
    return state == "Z"


async def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    for _ in range(int(seconds / 0.05)):
        if _is_gone(pid):
            return True
        await asyncio.sleep(0.05)
    return _is_gone(pid)


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                 ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        subprocess.run(["git", *args], cwd=str(repo), check=True)
    return repo


def _slow_index_mapper(tmp_path: Path, monkeypatch, sleep_s: float) -> Path:
    """A real ``simplicio-mapper`` on PATH whose ``index`` sleeps, then writes a project map."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    _script(bin_dir / "simplicio-mapper", (
        f"sleep {sleep_s}\n"
        "mkdir -p \"$2/.simplicio-loop\"\n"
        "echo '{\"files\": []}' > \"$2/.simplicio-loop/project-map.json\"\n"
        "echo '{\"status\": \"ok\"}'\n"
    ))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return bin_dir


def test_the_mapper_index_keeps_the_event_loop_running(tmp_path, monkeypatch):
    _slow_index_mapper(tmp_path, monkeypatch, 0.5)
    envelope, ticks = asyncio.run(_ticks_during(msm.run_mapper_index(str(tmp_path), timeout=10)))
    assert envelope == {"status": "ok"}
    assert ticks >= 10, ticks  # ~50 when the loop is free, 0 when the call blocks it


def test_a_mapper_index_timeout_kills_the_whole_process_group(tmp_path, monkeypatch):
    pidfile = tmp_path / "child.pid"
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    _script(bin_dir / "simplicio-mapper", f"sleep 60 &\necho $! > {pidfile}\nwait\n")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    async def scenario():
        with pytest.raises(subprocess.TimeoutExpired):
            # Wide enough for the shell script to start and record its child on a loaded host.
            await msm.run_mapper_index(str(tmp_path), timeout=4.0)
        return int(pidfile.read_text())

    child = asyncio.run(scenario())
    assert asyncio.run(_wait_gone(child)), "the grandchild survived the timeout"


def test_the_bounded_index_keeps_the_event_loop_running(tmp_path, monkeypatch):
    _slow_index_mapper(tmp_path, monkeypatch, 0.5)
    repo = _git_repo(tmp_path)
    _none, ticks = asyncio.run(_ticks_during(cli_impl._ensure_project_map(repo, budget=10.0)))
    assert ticks >= 10, ticks
    assert (repo / ".simplicio-loop" / "project-map.json").is_file()
    assert json.loads((repo / ".simplicio-loop" / "mapper-index-state.json").read_text())["tree_state"]


def test_a_bounded_index_over_budget_times_out_without_blocking_the_loop(tmp_path, monkeypatch):
    # A 1 s budget against a 6 s index: the loop gets many turns inside the budget even on a
    # loaded host, and the detached index is still running when the assertions look at it.
    _slow_index_mapper(tmp_path, monkeypatch, 6)
    repo = _git_repo(tmp_path)

    async def scenario():
        with pytest.raises(cli_impl.MapperIndexTimedOut):
            await cli_impl._ensure_project_map(repo, budget=1.0)

    _none, ticks = asyncio.run(_ticks_during(scenario()))
    assert ticks >= 5, ticks
    lock = json.loads((repo / ".simplicio-loop" / "mapper-index.lock").read_text())
    assert not _is_gone(lock["pid"]), "the detached index must outlive the call (#1339)"
    os.killpg(lock["pid"], 9)


def test_the_verify_keeps_the_event_loop_running_and_captures_both_streams(tmp_path):
    (report, output), ticks = asyncio.run(_ticks_during(
        _verify(tmp_path, "sleep 0.5; echo out; echo err >&2; exit 3")))
    assert ticks >= 10, ticks
    assert report["passed"] is False and report["returncode"] == 3
    assert output == "out\nerr" and report["output_tail"] == output


def test_a_passing_verify_reports_passed(tmp_path):
    (report, output), _ticks = asyncio.run(_ticks_during(_verify(tmp_path, "echo fine")))
    assert report == {"command": "echo fine", "passed": True, "returncode": 0, "output_tail": "fine"}
    assert output == "fine"


def test_a_verify_timeout_kills_the_whole_process_group(tmp_path, monkeypatch):
    monkeypatch.setattr(turbo_cli, "VERIFY_TIMEOUT_S", 0.5)
    pidfile = tmp_path / "child.pid"

    async def scenario():
        result = await _verify(tmp_path, f"sleep 60 & echo $! > {pidfile}; wait")
        return result, int(pidfile.read_text())

    (report, output), child = asyncio.run(scenario())
    assert report == {"command": f"sleep 60 & echo $! > {pidfile}; wait", "passed": False, "returncode": None,
                      "output_tail": "verify timed out after 0.5s"}
    assert output == ""
    assert asyncio.run(_wait_gone(child)), "the grandchild survived the timeout"
