"""Tests for simplicio.map_view (issue #213).

Uses real, throwaway git repositories under `tmp_path` — the identity
resolution (`resolve_git_identity`) shells out to the real `git` binary, so
faking it would just re-describe the implementation instead of verifying it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from simplicio import map_view


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-q", "-m", "initial")
    # Never let a missing `simplicio-mapper` binary or a real one on the
    # test machine's PATH make the config fingerprint non-deterministic.
    monkeypatch.setattr(map_view, "_mapper_config_fingerprint", lambda: "test-fingerprint")
    map_view.clear_view_cache()
    yield repo
    map_view.clear_view_cache()


# ---------------------------------------------------------------------------
# resolve_git_identity
# ---------------------------------------------------------------------------


def test_resolve_git_identity_on_clean_repo(git_repo):
    identity = map_view.resolve_git_identity(git_repo)
    assert identity.is_git_repo
    assert identity.head_sha is not None and len(identity.head_sha) == 40
    assert identity.common_dir is not None
    assert identity.common_dir.exists()
    # Single-branch repo: HEAD is its own baseline.
    assert identity.merge_base_sha == identity.head_sha
    # A clean tree still fingerprints (hash of an empty `git status`
    # output) — the empty STRING means "no output", not "no fingerprint".
    assert identity.dirty_fingerprint != ""


def test_resolve_git_identity_dirty_fingerprint_changes_with_dirty_state(git_repo):
    clean = map_view.resolve_git_identity(git_repo)
    (git_repo / "file.txt").write_text("changed\n", encoding="utf-8")
    dirty = map_view.resolve_git_identity(git_repo)
    assert dirty.dirty_fingerprint != clean.dirty_fingerprint
    assert dirty.dirty_fingerprint != ""


def test_resolve_git_identity_on_non_git_directory(tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    identity = map_view.resolve_git_identity(plain)
    assert identity.is_git_repo is False
    assert identity.head_sha is None
    assert identity.dirty_fingerprint == ""
    assert identity.merge_base_sha is None


def test_mapper_config_fingerprint_empty_when_binary_missing(monkeypatch):
    monkeypatch.setattr(map_view.shutil, "which", lambda _name: None)
    assert map_view._mapper_config_fingerprint() == ""


# ---------------------------------------------------------------------------
# CanonicalMapManifest / WorktreeOverlay — round trip + matches()
# ---------------------------------------------------------------------------


def test_canonical_manifest_round_trips_through_dict():
    manifest = map_view.CanonicalMapManifest(
        schema=map_view.SCHEMA_CANONICAL,
        common_dir="/repo/.git",
        head_sha="a" * 40,
        mapper_config_fingerprint="v1.0.0",
        artifacts={"k": "v"},
        built_at=123.0,
    )
    restored = map_view.CanonicalMapManifest.from_dict(manifest.to_dict())
    assert restored == manifest


def test_canonical_manifest_matches_requires_all_fields(git_repo):
    identity = map_view.resolve_git_identity(git_repo)
    manifest = map_view.CanonicalMapManifest(
        schema=map_view.SCHEMA_CANONICAL,
        common_dir=str(identity.common_dir),
        head_sha=identity.head_sha,
        mapper_config_fingerprint=identity.mapper_config_fingerprint,
    )
    assert manifest.matches(identity)

    stale = map_view.CanonicalMapManifest(
        schema=map_view.SCHEMA_CANONICAL,
        common_dir=str(identity.common_dir),
        head_sha="0" * 40,  # wrong HEAD
        mapper_config_fingerprint=identity.mapper_config_fingerprint,
    )
    assert not stale.matches(identity)


def test_worktree_overlay_round_trips_and_matches(git_repo):
    identity = map_view.resolve_git_identity(git_repo)
    overlay = map_view.WorktreeOverlay(
        schema=map_view.SCHEMA_OVERLAY,
        worktree_root=str(identity.root),
        merge_base_sha=identity.merge_base_sha,
        dirty_fingerprint=identity.dirty_fingerprint,
        changed_files=["a.py", "b.py"],
    )
    restored = map_view.WorktreeOverlay.from_dict(overlay.to_dict())
    assert restored == overlay
    assert overlay.matches(identity)

    (git_repo / "file.txt").write_text("dirty now\n", encoding="utf-8")
    dirtied_identity = map_view.resolve_git_identity(git_repo)
    assert not overlay.matches(dirtied_identity)


# ---------------------------------------------------------------------------
# get_effective_map_view — the core "no redundant full remap" behavior
# ---------------------------------------------------------------------------


def test_first_call_builds_canonical_and_overlay(git_repo):
    view = map_view.get_effective_map_view(git_repo)
    assert view.source in (map_view.SOURCE_FULL_REMAP, map_view.SOURCE_FALLBACK_STANDALONE)
    assert view.canonical is not None
    assert view.overlay is not None
    assert view.snapshot_id

    identity = map_view.resolve_git_identity(git_repo)
    canonical_path = map_view._canonical_path(identity)
    overlay_path = map_view._overlay_path(identity)
    assert canonical_path is not None and canonical_path.exists()
    assert overlay_path.exists()


def test_second_call_reuses_process_cached_view_without_rebuild(git_repo):
    first = map_view.get_effective_map_view(git_repo)
    second = map_view.get_effective_map_view(git_repo)
    assert first is second  # issue #213: same view handle reused across a run/retry


def test_fresh_process_state_hits_canonical_and_overlay_from_disk(git_repo):
    map_view.get_effective_map_view(git_repo)  # builds + writes manifests
    map_view.clear_view_cache()  # simulate a new process / new retry attempt
    view = map_view.get_effective_map_view(git_repo)
    assert view.source == map_view.SOURCE_CANONICAL_OVERLAY_HIT
    assert view.canonical is not None
    assert view.overlay is not None


def test_dirtying_the_tree_invalidates_only_the_overlay_not_canonical(git_repo):
    first = map_view.get_effective_map_view(git_repo)
    canonical_before = first.canonical
    map_view.clear_view_cache()

    (git_repo / "file.txt").write_text("dirty\n", encoding="utf-8")
    second = map_view.get_effective_map_view(git_repo)

    assert second.source == map_view.SOURCE_FULL_REMAP
    # Canonical manifest is unaffected by a dirty working tree — same HEAD.
    assert second.canonical is not None
    assert second.canonical.head_sha == canonical_before.head_sha
    assert second.overlay is not None
    assert second.overlay.dirty_fingerprint != ""


def test_force_remap_ignores_disk_cache(git_repo):
    map_view.get_effective_map_view(git_repo)
    map_view.clear_view_cache()
    forced = map_view.get_effective_map_view(git_repo, force_remap=True)
    assert forced.source != map_view.SOURCE_CANONICAL_OVERLAY_HIT


def test_stale_canonical_manifest_is_rejected_and_rebuilt(git_repo):
    identity = map_view.resolve_git_identity(git_repo)
    canonical_path = map_view._canonical_path(identity)
    assert canonical_path is not None
    canonical_path.parent.mkdir(parents=True, exist_ok=True)
    stale = map_view.CanonicalMapManifest(
        schema=map_view.SCHEMA_CANONICAL,
        common_dir=str(identity.common_dir),
        head_sha="0" * 40,  # deliberately wrong
        mapper_config_fingerprint=identity.mapper_config_fingerprint,
    )
    from simplicio.utils.serialization import dumps

    canonical_path.write_bytes(dumps(stale.to_dict(), indent=True))

    view = map_view.get_effective_map_view(git_repo)
    assert view.canonical is not None
    assert view.canonical.head_sha == identity.head_sha  # rebuilt, not the stale one


def test_clear_view_cache_empties_cache(git_repo):
    map_view.get_effective_map_view(git_repo)
    assert map_view._VIEW_CACHE
    map_view.clear_view_cache()
    assert not map_view._VIEW_CACHE


# ---------------------------------------------------------------------------
# doctor_map_view_status
# ---------------------------------------------------------------------------


def test_doctor_map_view_status_shape(git_repo):
    status = map_view.doctor_map_view_status(git_repo)
    assert status["schema"] == "simplicio.map-view-status/v1"
    assert "snapshot_id" in status
    assert "source" in status
    assert "canonical_hit" in status
    assert "overlay_hit" in status
    assert isinstance(status["changed_files"], list)


def test_snapshot_id_is_stable_for_same_identity(git_repo):
    first = map_view.get_effective_map_view(git_repo)
    map_view.clear_view_cache()
    second = map_view.get_effective_map_view(git_repo)
    assert first.snapshot_id == second.snapshot_id


def test_snapshot_id_changes_when_tree_becomes_dirty(git_repo):
    first = map_view.get_effective_map_view(git_repo)
    map_view.clear_view_cache()
    (git_repo / "file.txt").write_text("dirty\n", encoding="utf-8")
    second = map_view.get_effective_map_view(git_repo)
    assert first.snapshot_id != second.snapshot_id
