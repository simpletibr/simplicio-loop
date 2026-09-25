"""Scoped .simplicio/data roots: core vs per-project isolation."""
from __future__ import annotations

from pathlib import Path

from simplicio_mapper.store.project_scope import (
    core_data_root,
    project_data_root,
    resolve_project_slug,
    resolve_scoped_layout,
    sanitize_project_slug,
)
from simplicio_mapper.store.unify import unify_memory


def test_sanitize_and_slug_from_git_style_remote() -> None:
    assert sanitize_project_slug("https://github.com/wesleysimplicio/simplicio-mapper.git") == "simplicio-mapper"
    assert sanitize_project_slug("My Project!") == "my-project"


def test_core_data_root_is_under_dot_simplicio(tmp_path: Path) -> None:
    root = core_data_root(home=tmp_path, environ={})
    assert root == (tmp_path / ".simplicio" / "data").resolve()


def test_project_data_root_isolated_under_repo(tmp_path: Path) -> None:
    repo = tmp_path / "workspace" / "AppOne"
    repo.mkdir(parents=True)
    root, slug, source = project_data_root(repo, environ={})
    assert slug == "appone"
    assert source == "directory"
    assert root == (repo / ".simplicio" / "data" / "appone").resolve()


def test_scoped_layout_separates_core_and_project(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "repos" / "proj-a"
    repo.mkdir(parents=True)
    layout = resolve_scoped_layout(
        repo_root=repo,
        home=home,
        environ={},  # ignore process SIMPLICIO_* so isolation is deterministic
        include_project=True,
    )
    assert layout.core.root == (home / ".simplicio" / "data").resolve()
    assert layout.project is not None
    assert layout.project_slug == "proj-a"
    assert "proj-a" in str(layout.project.root)
    assert layout.core.root != layout.project.root
    # DBs are different paths
    assert layout.core.database("memory.sqlite") != layout.project.database("memory.sqlite")


def test_project_unify_does_not_write_into_core(tmp_path: Path) -> None:
    home = tmp_path / "h"
    home.mkdir()
    repo = tmp_path / "r" / "demo"
    repo.mkdir(parents=True)
    layout = resolve_scoped_layout(repo_root=repo, home=home, environ={}, include_project=True)
    layout.core.ensure_root()
    assert layout.project is not None
    layout.project.ensure_root()
    core_u = unify_memory(data_dir=layout.core.root, absorb_legacy_home=False, rebuild_fts=False)
    proj_u = unify_memory(data_dir=layout.project.root, absorb_legacy_home=False, rebuild_fts=False)
    assert Path(core_u["canonical_database"]).parent == layout.core.root
    assert Path(proj_u["canonical_database"]).parent == layout.project.root
    assert Path(core_u["canonical_database"]) != Path(proj_u["canonical_database"])


def test_env_project_slug_wins(tmp_path: Path) -> None:
    repo = tmp_path / "ignored-name"
    repo.mkdir()
    slug, source = resolve_project_slug(
        repo_root=repo,
        environ={"SIMPLICIO_PROJECT": "Codex-Theme-Alpha"},
    )
    assert slug == "codex-theme-alpha"
    assert source.startswith("env:")
