"""Unit tests for simplicio_mapper.mapper.effective_view (issue #236, ADR-008 step 5).

Covers lazy composition of ``EffectiveMapView`` and the ``LazyFileResolver``
read-only accessor: overlay-``None`` passthrough, additions, modifications,
removals (tombstones), renames, incompatible-overlay rejection (delegated to
``EffectiveMapView.__post_init__``), diagnostics counts, and -- the ADR's
explicit "no full-copy" requirement -- proof that composing a view and doing
a single lookup never reads/parses the entire canonical file inventory.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical import (  # noqa: E402
    CANONICAL_MAP_SCHEMA,
    CANONICAL_MAP_SCHEMA_VERSION,
    WORKTREE_OVERLAY_SCHEMA,
    WORKTREE_OVERLAY_SCHEMA_VERSION,
    CanonicalMapKey,
    CanonicalMapManifest,
    OverlayFileChange,
    WorktreeOverlay,
)
from simplicio_mapper.mapper.effective_view import (  # noqa: E402
    REMOVED,
    LazyFileResolver,
    compose_effective_view,
)


def _key(**overrides) -> CanonicalMapKey:
    base = {
        "repo_identity": "repo-abc123",
        "default_branch": "main",
        "commit_sha": "a" * 40,
        "tree_sha": "b" * 40,
        "schema_version": CANONICAL_MAP_SCHEMA_VERSION,
        "mapper_version": "0.30.0",
        "config_fingerprint": "cfg-fp-1",
    }
    base.update(overrides)
    return CanonicalMapKey(**base)


def _manifest(storage_root: str = "", file_manifest_name: str = "files.jsonl", **overrides) -> CanonicalMapManifest:
    base = {
        "schema": CANONICAL_MAP_SCHEMA,
        "schema_version": CANONICAL_MAP_SCHEMA_VERSION,
        "key": _key(),
        "storage_root": storage_root,
        "artifact_paths": {"file_manifest": file_manifest_name},
        "file_manifest_digest": "digest-xyz",
        "counts": {"files": 3},
        "created_at": "2026-07-17T00:00:00Z",
        "builder": {"pid": "123", "host": "runner-1"},
        "generation": 0,
    }
    base.update(overrides)
    return CanonicalMapManifest(**base)


def _overlay(**overrides) -> WorktreeOverlay:
    base = {
        "schema": WORKTREE_OVERLAY_SCHEMA,
        "schema_version": WORKTREE_OVERLAY_SCHEMA_VERSION,
        "base_key": _key(),
        "worktree_path": "/repo/worktree-a",
        "worktree_commit_sha": "a" * 40,
        "config_fingerprint": "cfg-fp-1",
    }
    base.update(overrides)
    return WorktreeOverlay(**base)


def _write_jsonl(tmp_dir: str, name: str, entries: list[dict]) -> str:
    path = Path(tmp_dir) / name
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return str(path)


class ComposeNoOverlayTests(unittest.TestCase):
    """Overlay is None -- worktree IS the canonical commit, no delta."""

    def test_overlay_none_passes_through(self) -> None:
        canonical = _manifest(counts={"files": 5})
        view = compose_effective_view(canonical, None)
        self.assertIsNone(view.overlay)
        self.assertIs(view.canonical, canonical)

    def test_diagnostics_for_no_overlay(self) -> None:
        canonical = _manifest(counts={"files": 5})
        view = compose_effective_view(canonical, None)
        self.assertEqual(view.diagnostics.files_reused, 5)
        self.assertEqual(view.diagnostics.files_remapped, 0)
        self.assertTrue(view.diagnostics.cache_hit)
        self.assertFalse(view.diagnostics.single_flight_waited)
        self.assertIsNone(view.diagnostics.invalidation_reason)

    def test_resolver_falls_through_to_canonical_with_no_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_jsonl(
                tmp,
                "files.jsonl",
                [{"path": "src/app.py", "content_digest": "aaa"}],
            )
            canonical = _manifest(storage_root=tmp, counts={"files": 1})
            view = compose_effective_view(canonical, None)
            resolver = LazyFileResolver(view)
            entry = resolver.resolve("src/app.py")
            self.assertEqual(entry["content_digest"], "aaa")
            self.assertIsNone(resolver.resolve("missing.py"))


class ComposeAdditionsTests(unittest.TestCase):
    def test_added_file_resolves_to_overlay_version(self) -> None:
        canonical = _manifest(counts={"files": 2})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(path="src/new.py", change_type="added", content_digest="new-digest"),
            )
        )
        view = compose_effective_view(canonical, overlay)
        resolver = LazyFileResolver(view)
        result = resolver.resolve("src/new.py")
        self.assertIsInstance(result, OverlayFileChange)
        self.assertEqual(result.content_digest, "new-digest")

    def test_diagnostics_count_addition_as_remapped_not_reused(self) -> None:
        canonical = _manifest(counts={"files": 2})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(path="src/new.py", change_type="added", content_digest="new-digest"),
            )
        )
        view = compose_effective_view(canonical, overlay)
        self.assertEqual(view.diagnostics.files_remapped, 1)
        self.assertEqual(view.diagnostics.files_reused, 1)


class ComposeModificationsTests(unittest.TestCase):
    def test_modified_file_resolves_to_overlay_version_not_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_jsonl(
                tmp,
                "files.jsonl",
                [{"path": "src/app.py", "content_digest": "old-digest"}],
            )
            canonical = _manifest(storage_root=tmp, counts={"files": 1})
            overlay = _overlay(
                changed_files=(
                    OverlayFileChange(
                        path="src/app.py", change_type="modified", content_digest="modified-digest"
                    ),
                )
            )
            view = compose_effective_view(canonical, overlay)
            resolver = LazyFileResolver(view)
            result = resolver.resolve("src/app.py")
            self.assertIsInstance(result, OverlayFileChange)
            self.assertEqual(result.content_digest, "modified-digest")

    def test_diagnostics_for_modification(self) -> None:
        canonical = _manifest(counts={"files": 4})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(path="src/app.py", change_type="modified", content_digest="d1"),
            )
        )
        view = compose_effective_view(canonical, overlay)
        self.assertEqual(view.diagnostics.files_remapped, 1)
        self.assertEqual(view.diagnostics.files_reused, 3)


class ComposeRemovalsTests(unittest.TestCase):
    """Tombstoned paths must never fall through to canonical."""

    def test_tombstoned_path_resolves_to_removed_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_jsonl(
                tmp,
                "files.jsonl",
                [{"path": "src/gone.py", "content_digest": "still-here-in-canonical"}],
            )
            canonical = _manifest(storage_root=tmp, counts={"files": 1})
            overlay = _overlay(tombstones=("src/gone.py",))
            view = compose_effective_view(canonical, overlay)
            resolver = LazyFileResolver(view)
            result = resolver.resolve("src/gone.py")
            self.assertIs(result, REMOVED)

    def test_removed_change_type_also_shadows_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_jsonl(tmp, "files.jsonl", [{"path": "src/gone.py", "content_digest": "x"}])
            canonical = _manifest(storage_root=tmp, counts={"files": 1})
            overlay = _overlay(
                changed_files=(OverlayFileChange(path="src/gone.py", change_type="removed"),)
            )
            view = compose_effective_view(canonical, overlay)
            resolver = LazyFileResolver(view)
            self.assertIs(resolver.resolve("src/gone.py"), REMOVED)

    def test_diagnostics_for_removal(self) -> None:
        canonical = _manifest(counts={"files": 4})
        overlay = _overlay(tombstones=("src/gone.py",))
        view = compose_effective_view(canonical, overlay)
        self.assertEqual(view.diagnostics.files_remapped, 0)
        self.assertEqual(view.diagnostics.files_reused, 3)


class ComposeRenameTests(unittest.TestCase):
    def test_rename_old_path_is_tombstoned_new_path_resolves_to_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_jsonl(tmp, "files.jsonl", [{"path": "src/old_name.py", "content_digest": "orig"}])
            canonical = _manifest(storage_root=tmp, counts={"files": 1})
            overlay = _overlay(
                changed_files=(
                    OverlayFileChange(
                        path="src/new_name.py",
                        change_type="renamed",
                        previous_path="src/old_name.py",
                        content_digest="renamed-digest",
                    ),
                )
            )
            view = compose_effective_view(canonical, overlay)
            resolver = LazyFileResolver(view)
            self.assertIs(resolver.resolve("src/old_name.py"), REMOVED)
            new_entry = resolver.resolve("src/new_name.py")
            self.assertIsInstance(new_entry, OverlayFileChange)
            self.assertEqual(new_entry.content_digest, "renamed-digest")

    def test_diagnostics_for_rename(self) -> None:
        canonical = _manifest(counts={"files": 5})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(
                    path="src/new_name.py",
                    change_type="renamed",
                    previous_path="src/old_name.py",
                    content_digest="d",
                ),
            )
        )
        view = compose_effective_view(canonical, overlay)
        # Shadowed set = {new_name (via changed_files), old_name (via rename source)} = 2
        self.assertEqual(view.diagnostics.files_remapped, 1)
        self.assertEqual(view.diagnostics.files_reused, 3)


class IncompatibleOverlayTests(unittest.TestCase):
    """Exercises EffectiveMapView.__post_init__'s existing validation."""

    def test_config_fingerprint_mismatch_raises(self) -> None:
        canonical = _manifest()
        overlay = _overlay(config_fingerprint="cfg-fp-DIFFERENT")
        with self.assertRaises(ValueError):
            compose_effective_view(canonical, overlay)

    def test_base_key_mismatch_raises(self) -> None:
        canonical = _manifest()
        overlay = _overlay(base_key=_key(commit_sha="c" * 40))
        with self.assertRaises(ValueError):
            compose_effective_view(canonical, overlay)


