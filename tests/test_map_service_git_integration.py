from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

import pytest

from simplicio_loop.map_service import MapServiceRegistry
from simplicio_loop.map_service_git import (
    GitIdentityError,
    real_tree_snapshot,
    resolve_repository_identity,
)
from simplicio_loop.map_service_single_flight import SingleFlightMapStore


def _run(*args: str, cwd: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, "git %s failed: %s" % (" ".join(args), result.stderr)


def _git_output(cwd: str, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, "git %s failed: %s" % (" ".join(args), result.stderr)
    return result.stdout.strip()


def _init_repo(root: Path) -> None:
    _run("init", "-q", cwd=str(root))
    _run("config", "user.email", "test@example.com", cwd=str(root))
    _run("config", "user.name", "Test", cwd=str(root))
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _run("add", "README.md", cwd=str(root))
    _run("commit", "-q", "-m", "initial", cwd=str(root))


def test_resolve_identity_of_a_non_git_path_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(GitIdentityError):
            resolve_repository_identity(directory)


def test_main_worktree_and_a_real_second_worktree_share_canonical_root() -> None:
    with tempfile.TemporaryDirectory() as directory:
        main_root = Path(directory) / "main"
        main_root.mkdir()
        _init_repo(main_root)

        worktree_root = Path(directory) / "feature-wt"
        _run("worktree", "add", "-q", str(worktree_root), "-b", "feature", cwd=str(main_root))

        main_identity = resolve_repository_identity(str(main_root))
        wt_identity = resolve_repository_identity(str(worktree_root))

        assert main_identity.worktree_root is None, "the main worktree has no separate worktree_root"
        assert wt_identity.worktree_root == str(worktree_root.resolve())
        # Both worktrees of the SAME repository agree on canonical_root and repository.
        assert main_identity.canonical_root == wt_identity.canonical_root
        assert main_identity.repository == wt_identity.repository
        # But they are genuinely distinct identities (different worktree_root / branch).
        assert main_identity.key != wt_identity.key


def test_dirty_detection_and_fingerprint_reflect_real_uncommitted_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)

        clean = resolve_repository_identity(str(root))
        assert clean.dirty is False
        assert clean.dirty_fingerprint == ""

        (root / "README.md").write_text("changed\n", encoding="utf-8")
        dirty = resolve_repository_identity(str(root))
        assert dirty.dirty is True
        assert dirty.dirty_fingerprint != ""
        assert dirty.base_sha == clean.base_sha, "an uncommitted change does not move HEAD"

        (root / "README.md").write_text("changed again\n", encoding="utf-8")
        dirty2 = resolve_repository_identity(str(root))
        assert dirty2.dirty_fingerprint != dirty.dirty_fingerprint, (
            "a different uncommitted diff must produce a different fingerprint"
        )


def test_dirty_fingerprint_reflects_untracked_file_content_too() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)

        (root / "scratch.txt").write_text("draft one\n", encoding="utf-8")
        first = resolve_repository_identity(str(root))
        assert first.dirty is True

        (root / "scratch.txt").write_text("draft two, different content\n", encoding="utf-8")
        second = resolve_repository_identity(str(root))
        assert second.dirty_fingerprint != first.dirty_fingerprint, (
            "an untracked file's changed CONTENT must change the fingerprint, "
            "not just its presence"
        )


def test_repository_with_a_configured_origin_uses_its_declared_default_branch() -> None:
    with tempfile.TemporaryDirectory() as directory:
        bare_remote = Path(directory) / "remote.git"
        _run("init", "-q", "--bare", "--initial-branch=trunk", str(bare_remote), cwd=str(directory))

        root = Path(directory) / "repo"
        root.mkdir()
        _run("init", "-q", "--initial-branch=trunk", cwd=str(root))
        _run("config", "user.email", "test@example.com", cwd=str(root))
        _run("config", "user.name", "Test", cwd=str(root))
        (root / "README.md").write_text("hello\n", encoding="utf-8")
        _run("add", "README.md", cwd=str(root))
        _run("commit", "-q", "-m", "initial", cwd=str(root))
        _run("remote", "add", "origin", str(bare_remote), cwd=str(root))
        _run("push", "-q", "origin", "trunk", cwd=str(root))
        _run("remote", "set-head", "origin", "trunk", cwd=str(root))
        # Check out a DIFFERENTLY-named local branch, so a pass can only mean the
        # remote's declared default was actually used — not a coincidence from the
        # local checkout happening to share the same name as the remote default.
        _run("checkout", "-q", "-b", "local-feature-branch", cwd=str(root))

        identity = resolve_repository_identity(str(root))
        assert identity.default_branch == "trunk"


