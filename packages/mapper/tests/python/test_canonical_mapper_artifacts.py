"""Regression tests for the canonical Mapper v1 artifact envelope (#614)."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.contract import validate_payload  # noqa: E402
from simplicio_mapper.mapper import build_artifacts, write_mapping_artifacts  # noqa: E402
from simplicio_mapper.mapper.canonical_artifacts import (  # noqa: E402
    ARTIFACT_SET_SCHEMA,
    build_artifact_manifest,
    canonical_digest,
    validate_artifact_manifest,
)

CONTRACT_ROOT = str(ROOT / "contracts" / "mapper-artifacts" / "v1")
FIXTURES = ROOT / "contracts" / "mapper-artifacts" / "v1" / "fixtures"
PUBLIC_ARTIFACTS = (
    "project_map",
    "precedent_index",
    "architecture_inventory",
    "symbol_index",
    "call_graph",
)
PUBLIC_SCHEMAS = {
    "project_map": "simplicio.project-map/v1",
    "precedent_index": "simplicio.precedent-index/v1",
    "architecture_inventory": "simplicio.architecture-inventory/v1",
    "symbol_index": "simplicio.symbol-index/v1",
    "call_graph": "simplicio.call-graph/v1",
}


class CanonicalMapperArtifactsTest(unittest.TestCase):
    def test_python_artifacts_have_metadata_and_repeatable_digests(self) -> None:
        source = FIXTURES / "python-minimal" / "source"
        with tempfile.TemporaryDirectory(prefix="mapper-614-output-") as output:
            first = build_artifacts(str(source), output_dir=output)
            second = build_artifacts(str(source), output_dir=output)

            for name in PUBLIC_ARTIFACTS:
                payload = first[name]
                self.assertEqual(payload["schema"], PUBLIC_SCHEMAS[name])
                producer = payload["producer"]
                self.assertEqual(producer["component"], "simplicio-mapper")
                self.assertEqual(producer["backend"], "python")
                self.assertEqual(producer["schema_version"], "v1")
                self.assertEqual(producer["canonical_digest"], canonical_digest(payload))
                if name == "symbol_index":
                    self.assertEqual(payload["version"], 1)
                    self.assertIsInstance(payload["generated_at"], str)
                    self.assertEqual(payload["root"], str(source))
                    self.assertEqual(producer["capability_coverage"]["symbols"], "full")
                    self.assertIsInstance(payload["counts"]["symbols"], int)
                    self.assertIsInstance(payload["counts"]["files"], int)
                    self.assertGreater(payload["counts"]["symbols"], 0)
                    self.assertGreater(payload["counts"]["files"], 0)
                    for symbol in payload["symbols"]:
                        self.assertIsInstance(symbol["defined_in"], str)
                        self.assertEqual(symbol["evidence"]["file"], symbol["defined_in"])
                        self.assertIsInstance(symbol["evidence"]["line"], int)
                schema_id, errors = validate_payload(payload, CONTRACT_ROOT)
                self.assertEqual(schema_id, PUBLIC_SCHEMAS[name])
                self.assertEqual(errors, [], msg=f"{name}: {errors}")
                self.assertEqual(
                    producer["canonical_digest"],
                    second[name]["producer"]["canonical_digest"],
                    msg=f"digest drift for {name}",
                )

    def test_digest_excludes_only_runtime_local_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapper-614-output-") as output:
            artifacts = build_artifacts(
                str(FIXTURES / "python-minimal" / "source"),
                output_dir=output,
            )
            payload = artifacts["project_map"]
            altered = copy.deepcopy(payload)
            altered["generated_at"] = "2099-01-01T00:00:00.000Z"
            altered["files"][0]["last_modified"] = "2099-01-01T00:00:00.000Z"
            self.assertEqual(canonical_digest(payload), canonical_digest(altered))

            altered["files"][0]["size_bytes"] += 1
            self.assertNotEqual(canonical_digest(payload), canonical_digest(altered))

            symbol_payload = artifacts["symbol_index"]
            symbol_altered = copy.deepcopy(symbol_payload)
            symbol_altered["root"] = "/another/machine/repository"
            self.assertEqual(canonical_digest(symbol_payload), canonical_digest(symbol_altered))

    def test_sync_and_async_python_pipelines_share_the_same_semantic_digest(self) -> None:
        source = str(FIXTURES / "python-minimal" / "source")
        with tempfile.TemporaryDirectory(prefix="mapper-614-output-") as output:
            async_artifacts = build_artifacts(source, output_dir=output)
            with patch.dict(os.environ, {"SIMPLICIO_MAPPER_EXECUTION_PROFILE": "sync"}):
                sync_artifacts = build_artifacts(source, output_dir=output)
            for name in PUBLIC_ARTIFACTS:
                self.assertEqual(
                    async_artifacts[name]["schema"],
                    sync_artifacts[name]["schema"],
                )
                self.assertEqual(
                    async_artifacts[name]["producer"]["canonical_digest"],
                    sync_artifacts[name]["producer"]["canonical_digest"],
                    msg=f"sync/async digest drift for {name}",
                )

    def test_matrix_fixture_covers_required_shapes_and_explicit_omissions(self) -> None:
        matrix = json.loads(
            (FIXTURES / "fixture-matrix.json").read_text(encoding="utf-8")
        )
        required = {
            "python", "ts-js", "rust", "go", "java-kotlin", "csharp-razor", "sql",
            "mixed-language-monorepo", "empty-repository", "unknown-language",
            "generated-directory", "large-file", "symlink", "invalid-utf8-legacy-text",
            "duplicate-symbol-names", "dirty-worktree", "untracked-file",
        }
        self.assertTrue(required.issubset({case["id"] for case in matrix["cases"]}))

        fixture = FIXTURES / "canonical-matrix"
        project_map = json.loads((fixture / "artifacts" / "project-map.json").read_text())
        symbols = json.loads((fixture / "artifacts" / "symbol-index.json").read_text())
        paths = {item["path"] for item in project_map["files"]}
        languages = {item["language"] for item in project_map["files"]}
        self.assertEqual(project_map["product"]["project_mode"], "monorepo")
        self.assertTrue({"typescript", "javascript", "rust", "go", "java", "kotlin", "csharp", "razor", "sql"} <= languages)
        self.assertNotIn("dist/generated.js", paths)
        self.assertNotIn("links/app.py", paths)
        self.assertIn("files:large/ignored.txt", project_map["producer"]["omitted_paths"])
        self.assertIn("generated:dist", project_map["producer"]["omitted_paths"])
        self.assertIn("symlink:links/app.py", project_map["producer"]["omitted_paths"])
        duplicate_runs = [item for item in symbols["symbols"] if item["name"] == "run"]
        self.assertGreaterEqual(len(duplicate_runs), 3)

        for name in PUBLIC_ARTIFACTS:
            payload = json.loads((fixture / "artifacts" / f"{name.replace('_', '-')}.json").read_text())
            self.assertEqual(validate_payload(payload, CONTRACT_ROOT)[1], [])
        manifest = json.loads((fixture / "artifacts" / "artifact-manifest.json").read_text())
        fixture_artifacts = {
            name: json.loads((fixture / "artifacts" / f"{name.replace('_', '-')}.json").read_text())
            for name in PUBLIC_ARTIFACTS
        }
        self.assertEqual(validate_payload(manifest, CONTRACT_ROOT)[1], [])
        self.assertEqual(validate_artifact_manifest(manifest, fixture_artifacts), [])

    def test_empty_repository_reports_empty_supported_capabilities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapper-614-empty-") as temp:
            with tempfile.TemporaryDirectory(prefix="mapper-614-output-") as output:
                payloads = build_artifacts(temp, output_dir=output)
            project_map = payloads["project_map"]
            self.assertEqual(project_map["files"], [])
            self.assertEqual(project_map["producer"]["capability_coverage"]["files"], "empty")
            self.assertEqual(
                payloads["symbol_index"]["producer"]["capability_coverage"]["symbols"],
                "empty",
            )

    def test_dirty_worktree_and_untracked_files_are_observable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapper-614-git-") as temp:
            root = Path(temp)
            (root / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "mapper@example.test"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Mapper Test"], cwd=root, check=True)
            subprocess.run(["git", "add", "main.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            (root / "main.py").write_text("def main():\n    return 2\n", encoding="utf-8")
            (root / "untracked.py").write_text("def extra():\n    return 3\n", encoding="utf-8")

            with tempfile.TemporaryDirectory(prefix="mapper-614-output-") as output:
                payload = build_artifacts(str(root), output_dir=output)["project_map"]
            self.assertEqual(payload["producer"]["source_generation"]["kind"], "git-working-tree")
            self.assertTrue(payload["producer"]["source_generation"]["dirty"])
            statuses = {item["path"]: item["git_status"] for item in payload["files"]}
            self.assertEqual(statuses["untracked.py"], "??")
            self.assertIn("untracked.py", payload["changed_files"])

    def test_write_mapping_artifacts_publishes_artifact_set_manifest(self) -> None:
        source = FIXTURES / "python-minimal" / "source"
        with tempfile.TemporaryDirectory(prefix="mapper-624-output-") as output:
            result = write_mapping_artifacts(str(source), output_dir=output)
            manifest_path = Path(result["artifact_manifest_path"])
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts = {
                name: result[name]
                for name in PUBLIC_ARTIFACTS
            }
            self.assertEqual(validate_artifact_manifest(manifest, artifacts), [])
            schema_id, errors = validate_payload(manifest, CONTRACT_ROOT)
            self.assertEqual(schema_id, ARTIFACT_SET_SCHEMA)
            self.assertEqual(errors, [])

        source = FIXTURES / "python-minimal" / "source"
        with tempfile.TemporaryDirectory(prefix="mapper-624-output-") as output:
            artifacts = build_artifacts(str(source), output_dir=output)
            manifest = build_artifact_manifest(artifacts)
            self.assertEqual(manifest["schema"], ARTIFACT_SET_SCHEMA)
            self.assertEqual(set(manifest["artifacts"]), set(PUBLIC_ARTIFACTS))
            self.assertEqual(manifest["generation"], artifacts["project_map"]["producer"]["source_generation"])
            self.assertTrue(manifest["artifact_set_digest"].startswith("sha256:"))
            self.assertEqual(validate_artifact_manifest(manifest, artifacts), [])

            altered = copy.deepcopy(artifacts)
            altered["symbol_index"]["symbols"][0]["name"] += "_changed"
            self.assertNotEqual(validate_artifact_manifest(manifest, altered), [])

    def test_artifact_set_rejects_mixed_generation_and_same_schema_wrong_shape(self) -> None:
        source = FIXTURES / "python-minimal" / "source"
        with tempfile.TemporaryDirectory(prefix="mapper-624-output-") as output:
            artifacts = build_artifacts(str(source), output_dir=output)
            manifest = build_artifact_manifest(artifacts)
            mixed = copy.deepcopy(artifacts)
            mixed["symbol_index"]["producer"]["source_generation"]["revision"] = "stale"
            self.assertTrue(any("generation" in error for error in validate_artifact_manifest(manifest, mixed)))
            wrong_shape = copy.deepcopy(artifacts)
            wrong_shape["symbol_index"]["schema"] = "simplicio.project-map/v1"
            self.assertTrue(any("schema" in error for error in validate_artifact_manifest(manifest, wrong_shape)))


if __name__ == "__main__":
    unittest.main()
