"""Unit tests for simplicio_mapper.mapper.canonical_builder (issue #236, ADR-008 step 3).

Builds a real ``CanonicalMapManifest`` against real temporary git repositories
(never a mocked subprocess) -- covers custom default-branch names, dirty
worktrees, idempotent reuse, and clean ``git worktree`` teardown, per the
ADR's migration plan step 3 and its acceptance criteria.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical import CanonicalMapManifest  # noqa: E402
from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_storage import canonical_manifest_dir  # noqa: E402


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _digest_dir(storage_root: str, digest: str) -> Path:
    """Mirror `canonical_builder`'s own path arithmetic (via `canonical_storage`)."""
    return Path(canonical_manifest_dir(storage_root, digest))


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


def _worktree_list(path: Path) -> str:
    return _run(["worktree", "list"], path).stdout


class BuildCanonicalManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")

    def _build(self, repo: Path, config_fingerprint: str = "cfg-1") -> CanonicalMapManifest:
        manifest = build_canonical_manifest(str(repo), self.storage_root, config_fingerprint)
        self.assertIsNotNone(manifest, "expected a populated CanonicalMapManifest, got None")
        return manifest

    def test_builds_manifest_for_default_branch_main(self) -> None:
        repo = self.base / "repo-main"
        _init_repo(repo, default_branch="main")
        manifest = self._build(repo)

        self.assertEqual(manifest.key.default_branch, "main")
        self.assertEqual(manifest.counts["files"], 2)
        self.assertIn("project_map", manifest.artifact_paths)
        self.assertIn("precedent_index", manifest.artifact_paths)
        self.assertIn("symbol_index", manifest.artifact_paths)
        self.assertIn("call_graph", manifest.artifact_paths)
        # __post_init__ validation already ran during construction (frozen
        # dataclass) -- re-run it explicitly here so a future refactor that
        # bypasses the constructor (e.g. building via `object.__new__`) still
        # gets caught by this test.
        manifest.__post_init__()

    def test_builds_manifest_for_default_branch_master(self) -> None:
        repo = self.base / "repo-master"
        _init_repo(repo, default_branch="master")
        manifest = self._build(repo)
        self.assertEqual(manifest.key.default_branch, "master")

    def test_builds_manifest_for_custom_default_branch_name(self) -> None:
        repo = self.base / "repo-trunk"
        _init_repo(repo, default_branch="trunk")
        manifest = self._build(repo)
        self.assertEqual(manifest.key.default_branch, "trunk")
        self.assertEqual(manifest.key.commit_sha, _run(["rev-parse", "trunk"], repo).stdout.strip())

    def test_artifacts_are_written_under_content_addressed_digest_dir(self) -> None:
        repo = self.base / "repo-storage"
        _init_repo(repo)
        manifest = self._build(repo)

        digest_dir = _digest_dir(self.storage_root, manifest.key.digest())
        self.assertTrue(digest_dir.is_dir())
        for file_name in manifest.artifact_paths.values():
            self.assertTrue((digest_dir / file_name).is_file(), file_name)
        self.assertTrue((digest_dir / "manifest.json").is_file())

    def test_dirty_worktree_does_not_leak_into_canonical_manifest(self) -> None:
        repo = self.base / "repo-dirty"
        _init_repo(repo)
        manifest_clean = self._build(repo, config_fingerprint="cfg-clean")

        # Introduce uncommitted changes: a brand-new untracked file plus a
        # modification to a tracked file. Neither is committed.
        (repo / "src" / "dirty.py").write_text("DIRTY = True\n", encoding="utf-8")
        (repo / "README.md").write_text("hello (locally edited)\n", encoding="utf-8")

        manifest_dirty_run = build_canonical_manifest(str(repo), self.storage_root, "cfg-clean")
        self.assertIsNotNone(manifest_dirty_run)

        # Same commit -> same digest -> same manifest (dirty state must not
        # change the canonical key or its artifacts at all).
        self.assertEqual(manifest_dirty_run.key.digest(), manifest_clean.key.digest())
        self.assertEqual(manifest_dirty_run.counts["files"], 2)

        digest_dir = _digest_dir(self.storage_root, manifest_dirty_run.key.digest())
        project_map_path = digest_dir / manifest_dirty_run.artifact_paths["project_map"]
        import orjson

        project_map = orjson.loads(project_map_path.read_bytes())
        entries_by_path = {entry["path"]: entry for entry in project_map["files"]}
        self.assertNotIn("src/dirty.py", entries_by_path)
        # The detached checkout is exactly `commit_sha`'s tree -- `git
        # status` inside it must report clean, so `git_status` here must not
        # carry over the caller worktree's "modified"/"untracked" state.
        readme_entry = entries_by_path["README.md"]
        self.assertNotEqual(readme_entry.get("git_status"), "modified")

    def test_two_builds_of_same_commit_are_idempotent(self) -> None:
        repo = self.base / "repo-idempotent"
        _init_repo(repo)
        first = self._build(repo, config_fingerprint="cfg-idem")
        second = self._build(repo, config_fingerprint="cfg-idem")
        self.assertEqual(first, second)
        self.assertEqual(first.created_at, second.created_at)
        self.assertEqual(first.generation, second.generation)

    def test_different_config_fingerprint_never_shares_manifest(self) -> None:
        repo = self.base / "repo-config-fingerprint"
        _init_repo(repo)
        first = self._build(repo, config_fingerprint="cfg-a")
        second = self._build(repo, config_fingerprint="cfg-b")
        self.assertNotEqual(first.key.digest(), second.key.digest())
        self.assertNotEqual(
            _digest_dir(self.storage_root, first.key.digest()),
            _digest_dir(self.storage_root, second.key.digest()),
        )

    def test_cleanup_leaves_no_stray_git_worktree_entries(self) -> None:
        repo = self.base / "repo-cleanup"
        _init_repo(repo)
        before = _worktree_list(repo)
        self.assertEqual(before.count("\n"), 1, before)

        self._build(repo)

        after = _worktree_list(repo)
        self.assertEqual(before, after)
        self.assertEqual(after.count("\n"), 1, after)

    def test_multiple_worktrees_on_same_commit_reuse_the_same_digest(self) -> None:
        repo = self.base / "repo-multi-worktree"
        _init_repo(repo)
        second_worktree = self.base / "repo-multi-worktree-second"
        _run(["worktree", "add", str(second_worktree)], repo)
        try:
            manifest_a = self._build(repo, config_fingerprint="cfg-shared")
            manifest_b = build_canonical_manifest(
                str(second_worktree), self.storage_root, "cfg-shared"
            )
            self.assertIsNotNone(manifest_b)
            self.assertEqual(manifest_a.key.digest(), manifest_b.key.digest())
            self.assertEqual(manifest_a, manifest_b)
        finally:
            _run(["worktree", "remove", "--force", str(second_worktree)], repo)

    def test_returns_none_for_non_git_directory(self) -> None:
        plain_dir = self.base / "plain"
        plain_dir.mkdir()
        manifest = build_canonical_manifest(str(plain_dir), self.storage_root, "cfg-none")
        self.assertIsNone(manifest)


if __name__ == "__main__":
    unittest.main()
