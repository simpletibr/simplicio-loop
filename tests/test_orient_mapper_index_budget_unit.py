"""issue #1339: `orient` (plain and `--brief`) must always print valid JSON
within a foreground budget, never block for minutes with empty stdout.

Root cause: `_ensure_project_map` (issue #1328/#1331) ran a fully synchronous
`simplicio-mapper index` (up to its own 300s timeout) with no budget wrapping
the whole `orient`/`orient --brief` call, and any exception inside `orient`
left stdout empty.

This module is TDD-first: it exercises the new budget-aware
`_ensure_project_map(root, budget=...)` path directly (unit) and the
`orient`/`orient_brief` integration with a real, slow fake `simplicio-mapper`
binary on PATH (no mocking of the subprocess boundary itself).
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from simplicio_loop import cli_impl


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(repo), check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(repo), check=True)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=str(repo), check=True)
    return repo


def _install_fake_mapper(tmp_path: Path, *, sleep_s: float) -> Path:
    """A real, slow `simplicio-mapper` on PATH -- no mocking of the process
    boundary. Only `index <path> --json` (the command this issue is about)
    sleeps past the orient budget, then writes a minimal valid envelope and
    project-map.json; every other subcommand (e.g. `orient`, used by the
    Mapper-fallback path when Fast is off/unavailable) answers immediately
    with a trivial READY-shaped envelope, so it never itself becomes an
    unrelated source of slowness in these tests."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "simplicio-mapper"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time, pathlib\n"
        "args = sys.argv[1:]\n"
        "if args and args[0] == 'index':\n"
        f"    time.sleep({sleep_s})\n"
        "    root = pathlib.Path(args[1])\n"
        "    map_dir = root / '.simplicio-loop'\n"
        "    map_dir.mkdir(parents=True, exist_ok=True)\n"
        "    (map_dir / 'project-map.json').write_text(json.dumps({'files': []}))\n"
        "    print(json.dumps({'status': 'ok'}))\n"
        "else:\n"
        "    print(json.dumps({'status': 'ok', 'selection': {'targets': []}}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return bin_dir


@pytest.fixture()
def fake_slow_mapper(tmp_path, monkeypatch):
    bin_dir = _install_fake_mapper(tmp_path, sleep_s=2.0)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("SIMPLICIO_LOOP_ORIENT_BUDGET_S", "0.3")
    return bin_dir


def test_ensure_project_map_bounded_raises_timed_out_then_running(tmp_path, fake_slow_mapper):
    repo = _git_repo(tmp_path)
    started = time.monotonic()
    with pytest.raises(cli_impl.MapperIndexTimedOut):
        asyncio.run(cli_impl._ensure_project_map(repo, budget=cli_impl._orient_budget_seconds()))
    elapsed = time.monotonic() - started
    assert elapsed < 1.5, elapsed  # budget (0.3s) + a small margin, never the full 2s sleep

    # A second call while the backgrounded index is still running is a
    # distinct typed reason -- never a silent re-run, never another full block.
    with pytest.raises(cli_impl.MapperIndexRunning):
        asyncio.run(cli_impl._ensure_project_map(repo, budget=cli_impl._orient_budget_seconds()))

    # Once the background process actually finishes, the next call reuses it
    # (issue #1331 tree-state reuse) instead of raising or reindexing.
    # The detached command now tries the overlay before the (2 s) index, so wait for the process to
    # exit instead of guessing how long both take under load.
    lock = repo / ".simplicio-loop" / cli_impl._MAPPER_INDEX_LOCK_NAME
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and cli_impl._mapper_index_running_info(lock) is not None:
        time.sleep(0.2)
    asyncio.run(cli_impl._ensure_project_map(repo, budget=cli_impl._orient_budget_seconds()))
    assert (repo / ".simplicio-loop" / "project-map.json").is_file()
    assert (repo / ".simplicio-loop" / "mapper-index-state.json").is_file()


def test_orient_brief_prints_valid_json_with_timeout_reason_code(tmp_path, fake_slow_mapper, capsys):
    repo = _git_repo(tmp_path)
    started = time.monotonic()
    rc = cli_impl.orient(str(repo), "fix a.py", brief=True)
    elapsed = time.monotonic() - started
    out = capsys.readouterr().out
    assert out.strip(), "orient --brief must never print empty stdout"
    payload = json.loads(out)  # must be valid JSON -- this is the core AC
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "mapper_index_timeout"
    assert elapsed < 1.5, elapsed
    assert rc != 0


def test_orient_non_brief_prints_valid_json_with_timeout_reason_code(tmp_path, fake_slow_mapper, capsys):
    repo = _git_repo(tmp_path)
    started = time.monotonic()
    rc = cli_impl.orient(str(repo), "fix a.py")
    elapsed = time.monotonic() - started
    out = capsys.readouterr().out
    assert out.strip()
    payload = json.loads(out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "mapper_index_timeout"
    assert elapsed < 1.5, elapsed
    assert rc != 0


def test_orient_that_raises_still_prints_valid_json(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(cli_impl, "_orient_core", boom)
    rc = cli_impl.orient(str(repo), "fix a.py")
    out = capsys.readouterr().out
    assert out.strip()
    payload = json.loads(out)
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "orient_internal_error"
    assert rc == 2


def test_orient_brief_that_raises_still_returns_valid_payload(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(cli_impl, "_orient_core", boom)
    payload = cli_impl.orient_brief(repo, ["fix a.py"])
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "orient_internal_error"
    json.dumps(payload)  # must be JSON-serializable
