from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_release_reconciliation as reconciliation


class ReleaseReconciliationTest(unittest.TestCase):
    def _root(self, version: str = "0.26.26") -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "simplicio_mapper").mkdir()
        (tmp / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
        (tmp / "pyproject.toml").write_text(f'version = "{version}"\n', encoding="utf-8")
        (tmp / "simplicio_mapper" / "__init__.py").write_text(
            f'__version__ = "{version}"\n', encoding="utf-8"
        )
        return tmp

    def test_reconciles_tag_and_all_release_identity_fields(self) -> None:
        root = self._root()
        sha = "a" * 40
        generated = {
            "schema": reconciliation.RELEASE_MANIFEST_SCHEMA,
            "version": "0.26.26",
            "commit_sha": sha,
            "artifact_digest": "sha256:" + "b" * 64,
        }
        with (
            mock.patch.object(reconciliation, "_run_git", side_effect=[sha, sha]),
            mock.patch.object(reconciliation, "build_release_manifest", return_value=generated),
            mock.patch.object(
                reconciliation,
                "build_release_artifact_digest",
                return_value=generated["artifact_digest"],
            ),
        ):
            result = reconciliation.reconcile_release(root, "v0.26.26")
        self.assertEqual(result["status"], "reconciled")
        self.assertEqual(result["commit_sha"], sha)
        self.assertEqual(result["versions"]["package.json"], "0.26.26")

    def test_version_drift_fails_before_manifest_generation(self) -> None:
        root = self._root("0.26.25")
        with self.assertRaises(reconciliation.ReleaseReconciliationError):
            reconciliation.reconcile_release(root, "v0.26.26")

    def test_captured_manifest_must_match_identity_but_may_have_old_timestamp(self) -> None:
        root = self._root()
        sha = "c" * 40
        generated = {
            "schema": reconciliation.RELEASE_MANIFEST_SCHEMA,
            "version": "0.26.26",
            "commit_sha": sha,
            "artifact_digest": "sha256:" + "d" * 64,
        }
        captured = {**generated, "generated_at": "2026-09-02T00:00:00Z"}
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(captured), encoding="utf-8")
        with (
            mock.patch.object(reconciliation, "_run_git", side_effect=[sha, sha]),
            mock.patch.object(reconciliation, "build_release_manifest", return_value=generated),
            mock.patch.object(
                reconciliation,
                "build_release_artifact_digest",
                return_value=generated["artifact_digest"],
            ),
        ):
            result = reconciliation.reconcile_release(root, "v0.26.26", manifest_path=manifest)
        self.assertEqual(result["manifest"], str(manifest))


if __name__ == "__main__":
    unittest.main()