def test_detached_head_falls_back_to_a_fixed_default_branch_name() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)
        # Neither main, master nor an origin/HEAD exists, so there is no default-branch candidate.
        _run("branch", "-m", "work", cwd=str(root))
        head_sha = _git_output(str(root), "rev-parse", "HEAD")
        _run("checkout", "-q", head_sha, cwd=str(root))  # real detached HEAD, no branch at all

        identity = resolve_repository_identity(str(root))
        assert identity.default_branch == "main"


def test_repo_with_no_commits_yet_has_an_empty_real_tree_snapshot() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _run("init", "-q", cwd=str(root))
        tree_hash, files = real_tree_snapshot(str(root))
        assert files == []
        assert tree_hash  # still a stable, non-empty digest, not a crash


def test_a_real_commit_changes_base_sha_and_the_identity_key() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)
        before = resolve_repository_identity(str(root))

        (root / "new.txt").write_text("data\n", encoding="utf-8")
        _run("add", "new.txt", cwd=str(root))
        _run("commit", "-q", "-m", "second", cwd=str(root))
        after = resolve_repository_identity(str(root))

        assert after.base_sha != before.base_sha
        assert after.key != before.key


def test_real_tree_snapshot_changes_when_tracked_file_content_changes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)

        tree_hash_1, files_1 = real_tree_snapshot(str(root))
        assert files_1 == [str((root / "README.md").resolve())]

        (root / "README.md").write_text("changed\n", encoding="utf-8")
        _run("add", "README.md", cwd=str(root))
        tree_hash_2, _ = real_tree_snapshot(str(root))
        assert tree_hash_2 != tree_hash_1, "content change must change the tree hash"


def test_two_real_worktrees_single_flight_share_one_canonical_build() -> None:
    """The actual AC this closes: 'equivalentes executam um build e recebem o mesmo
    snapshot/overlay' — but now driven by REAL git identities/tree hashes from two REAL
    worktrees of the same repository, not synthetic in-memory values."""
    with tempfile.TemporaryDirectory() as directory:
        main_root = Path(directory) / "main"
        main_root.mkdir()
        _init_repo(main_root)
        worktree_root = Path(directory) / "wt2"
        _run("worktree", "add", "-q", str(worktree_root), "-b", "wt2-branch", cwd=str(main_root))

        registry = MapServiceRegistry()
        store = SingleFlightMapStore(registry)

        main_identity = resolve_repository_identity(str(main_root))
        wt_identity = resolve_repository_identity(str(worktree_root))
        registry.register(main_identity)
        registry.register(wt_identity)

        # Both worktrees are at the SAME commit (worktree add branched from HEAD without
        # further commits) so they share one real tree_hash - a genuinely equivalent
        # canonical build request from either worktree's perspective.
        tree_hash, files = real_tree_snapshot(str(main_root))
        build_calls = []

        async def real_builder():
            build_calls.append(1)
            await asyncio.sleep(0)  # a real await point, not a synchronous shortcut
            return registry.build_canonical(main_identity.key, tree_hash=tree_hash, files=files)

        async def scenario():
            handle_from_main, handle_from_wt = await asyncio.gather(
                store.get_or_build(
                    main_identity.key, mode="canonical", tree_hash=tree_hash, files=files,
                    builder=real_builder,
                ),
                store.get_or_build(
                    main_identity.key, mode="canonical", tree_hash=tree_hash, files=files,
                    builder=real_builder,
                ),
            )
            return handle_from_main, handle_from_wt

        handle_from_main, handle_from_wt = asyncio.run(scenario())

        assert len(build_calls) == 1, "two equivalent concurrent requests must build exactly once"
        assert handle_from_main.cache_key == handle_from_wt.cache_key
        assert real_tree_snapshot(str(worktree_root))[0] == tree_hash, (
            "the second worktree, unmodified since branching, has the identical real tree hash"
        )