class MixedOverlayDiagnosticsTests(unittest.TestCase):
    def test_mixed_overlay_counts(self) -> None:
        canonical = _manifest(counts={"files": 10})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(path="a_added.py", change_type="added", content_digest="d1"),
                OverlayFileChange(path="b_modified.py", change_type="modified", content_digest="d2"),
                OverlayFileChange(
                    path="c_renamed_new.py",
                    change_type="renamed",
                    previous_path="c_renamed_old.py",
                    content_digest="d3",
                ),
            ),
            tombstones=("d_removed.py",),
        )
        view = compose_effective_view(canonical, overlay)
        # remapped: added + modified + renamed = 3 (removal excluded)
        self.assertEqual(view.diagnostics.files_remapped, 3)
        # shadowed = {a_added, b_modified, c_renamed_new, c_renamed_old, d_removed} = 5
        self.assertEqual(view.diagnostics.files_reused, 5)


class NoFullCopyLazinessTests(unittest.TestCase):
    """Proves the ADR's explicit "no full-copy of the base map" requirement."""

    def test_compose_never_touches_canonical_file_manifest_on_disk(self) -> None:
        # artifact_paths points at a file manifest that does not exist at all.
        # If compose_effective_view ever opened it, this would raise.
        canonical = _manifest(
            storage_root="/nonexistent/does/not/exist",
            file_manifest_name="huge-inventory.jsonl",
            counts={"files": 10_000_000},
        )
        overlay = _overlay(
            changed_files=(OverlayFileChange(path="small.py", change_type="added", content_digest="d"),)
        )
        view = compose_effective_view(canonical, overlay)
        self.assertEqual(view.diagnostics.files_reused, 10_000_000 - 1)
        self.assertEqual(view.diagnostics.files_remapped, 1)

    def test_single_lookup_stops_after_first_match_never_parses_rest(self) -> None:
        """A huge canonical manifest with garbage after the first line.

        If the resolver ever read/parsed the whole file (or loaded it as one
        JSON document) this test would raise a JSON decode error. Because the
        target path is the very first line, a truly lazy line-by-line lookup
        finds it and stops -- proving it never materializes the rest of the
        (deliberately unparseable) canonical file inventory.
        """
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "huge.jsonl"
            with open(manifest_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"path": "target.py", "content_digest": "found-me"}) + "\n")
                for _ in range(50_000):
                    handle.write("{{{ not valid json at all\n")
            canonical = _manifest(
                storage_root=tmp,
                file_manifest_name="huge.jsonl",
                counts={"files": 50_001},
            )
            view = compose_effective_view(canonical, None)
            resolver = LazyFileResolver(view)
            entry = resolver.resolve("target.py")
            self.assertEqual(entry["content_digest"], "found-me")

    def test_lookup_for_overlay_shadowed_path_never_opens_canonical_file(self) -> None:
        # storage_root points nowhere; if the resolver fell through to
        # canonical for an overlay-shadowed path, this would raise.
        canonical = _manifest(storage_root="/nonexistent/path", counts={"files": 1000})
        overlay = _overlay(
            changed_files=(
                OverlayFileChange(path="shadowed.py", change_type="added", content_digest="d"),
            )
        )
        view = compose_effective_view(canonical, overlay)
        resolver = LazyFileResolver(view)
        result = resolver.resolve("shadowed.py")
        self.assertIsInstance(result, OverlayFileChange)

    def test_lookup_for_tombstoned_path_never_opens_canonical_file(self) -> None:
        canonical = _manifest(storage_root="/nonexistent/path", counts={"files": 1000})
        overlay = _overlay(tombstones=("gone.py",))
        view = compose_effective_view(canonical, overlay)
        resolver = LazyFileResolver(view)
        self.assertIs(resolver.resolve("gone.py"), REMOVED)


if __name__ == "__main__":
    unittest.main()
