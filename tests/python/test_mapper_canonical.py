"""Unit tests for simplicio_mapper.mapper.canonical (issue #236, Phase 0).

Covers schema-version constants and dataclass field validation for the
canonical-map / worktree-overlay design proposed in
``.specs/architecture/ADR-008-canonical-map-overlays.md``. No production
pipeline wiring exists yet -- these tests only exercise the schema module in
isolation.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical import (  # noqa: E402
    CANONICAL_MAP_SCHEMA,
    CANONICAL_MAP_SCHEMA_VERSION,
    EFFECTIVE_MAP_VIEW_SCHEMA,
    EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
    OVERLAY_CHANGE_TYPES,
    WORKTREE_OVERLAY_SCHEMA,
    WORKTREE_OVERLAY_SCHEMA_VERSION,
    CanonicalMapKey,
    CanonicalMapManifest,
    EffectiveMapDiagnostics,
    EffectiveMapView,
    OverlayFileChange,
    WorktreeOverlay,
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


def _manifest(**overrides) -> CanonicalMapManifest:
    base = {
        "schema": CANONICAL_MAP_SCHEMA,
        "schema_version": CANONICAL_MAP_SCHEMA_VERSION,
        "key": _key(),
        "storage_root": "simplicio/canonical/deadbeef",
        "artifact_paths": {"project_map": "project-map.json"},
        "file_manifest_digest": "digest-xyz",
        "counts": {"files": 10},
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


class CanonicalMapKeyTests(unittest.TestCase):
    def test_digest_is_deterministic_for_equal_keys(self) -> None:
        self.assertEqual(_key().digest(), _key().digest())

    def test_digest_changes_when_any_identity_field_differs(self) -> None:
        baseline = _key().digest()
        variants = [
            _key(repo_identity="repo-other"),
            _key(default_branch="master"),
            _key(commit_sha="c" * 40),
            _key(tree_sha="d" * 40),
            _key(mapper_version="0.30.1"),
            _key(config_fingerprint="cfg-fp-2"),
            _key(platform_tag="win32"),
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(baseline, variant.digest())

    def test_platform_tag_defaults_to_none(self) -> None:
        self.assertIsNone(_key().platform_tag)

    def test_digest_is_a_hex_string(self) -> None:
        digest = _key().digest()
        self.assertEqual(len(digest), 48)
        int(digest, 16)  # raises ValueError if not hex


class CanonicalMapManifestTests(unittest.TestCase):
    def test_valid_manifest_constructs(self) -> None:
        manifest = _manifest()
        self.assertEqual(manifest.schema, CANONICAL_MAP_SCHEMA)
        self.assertEqual(manifest.schema_version, CANONICAL_MAP_SCHEMA_VERSION)
        self.assertEqual(manifest.generation, 0)

    def test_rejects_wrong_schema_string(self) -> None:
        with self.assertRaises(ValueError):
            _manifest(schema="simplicio.something-else/v1")

    def test_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            _manifest(schema_version=CANONICAL_MAP_SCHEMA_VERSION + 1)

    def test_rejects_negative_generation(self) -> None:
        with self.assertRaises(ValueError):
            _manifest(generation=-1)

    def test_manifest_is_frozen(self) -> None:
        manifest = _manifest()
        with self.assertRaises(Exception):
            manifest.generation = 5  # type: ignore[misc]


class OverlayFileChangeTests(unittest.TestCase):
    def test_all_change_types_accepted(self) -> None:
        for change_type in OVERLAY_CHANGE_TYPES:
            with self.subTest(change_type=change_type):
                kwargs = {"path": "a.py", "change_type": change_type}
                if change_type == "renamed":
                    kwargs["previous_path"] = "old_a.py"
                OverlayFileChange(**kwargs)

    def test_rejects_unknown_change_type(self) -> None:
        with self.assertRaises(ValueError):
            OverlayFileChange(path="a.py", change_type="teleported")

    def test_renamed_requires_previous_path(self) -> None:
        with self.assertRaises(ValueError):
            OverlayFileChange(path="a.py", change_type="renamed")

    def test_removed_forbids_content_digest(self) -> None:
        with self.assertRaises(ValueError):
            OverlayFileChange(path="a.py", change_type="removed", content_digest="abc")

    def test_added_allows_content_digest(self) -> None:
        change = OverlayFileChange(path="a.py", change_type="added", content_digest="abc")
        self.assertEqual(change.content_digest, "abc")


class WorktreeOverlayTests(unittest.TestCase):
    def test_valid_overlay_constructs_with_defaults(self) -> None:
        overlay = _overlay()
        self.assertEqual(overlay.changed_files, ())
        self.assertEqual(overlay.tombstones, ())
        self.assertFalse(overlay.dirty)

    def test_rejects_wrong_schema_string(self) -> None:
        with self.assertRaises(ValueError):
            _overlay(schema="simplicio.wrong/v1")

    def test_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            _overlay(schema_version=WORKTREE_OVERLAY_SCHEMA_VERSION + 1)

    def test_is_compatible_with_base_true_when_fingerprints_match(self) -> None:
        overlay = _overlay(config_fingerprint="cfg-fp-1")
        self.assertTrue(overlay.is_compatible_with_base())

    def test_is_compatible_with_base_false_when_fingerprints_differ(self) -> None:
        overlay = _overlay(config_fingerprint="cfg-fp-DIFFERENT")
        self.assertFalse(overlay.is_compatible_with_base())


class EffectiveMapViewTests(unittest.TestCase):
    def _diagnostics(self, **overrides) -> EffectiveMapDiagnostics:
        base = {
            "cache_hit": True,
            "single_flight_waited": False,
            "files_reused": 10,
            "files_remapped": 0,
        }
        base.update(overrides)
        return EffectiveMapDiagnostics(**base)

    def test_view_without_overlay_constructs(self) -> None:
        view = EffectiveMapView(
            schema=EFFECTIVE_MAP_VIEW_SCHEMA,
            schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
            canonical=_manifest(),
            overlay=None,
            diagnostics=self._diagnostics(),
        )
        self.assertIsNone(view.overlay)
        self.assertIsNone(view.diagnostics.invalidation_reason)

    def test_view_with_compatible_overlay_constructs(self) -> None:
        manifest = _manifest()
        overlay = _overlay(base_key=manifest.key, config_fingerprint="cfg-fp-1")
        view = EffectiveMapView(
            schema=EFFECTIVE_MAP_VIEW_SCHEMA,
            schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
            canonical=manifest,
            overlay=overlay,
            diagnostics=self._diagnostics(files_remapped=2, files_reused=8),
        )
        self.assertIs(view.overlay, overlay)

    def test_rejects_overlay_with_incompatible_config_fingerprint(self) -> None:
        manifest = _manifest()
        overlay = _overlay(base_key=manifest.key, config_fingerprint="cfg-fp-DIFFERENT")
        with self.assertRaises(ValueError):
            EffectiveMapView(
                schema=EFFECTIVE_MAP_VIEW_SCHEMA,
                schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
                canonical=manifest,
                overlay=overlay,
                diagnostics=self._diagnostics(),
            )

    def test_rejects_overlay_with_mismatched_base_key(self) -> None:
        manifest = _manifest()
        overlay = _overlay(base_key=_key(commit_sha="f" * 40), config_fingerprint="cfg-fp-1")
        with self.assertRaises(ValueError):
            EffectiveMapView(
                schema=EFFECTIVE_MAP_VIEW_SCHEMA,
                schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
                canonical=manifest,
                overlay=overlay,
                diagnostics=self._diagnostics(),
            )

    def test_rejects_wrong_schema_string(self) -> None:
        with self.assertRaises(ValueError):
            EffectiveMapView(
                schema="simplicio.wrong/v1",
                schema_version=EFFECTIVE_MAP_VIEW_SCHEMA_VERSION,
                canonical=_manifest(),
                overlay=None,
                diagnostics=self._diagnostics(),
            )


if __name__ == "__main__":
    unittest.main()
