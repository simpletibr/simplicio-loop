"""Unit tests for simplicio_mapper.mapper.canonical_overlay (issue #236, ADR-008 step 4).

Covers ``compute_worktree_overlay`` -- the delta between a worktree's current
state (working tree, including staged/unstaged/untracked changes) and a
canonical ``CanonicalMapKey``'s base commit -- against real temporary git
repositories (never mocked ``git`` output, except for explicit error-path
tests using ``unittest.mock.patch``). No production pipeline wiring exists
yet; these tests only exercise the new module in isolation, per the ADR's
migration plan.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper import canonical_overlay  # noqa: E402
from simplicio_mapper.mapper.canonical import (  # noqa: E402
    CanonicalMapKey,
    WorktreeOverlay,
)
from simplicio_mapper.mapper.canonical_overlay import (  # noqa: E402
    compute_worktree_overlay,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


def _current_commit_sha(path: Path) -> str:
    return _run(["rev-parse", "HEAD"], path).stdout.strip()


def _current_tree_sha(path: Path) -> str:
    return _run(["rev-parse", "HEAD^{tree}"], path).stdout.strip()


def _base_key(repo: Path, **overrides) -> CanonicalMapKey:
    fields = {
        "repo_identity": "repo-id-1",
        "default_branch": "main",
        "commit_sha": _current_commit_sha(repo),
        "tree_sha": _current_tree_sha(repo),
        "schema_version": 1,
        "mapper_version": "0.0.0-test",
        "config_fingerprint": "cfg-fp-1",
    }
    fields.update(overrides)
    return CanonicalMapKey(**fields)


class ComputeWorktreeOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _assert_valid_overlay(self, overlay: WorktreeOverlay) -> None:
        self.assertIsInstance(overlay, WorktreeOverlay)
        self.assertEqual(overlay.schema, "simplicio.worktree-overlay/v1")
        self.assertEqual(overlay.schema_version, 1)
        # __post_init__ already ran at construction time (frozen dataclass);
        # re-invoking it here proves the returned instance still satisfies
        # its own schema invariants (nothing mutated it after the fact).
        overlay.__post_init__()

    def test_zero_drift_returns_empty_clean_overlay(self) -> None:
        repo = self.root / "zero-drift"
        _init_repo(repo)
        key = _base_key(repo)

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertEqual(overlay.changed_files, ())
        self.assertEqual(overlay.tombstones, ())
        self.assertFalse(overlay.dirty)
        self.assertEqual(overlay.worktree_commit_sha, key.commit_sha)
        self.assertTrue(overlay.is_compatible_with_base())

    def test_untracked_file_reported_as_added(self) -> None:
        repo = self.root / "untracked"
        _init_repo(repo)
        key = _base_key(repo)
        (repo / "new_file.py").write_text("print('hi')\n", encoding="utf-8")

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertTrue(overlay.dirty)
        paths = {c.path: c for c in overlay.changed_files}
        self.assertIn("new_file.py", paths)
        change = paths["new_file.py"]
        self.assertEqual(change.change_type, "added")
        self.assertIsNotNone(change.content_digest)
        self.assertEqual(overlay.tombstones, ())

    def test_staged_new_file_reported_as_added(self) -> None:
        repo = self.root / "staged"
        _init_repo(repo)
        key = _base_key(repo)
        (repo / "staged_file.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "staged_file.py"], repo)

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertTrue(overlay.dirty)
        paths = {c.path: c for c in overlay.changed_files}
        self.assertEqual(paths["staged_file.py"].change_type, "added")

    def test_unstaged_modification_reported_as_modified(self) -> None:
        repo = self.root / "unstaged"
        _init_repo(repo)
        key = _base_key(repo)
        (repo / "README.md").write_text("hello again\n", encoding="utf-8")

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertTrue(overlay.dirty)
        paths = {c.path: c for c in overlay.changed_files}
        self.assertEqual(paths["README.md"].change_type, "modified")
        self.assertIsNotNone(paths["README.md"].content_digest)

    def test_dirty_true_for_uncommitted_changes_on_clean_base(self) -> None:
        repo = self.root / "dirty-flag"
        _init_repo(repo)
        key = _base_key(repo)
        self.assertEqual(key.commit_sha, _current_commit_sha(repo))

        (repo / "README.md").write_text("dirty change\n", encoding="utf-8")
        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertEqual(overlay.worktree_commit_sha, key.commit_sha)
        self.assertTrue(overlay.dirty)
        self.assertEqual(len(overlay.changed_files), 1)

    def test_ignored_file_is_excluded_from_overlay(self) -> None:
        repo = self.root / "ignored"
        _init_repo(repo)
        key = _base_key(repo)
        (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
        _run(["add", ".gitignore"], repo)
        _run(["commit", "-m", "add gitignore"], repo)
        # Re-resolve the base key against the new HEAD so this scenario is
        # "worktree is exactly at the base commit, plus an ignored file" --
        # isolating the ignored-file behavior from committed drift.
        key = _base_key(repo)

        (repo / "ignored.log").write_text("noise\n", encoding="utf-8")

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        overlay_paths = {c.path for c in overlay.changed_files}
        self.assertNotIn("ignored.log", overlay_paths)
        # An ignored file alone must not flip dirty either -- git status
        # (without --ignored) never reports it.
        self.assertFalse(overlay.dirty)

    def test_removed_file_is_tombstoned_without_content_digest(self) -> None:
        repo = self.root / "removed"
        _init_repo(repo)
        (repo / "to_remove.py").write_text("x = 1\n", encoding="utf-8")
        _run(["add", "to_remove.py"], repo)
        _run(["commit", "-m", "add file to remove"], repo)
        key = _base_key(repo)

        (repo / "to_remove.py").unlink()

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertIn("to_remove.py", overlay.tombstones)
        removed_entries = [c for c in overlay.changed_files if c.path == "to_remove.py"]
        self.assertEqual(len(removed_entries), 1)
        self.assertEqual(removed_entries[0].change_type, "removed")
        self.assertIsNone(removed_entries[0].content_digest)

    def test_renamed_file_preserves_previous_path(self) -> None:
        repo = self.root / "renamed"
        _init_repo(repo)
        (repo / "old_name.py").write_text("value = 42\n", encoding="utf-8")
        _run(["add", "old_name.py"], repo)
        _run(["commit", "-m", "add file to rename"], repo)
        key = _base_key(repo)

        _run(["mv", "old_name.py", "new_name.py"], repo)

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        renamed = [c for c in overlay.changed_files if c.change_type == "renamed"]
        self.assertEqual(len(renamed), 1)
        self.assertEqual(renamed[0].path, "new_name.py")
        self.assertEqual(renamed[0].previous_path, "old_name.py")
        self.assertIsNotNone(renamed[0].content_digest)
        # The old name is gone from the tree -- it must appear as a
        # tombstone even though it's reported via "renamed", not "removed".
        self.assertIn("old_name.py", overlay.tombstones)

    def test_committed_drift_ahead_of_base_is_reported(self) -> None:
        repo = self.root / "committed-drift"
        _init_repo(repo)
        key = _base_key(repo)

        (repo / "added_by_commit.py").write_text("z = 1\n", encoding="utf-8")
        _run(["add", "added_by_commit.py"], repo)
        _run(["commit", "-m", "advance past base"], repo)

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertNotEqual(overlay.worktree_commit_sha, key.commit_sha)
        # No uncommitted changes on top of the new HEAD -- committed drift
        # alone does not flip "dirty".
        self.assertFalse(overlay.dirty)
        paths = {c.path: c for c in overlay.changed_files}
        self.assertEqual(paths["added_by_commit.py"].change_type, "added")

    def test_config_fingerprint_passed_through_verbatim(self) -> None:
        repo = self.root / "fingerprint"
        _init_repo(repo)
        key = _base_key(repo, config_fingerprint="cfg-fp-specific")

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-specific")

        self._assert_valid_overlay(overlay)
        self.assertEqual(overlay.config_fingerprint, "cfg-fp-specific")
        self.assertTrue(overlay.is_compatible_with_base())

    def test_worktree_path_is_absolute(self) -> None:
        repo = self.root / "abs-path"
        _init_repo(repo)
        key = _base_key(repo)

        overlay = compute_worktree_overlay(str(repo), key, "cfg-fp-1")

        self._assert_valid_overlay(overlay)
        self.assertTrue(Path(overlay.worktree_path).is_absolute())


class ComputeWorktreeOverlayErrorPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_returns_none_for_non_git_directory(self) -> None:
        plain_dir = self.root / "plain"
        plain_dir.mkdir()
        key = CanonicalMapKey(
            repo_identity="r",
            default_branch="main",
            commit_sha="a" * 40,
            tree_sha="b" * 40,
            schema_version=1,
            mapper_version="0.0.0-test",
            config_fingerprint="cfg",
        )
        self.assertIsNone(compute_worktree_overlay(str(plain_dir), key, "cfg"))

    def test_returns_none_when_base_commit_missing(self) -> None:
        repo = self.root / "missing-base"
        _init_repo(repo)
        key = _base_key(repo, commit_sha="0" * 40, tree_sha="0" * 40)

        self.assertIsNone(compute_worktree_overlay(str(repo), key, "cfg-fp-1"))

    def test_returns_none_when_head_unresolvable(self) -> None:
        repo = self.root / "unborn-head"
        repo.mkdir()
        _run(["init", "--initial-branch", "main"], repo)
        key = CanonicalMapKey(
            repo_identity="r",
            default_branch="main",
            commit_sha="a" * 40,
            tree_sha="b" * 40,
            schema_version=1,
            mapper_version="0.0.0-test",
            config_fingerprint="cfg",
        )
        self.assertIsNone(compute_worktree_overlay(str(repo), key, "cfg"))

    def test_returns_none_on_git_status_subprocess_failure(self) -> None:
        repo = self.root / "status-fails"
        _init_repo(repo)
        key = _base_key(repo)

        real_run_git = canonical_overlay._run_git

        def _fail_on_status(args, cwd, timeout=canonical_overlay._GIT_TIMEOUT_SECONDS):
            if args[:1] == ["status"]:
                return None
            return real_run_git(args, cwd, timeout)

        with patch.object(canonical_overlay, "_run_git", side_effect=_fail_on_status):
            self.assertIsNone(compute_worktree_overlay(str(repo), key, "cfg-fp-1"))

    def test_returns_none_on_spawn_failure(self) -> None:
        repo = self.root / "spawn-fails"
        _init_repo(repo)
        key = _base_key(repo)

        with patch.object(
            canonical_overlay.subprocess,
            "run",
            side_effect=FileNotFoundError("git not on PATH"),
        ):
            self.assertIsNone(compute_worktree_overlay(str(repo), key, "cfg-fp-1"))


class ApplyHopMergeTests(unittest.TestCase):
    """Focused tests for the internal two-hop merge logic in isolation."""

    def test_rename_then_rename_chains_to_original_origin(self) -> None:
        state: dict = {}
        tombstones: set = set()
        canonical_overlay._apply_hop(state, tombstones, "renamed", "a.py", "b.py")
        canonical_overlay._apply_hop(state, tombstones, "renamed", "b.py", "c.py")
        self.assertEqual(state, {"c.py": "a.py"})
        self.assertEqual(tombstones, set())

    def test_added_then_removed_nets_to_no_change(self) -> None:
        state: dict = {}
        tombstones: set = set()
        canonical_overlay._apply_hop(state, tombstones, "added", None, "new.py")
        canonical_overlay._apply_hop(state, tombstones, "removed", None, "new.py")
        self.assertEqual(state, {})
        self.assertEqual(tombstones, set())

    def test_removed_then_recreated_nets_to_modified(self) -> None:
        state: dict = {}
        tombstones: set = set()
        canonical_overlay._apply_hop(state, tombstones, "removed", None, "f.py")
        canonical_overlay._apply_hop(state, tombstones, "added", None, "f.py")
        self.assertEqual(state, {"f.py": "f.py"})
        self.assertEqual(tombstones, set())

    def test_rename_back_to_original_name_nets_to_no_change(self) -> None:
        state: dict = {}
        tombstones: set = set()
        canonical_overlay._apply_hop(state, tombstones, "renamed", "a.py", "b.py")
        canonical_overlay._apply_hop(state, tombstones, "renamed", "b.py", "a.py")
        self.assertEqual(state, {})
        self.assertEqual(tombstones, set())


if __name__ == "__main__":
    unittest.main()
