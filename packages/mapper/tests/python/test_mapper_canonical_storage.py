"""Unit tests for simplicio_mapper.mapper.canonical_storage (issue #236, ADR-008 step 3, partial).

Covers pure path-resolution for the content-addressed canonical-manifest /
worktree-overlay storage locations described in
``.specs/architecture/ADR-008-canonical-map-overlays.md`` section 3. No
directory creation, no file writes -- these tests only assert on the
computed strings, per the module's "pure path computation only" contract.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical import CANONICAL_MAP_SCHEMA_VERSION, CanonicalMapKey  # noqa: E402
from simplicio_mapper.mapper.canonical_storage import (  # noqa: E402
    CANONICAL_CACHE_DIR_ENV_VAR,
    canonical_manifest_dir,
    canonical_manifest_dir_for_key,
    canonical_manifest_tmp_dir,
    overlay_dir,
    resolve_canonical_cache_root,
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


class ResolveCanonicalCacheRootTests(unittest.TestCase):
    def test_falls_back_to_common_git_dir_when_env_var_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(CANONICAL_CACHE_DIR_ENV_VAR, None)
            root = resolve_canonical_cache_root("/repo/.git")
        self.assertEqual(root, os.path.join("/repo/.git", "simplicio"))

    def test_honors_env_var_override_when_set(self) -> None:
        with patch.dict(os.environ, {CANONICAL_CACHE_DIR_ENV_VAR: "/shared/cache"}):
            root = resolve_canonical_cache_root("/repo/.git")
        self.assertEqual(root, "/shared/cache")

    def test_ignores_empty_string_env_var_and_falls_back(self) -> None:
        with patch.dict(os.environ, {CANONICAL_CACHE_DIR_ENV_VAR: ""}):
            root = resolve_canonical_cache_root("/repo/.git")
        self.assertEqual(root, os.path.join("/repo/.git", "simplicio"))


class CanonicalManifestDirTests(unittest.TestCase):
    def test_shape_is_cache_root_canonical_digest(self) -> None:
        result = canonical_manifest_dir("/repo/.git/simplicio", "deadbeef")
        expected = os.path.join("/repo/.git/simplicio", "canonical", "deadbeef") + os.sep
        self.assertEqual(result, expected)

    def test_different_digests_produce_different_dirs(self) -> None:
        a = canonical_manifest_dir("/root", "digest-a")
        b = canonical_manifest_dir("/root", "digest-b")
        self.assertNotEqual(a, b)

    def test_different_cache_roots_produce_different_dirs(self) -> None:
        a = canonical_manifest_dir("/root-1", "same-digest")
        b = canonical_manifest_dir("/root-2", "same-digest")
        self.assertNotEqual(a, b)


class CanonicalManifestTmpDirTests(unittest.TestCase):
    def test_shape_is_digest_dot_tmp_dash_token(self) -> None:
        result = canonical_manifest_tmp_dir("/root", "deadbeef", "pid123")
        expected = os.path.join("/root", "canonical", "deadbeef.tmp-pid123") + os.sep
        self.assertEqual(result, expected)

    def test_is_sibling_of_final_manifest_dir(self) -> None:
        final = canonical_manifest_dir("/root", "deadbeef")
        tmp = canonical_manifest_tmp_dir("/root", "deadbeef", "pid123")
        self.assertEqual(os.path.dirname(os.path.dirname(final)), os.path.dirname(os.path.dirname(tmp)))
        self.assertNotEqual(final, tmp)

    def test_different_tokens_produce_different_dirs(self) -> None:
        a = canonical_manifest_tmp_dir("/root", "deadbeef", "token-1")
        b = canonical_manifest_tmp_dir("/root", "deadbeef", "token-2")
        self.assertNotEqual(a, b)


class OverlayDirTests(unittest.TestCase):
    def test_shape_is_cache_root_overlays_digest(self) -> None:
        result = overlay_dir("/root", "overlay-digest")
        expected = os.path.join("/root", "overlays", "overlay-digest") + os.sep
        self.assertEqual(result, expected)

    def test_overlay_dir_never_nested_under_canonical_dir(self) -> None:
        canonical = canonical_manifest_dir("/root", "same-digest")
        overlay = overlay_dir("/root", "same-digest")
        self.assertNotEqual(canonical, overlay)
        self.assertNotIn("canonical", overlay)
        self.assertNotIn("overlays", canonical)


class CanonicalManifestDirForKeyTests(unittest.TestCase):
    def test_composes_key_digest_with_canonical_manifest_dir(self) -> None:
        key = _key()
        expected = canonical_manifest_dir("/root", key.digest())
        self.assertEqual(canonical_manifest_dir_for_key("/root", key), expected)

    def test_different_keys_with_different_fields_produce_different_dirs(self) -> None:
        base = canonical_manifest_dir_for_key("/root", _key())
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
                self.assertNotEqual(base, canonical_manifest_dir_for_key("/root", variant))

    def test_equal_keys_produce_equal_dirs(self) -> None:
        self.assertEqual(
            canonical_manifest_dir_for_key("/root", _key()),
            canonical_manifest_dir_for_key("/root", _key()),
        )


if __name__ == "__main__":
    unittest.main()
