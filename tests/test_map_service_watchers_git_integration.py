from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from simplicio_loop.map_service import MapServiceRegistry, UnknownRepositoryError
from simplicio_loop.map_service_git import real_tree_snapshot, resolve_repository_identity
from simplicio_loop.map_service_single_flight import SingleFlightMapStore
from simplicio_loop.map_service_watchers import MapWatcherManager


def _run(*args: str, cwd: str) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, "git %s failed: %s" % (" ".join(args), result.stderr)


def _init_repo(root: Path) -> None:
    _run("init", "-q", "-b", "master", cwd=str(root))  # the test names its base branch; never the host default
    _run("config", "user.email", "test@example.com", cwd=str(root))
    _run("config", "user.name", "Test", cwd=str(root))
    (root / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
    _run("add", "app.py", cwd=str(root))
    _run("commit", "-q", "-m", "initial", cwd=str(root))


def test_real_branch_switch_invalidates_and_rebuild_reflects_new_commit() -> None:
    """The AC gap this closes: 'transicoes de branch/rebase/dirty' against
    MapWatcherManager itself, with real git operations - not a fresh in-process object
    standing in for a restart, and not a synthetic tree_hash standing in for a real
    commit change."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)

        registry = MapServiceRegistry()
        store = SingleFlightMapStore(registry)
        manager = MapWatcherManager(registry, store)

        identity_v1 = resolve_repository_identity(str(root))
        registry.register(identity_v1)
        tree_hash_v1, files_v1 = real_tree_snapshot(str(root))
        view_v1 = registry.build_canonical(identity_v1.key, tree_hash=tree_hash_v1, files=files_v1)

        events = []
        manager.watch(identity_v1.key, lambda event: events.append(event), debounce_seconds=0.0)

        # Real branch switch + real commit - not a simulated event.
        _run("checkout", "-q", "-b", "feature", cwd=str(root))
        (root / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        _run("add", "app.py", cwd=str(root))
        _run("commit", "-q", "-m", "bump version on feature branch", cwd=str(root))

        identity_v2 = resolve_repository_identity(str(root))
        assert identity_v2.key != identity_v1.key, "a real branch switch + commit must change the identity"
        assert identity_v2.base_sha != identity_v1.base_sha

        # A real filesystem watcher would report exactly this changed path; feed it
        # through emit()/flush() rather than inventing a synthetic path.
        manager.emit(identity_v1.key, [str(root / "app.py")])
        fired = manager.flush(force=True)
        assert len(fired) == 1
        assert fired[0]["identity_key"] == identity_v1.key
        assert events and events[0]["identity_key"] == identity_v1.key

        # The old view is invalidated (get_view raises rather than returning an
        # invalid view - that's the registry's actual contract); a rebuild against the
        # NEW real commit produces a genuinely different cache_key (real content
        # changed, not a synthetic bump).
        with pytest.raises(UnknownRepositoryError):
            registry.get_view(view_v1.cache_key, acquire=False)
        registry.register(identity_v2)
        tree_hash_v2, files_v2 = real_tree_snapshot(str(root))
        assert tree_hash_v2 != tree_hash_v1
        view_v2 = registry.build_canonical(identity_v2.key, tree_hash=tree_hash_v2, files=files_v2)
        assert view_v2.cache_key != view_v1.cache_key


def test_real_rebase_changes_base_sha_and_triggers_a_correct_rebuild() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)
        _run("checkout", "-q", "-b", "feature", cwd=str(root))
        (root / "feature.py").write_text("FEATURE = True\n", encoding="utf-8")
        _run("add", "feature.py", cwd=str(root))
        _run("commit", "-q", "-m", "add feature", cwd=str(root))

        # Advance the base branch independently, so the feature branch's rebase is a
        # REAL rebase (replaying a commit onto a moved base), not a no-op fast-forward.
        _run("checkout", "-q", "master", cwd=str(root))
        (root / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        _run("add", "app.py", cwd=str(root))
        _run("commit", "-q", "-m", "advance master independently", cwd=str(root))
        _run("checkout", "-q", "feature", cwd=str(root))

        registry = MapServiceRegistry()
        store = SingleFlightMapStore(registry)
        manager = MapWatcherManager(registry, store)
        identity_before = resolve_repository_identity(str(root))
        registry.register(identity_before)
        events = []
        manager.watch(identity_before.key, lambda event: events.append(event), debounce_seconds=0.0)

        _run("rebase", "-q", "master", cwd=str(root))  # real rebase, real new commit sha

        identity_after = resolve_repository_identity(str(root))
        assert identity_after.base_sha != identity_before.base_sha, (
            "a real rebase must produce a real new commit sha, not the pre-rebase one"
        )

        manager.emit(identity_before.key, [str(root / "feature.py"), str(root / "app.py")])
        fired = manager.flush(force=True)
        assert len(fired) == 1
        assert events[0]["identity_key"] == identity_before.key

        registry.register(identity_after)
        tree_hash_after, files_after = real_tree_snapshot(str(root))
        rebuilt = registry.build_canonical(identity_after.key, tree_hash=tree_hash_after, files=files_after)
        assert rebuilt.identity_key == identity_after.key


def test_real_dirty_uncommitted_change_triggers_a_correct_overlay_transition() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"
        root.mkdir()
        _init_repo(root)

        registry = MapServiceRegistry()
        store = SingleFlightMapStore(registry)
        manager = MapWatcherManager(registry, store)

        clean_identity = resolve_repository_identity(str(root))
        assert clean_identity.dirty is False
        registry.register(clean_identity)
        manager.watch(clean_identity.key, lambda event: None, debounce_seconds=0.0)

        # A real uncommitted edit - not a synthetic dirty flag.
        (root / "app.py").write_text("VERSION = 999  # uncommitted\n", encoding="utf-8")
        dirty_identity = resolve_repository_identity(str(root))
        assert dirty_identity.dirty is True
        assert dirty_identity.base_sha == clean_identity.base_sha, "uncommitted edit must not move HEAD"
        assert dirty_identity.key != clean_identity.key

        manager.emit(clean_identity.key, [str(root / "app.py")])
        fired = manager.flush(force=True)
        assert len(fired) == 1
        assert not registry.identity(clean_identity.key).dirty  # the ORIGINAL identity's own flag is unaffected

        # The dirty state needs its OWN identity registered (worktree_root required for
        # an overlay build, matching MapServiceRegistry's existing contract).
        registry.register(dirty_identity)
