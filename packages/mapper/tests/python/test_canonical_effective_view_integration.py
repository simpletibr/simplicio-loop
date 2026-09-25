"""Integration/system tests reconciling canonical_builder <-> effective_view (issue #236).

``canonical_builder.build_canonical_manifest`` and ``effective_view.py``
(``compose_effective_view`` / ``LazyFileResolver``) were each merged with
their own isolated unit tests, but never exercised together against a real
builder-produced manifest. ``effective_view.py`` assumed a
``artifact_paths["file_manifest"]`` JSON Lines side-artifact that
``canonical_builder.py`` did not write -- meaning the whole
``EffectiveMapView`` composition was non-functional against any real
manifest the builder actually produces, only against hand-constructed
fixtures (see ``test_effective_view.py``).

This module is the missing system-level proof: it calls the *real* builder
against a *real* temporary git repository, then calls the *real* composition
+ overlay-computation functions against that real manifest, and asserts
``LazyFileResolver.resolve()`` correctly finds real per-file entries -- not
mocks, not hand-built fixtures.

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

from simplicio_mapper.mapper.canonical import OverlayFileChange  # noqa: E402
from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_overlay import compute_worktree_overlay  # noqa: E402
from simplicio_mapper.mapper.effective_view import (  # noqa: E402
    REMOVED,
    LazyFileResolver,
    compose_effective_view,
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
    src = path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (src / "keep.py").write_text("KEEP = True\n", encoding="utf-8")
    (src / "doomed.py").write_text("DOOMED = True\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


class BuilderEffectiveViewIntegrationTests(unittest.TestCase):
    """Builder -> composition, against a real manifest, worktree clean (no overlay)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")

    def test_resolver_finds_real_files_from_real_builder_manifest(self) -> None:
        repo = self.base / "repo"
        _init_repo(repo)

        manifest = build_canonical_manifest(str(repo), self.storage_root, "cfg-integration")
        self.assertIsNotNone(manifest)
        self.assertIn("file_manifest", manifest.artifact_paths)

        # No overlay: this worktree IS the canonical commit.
        view = compose_effective_view(manifest, None)
        resolver = LazyFileResolver(view)

        for path in ("README.md", "src/mod.py", "src/keep.py", "src/doomed.py"):
            entry = resolver.resolve(path)
            self.assertIsInstance(entry, dict, f"expected a canonical dict entry for {path}")
            self.assertEqual(entry["path"], path)

        self.assertIsNone(resolver.resolve("does/not/exist.py"))

    def test_resolver_entry_matches_project_map_entry_field_for_field(self) -> None:
        repo = self.base / "repo-fields"
        _init_repo(repo)
        manifest = build_canonical_manifest(str(repo), self.storage_root, "cfg-fields")
        self.assertIsNotNone(manifest)

        import orjson

        from simplicio_mapper.mapper.canonical_storage import canonical_manifest_dir

        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        project_map = orjson.loads(
            (digest_dir / manifest.artifact_paths["project_map"]).read_bytes()
        )
        project_map_entry = next(f for f in project_map["files"] if f["path"] == "src/mod.py")

        view = compose_effective_view(manifest, None)
        resolver = LazyFileResolver(view)
        resolved_entry = resolver.resolve("src/mod.py")
        self.assertEqual(resolved_entry, project_map_entry)


class BuilderOverlayEffectiveViewSystemTests(unittest.TestCase):
    """Full chain: build -> compute overlay against a dirty worktree -> compose -> resolve.

    Covers the three resolution outcomes the ADR requires: canonical-only
    (untouched by the overlay), overlay-shadowed (added/modified by the dirty
    worktree), and tombstoned (removed by the dirty worktree) -- all against
    real git state, not hand-built ``OverlayFileChange``/``WorktreeOverlay``
    fixtures.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.storage_root = str(self.base / "storage")

    def test_mixed_resolution_against_real_dirty_worktree(self) -> None:
        repo = self.base / "repo-system"
        _init_repo(repo)

        config_fingerprint = "cfg-system"
        manifest = build_canonical_manifest(str(repo), self.storage_root, config_fingerprint)
        self.assertIsNotNone(manifest)

        # Dirty the *real* worktree on top of the canonical commit:
        # - modify a tracked file (src/keep.py stays, but shadowed)
        # - remove a tracked file (src/doomed.py -> tombstoned)
        # - add a brand-new untracked file (src/new_thing.py -> shadowed)
        # - README.md is left untouched -> must resolve to the canonical entry.
        (repo / "src" / "keep.py").write_text("KEEP = 'modified'\n", encoding="utf-8")
        (repo / "src" / "doomed.py").unlink()
        (repo / "src" / "new_thing.py").write_text("NEW = True\n", encoding="utf-8")

        overlay = compute_worktree_overlay(str(repo), manifest.key, config_fingerprint)
        self.assertIsNotNone(overlay)
        self.assertTrue(overlay.dirty)

        view = compose_effective_view(manifest, overlay)
        resolver = LazyFileResolver(view)

        # Canonical-only: untouched by the overlay, resolves through to the
        # real file-manifest artifact the builder wrote.
        readme_entry = resolver.resolve("README.md")
        self.assertIsInstance(readme_entry, dict)
        self.assertEqual(readme_entry["path"], "README.md")

        # Overlay-shadowed (modified): must NOT be the stale canonical entry.
        keep_entry = resolver.resolve("src/keep.py")
        self.assertIsInstance(keep_entry, OverlayFileChange)
        self.assertEqual(keep_entry.change_type, "modified")

        # Overlay-shadowed (added, untracked): only exists via the overlay.
        new_entry = resolver.resolve("src/new_thing.py")
        self.assertIsInstance(new_entry, OverlayFileChange)
        self.assertEqual(new_entry.change_type, "added")

        # Tombstoned: removed by the dirty worktree, must never fall through
        # to the (still-present) canonical entry.
        self.assertIs(resolver.resolve("src/doomed.py"), REMOVED)

        # Diagnostics are consistent with the real delta computed above.
        self.assertGreaterEqual(view.diagnostics.files_remapped, 2)
        self.assertIsNone(view.diagnostics.invalidation_reason)

    def test_clean_worktree_overlay_has_no_delta_and_all_paths_resolve_canonical(self) -> None:
        repo = self.base / "repo-clean"
        _init_repo(repo)
        config_fingerprint = "cfg-clean-system"
        manifest = build_canonical_manifest(str(repo), self.storage_root, config_fingerprint)
        self.assertIsNotNone(manifest)

        overlay = compute_worktree_overlay(str(repo), manifest.key, config_fingerprint)
        self.assertIsNotNone(overlay)
        self.assertFalse(overlay.dirty)
        self.assertEqual(overlay.changed_files, ())
        self.assertEqual(overlay.tombstones, ())

        view = compose_effective_view(manifest, overlay)
        resolver = LazyFileResolver(view)
        for path in ("README.md", "src/mod.py", "src/keep.py", "src/doomed.py"):
            entry = resolver.resolve(path)
            self.assertIsInstance(entry, dict)
            self.assertEqual(entry["path"], path)


if __name__ == "__main__":
    unittest.main()
