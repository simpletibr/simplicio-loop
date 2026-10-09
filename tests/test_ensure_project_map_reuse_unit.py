"""issue #1331: `orient`/`prepare`/`wave`'s `_ensure_project_map` must not
re-run a full Mapper deep index on every call against an unchanged tree, and
its previously-hardcoded 60s timeout (too short for a real ~3,900-file
monorepo, measured in the #1328 wave) must be raised/configurable.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

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


def test_second_call_on_unchanged_tree_does_not_reindex(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    calls = []

    async def fake_run_mapper_index(path, *, timeout=60.0):
        calls.append(path)
        map_dir = Path(path) / ".simplicio-loop"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "project-map.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr(
        "simplicio_loop.map_service_mapper.run_mapper_index", fake_run_mapper_index,
    )
    asyncio.run(cli_impl._ensure_project_map(repo))
    assert len(calls) == 1
    # second call, tree unchanged -> no second full index
    asyncio.run(cli_impl._ensure_project_map(repo))
    assert len(calls) == 1


def test_a_real_tree_change_triggers_reindex(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    calls = []

    async def fake_run_mapper_index(path, *, timeout=60.0):
        calls.append(path)
        map_dir = Path(path) / ".simplicio-loop"
        map_dir.mkdir(parents=True, exist_ok=True)
        (map_dir / "project-map.json").write_text(json.dumps({"files": []}), encoding="utf-8")
        return {"status": "ok"}

    monkeypatch.setattr(
        "simplicio_loop.map_service_mapper.run_mapper_index", fake_run_mapper_index,
    )
    asyncio.run(cli_impl._ensure_project_map(repo))
    assert len(calls) == 1
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    asyncio.run(cli_impl._ensure_project_map(repo))
    assert len(calls) == 2


def test_default_index_timeout_is_raised_past_60s(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOOP_MAPPER_INDEX_TIMEOUT_S", raising=False)
    assert cli_impl._mapper_index_timeout_seconds() > 60.0


def test_index_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_LOOP_MAPPER_INDEX_TIMEOUT_S", "45")
    assert cli_impl._mapper_index_timeout_seconds() == 45.0
