"""Mapper ↔ Fast integration status (with unified memory SoT)."""
from __future__ import annotations

from pathlib import Path

from simplicio_mapper.store.fast_link import mapper_fast_status
from simplicio_mapper.store.unify import unify_memory


def test_mapper_fast_status_standalone_and_repo(tmp_path: Path) -> None:
    data = tmp_path / "data"
    # empty unify still creates schema
    unify_memory(data_dir=data, absorb_legacy_home=False, rebuild_fts=False)

    status = mapper_fast_status(data_dir=data)
    assert status["schema"] == "simplicio.mapper-fast-link/v1"
    assert "mapper" in status
    assert "fast" in status
    assert "memory" in status
    assert status["policy"]["memory_sot"].startswith("SIMPLICIO_DATA_DIR")
    assert ".sfast" in status["policy"]["fast_snapshot"]
    # certification must import on Windows
    assert status["mapper"]["modules"].get("fast_certification") is True

    repo = tmp_path / "repo"
    (repo / ".simplicio" / "fast").mkdir(parents=True)
    (repo / ".simplicio" / "project-map.json").write_text("{}", encoding="utf-8")
    repo_status = mapper_fast_status(repo=repo, data_dir=data)
    assert repo_status["repo"] is not None
    assert repo_status["repo"]["project_map"]["exists"] is True
    assert "fast_build" in repo_status["repo"]["commands"]
