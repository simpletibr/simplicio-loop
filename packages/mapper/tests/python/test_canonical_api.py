"""Tests for the public canonical map sync/async API (issue #236 step 8)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical_api import (  # noqa: E402
    get_effective_map_view,
    get_effective_map_view_async,
)
from simplicio_mapper.mapper.canonical_storage import CANONICAL_CACHE_DIR_ENV_VAR  # noqa: E402
from simplicio_mapper.mapper.effective_view import LazyFileResolver  # noqa: E402


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    src = path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


class CanonicalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self._cache_dir = self.base / "canonical-cache"
        self._saved_cache = os.environ.pop(CANONICAL_CACHE_DIR_ENV_VAR, None)
        os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = str(self._cache_dir)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._saved_cache is not None:
            os.environ[CANONICAL_CACHE_DIR_ENV_VAR] = self._saved_cache
        else:
            os.environ.pop(CANONICAL_CACHE_DIR_ENV_VAR, None)

    def test_sync_api_returns_lazy_view_for_clean_repo(self) -> None:
        repo = self.base / "repo"
        _init_repo(repo, default_branch="trunk")
        view = get_effective_map_view(str(repo))
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.canonical.key.default_branch, "trunk")
        self.assertEqual(view.diagnostics.files_reused, 2)
        self.assertEqual(view.diagnostics.files_remapped, 0)
        self.assertEqual(LazyFileResolver(view).resolve("README.md")["path"], "README.md")

    def test_sync_api_composes_dirty_overlay_without_materializing_artifacts(self) -> None:
        repo = self.base / "repo-dirty"
        _init_repo(repo)
        (repo / "README.md").write_text("dirty\n", encoding="utf-8")
        view = get_effective_map_view(str(repo))
        self.assertIsNotNone(view)
        assert view is not None
        self.assertIsNotNone(view.overlay)
        self.assertTrue(view.overlay.dirty)
        self.assertEqual(view.diagnostics.files_remapped, 1)
        self.assertFalse((repo / ".simplicio-loop" / "project-map.json").exists())

    def test_sync_api_returns_none_for_non_git_directory(self) -> None:
        plain = self.base / "plain"
        plain.mkdir()
        self.assertIsNone(get_effective_map_view(str(plain)))

    def test_async_api_matches_sync_api(self) -> None:
        repo = self.base / "repo-async"
        _init_repo(repo)
        view = asyncio.run(get_effective_map_view_async(str(repo)))
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.canonical.counts["files"], 2)


if __name__ == "__main__":
    unittest.main()
