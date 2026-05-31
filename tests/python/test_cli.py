"""Unit tests for the simplicio_mapper Python CLI and mapper.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper import __version__  # noqa: E402
from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.mapper import (  # noqa: E402
    ARTIFACT_SCHEMA,
    PRECEDENT_SCHEMA,
    build_artifacts,
    write_mapping_artifacts,
)
from simplicio_mapper.models import CodeEntity, ProjectFile  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class FileProcessingCacheTest(unittest.TestCase):
    def test_cache_hits_same_file_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = FileProcessingCache(Path(tmp) / "cache")
            try:
                cache.set_processed_file("example.py", 11, 123, {"file_hash": "abc"})

                self.assertEqual(
                    cache.get_processed_file("example.py", 11, 123),
                    {"file_hash": "abc"},
                )
                self.assertIsNone(cache.get_processed_file("example.py", 12, 124))
            finally:
                cache.close()

    def test_primary_models_use_slots(self) -> None:
        project_file = ProjectFile(
            path="app.py",
            language="python",
            size_bytes=10,
            last_modified="2026-01-01T00:00:00.000Z",
            file_hash="abc",
            git_status="clean",
            roles=[],
            imports=[],
            exports=[],
        )
        entity = CodeEntity("app", 1)

        self.assertFalse(hasattr(project_file, "__dict__"))
        self.assertFalse(hasattr(entity, "__dict__"))


class MapperArtifactsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_artifacts_emits_rich_project_map(self) -> None:
        _write(self.dir, "package.json", json.dumps({
            "name": "artifact-host",
            "scripts": {"test": "node --test", "lint": "node scripts/lint.js"},
            "dependencies": {"express": "^4.0.0"},
        }))
        _write(self.dir, "src/server.js",
               "const express = require('express');\nfunction startServer() {}\nmodule.exports = { startServer };\n")
        _write(self.dir, "tests/server.test.js",
               "const { test } = require('node:test');\ntest('starts server', () => {});\n")

        result = build_artifacts(
            cwd=str(self.dir),
            meta={"product_name": "Artifact Host", "stack": "node-express", "project_mode": "root"},
        )
        project_map = result["project_map"]
        precedent_index = result["precedent_index"]

        self.assertEqual(project_map["schema"], ARTIFACT_SCHEMA)
        self.assertEqual(project_map["product"]["name"], "Artifact Host")
        self.assertTrue(any(
            f["path"] == "src/server.js" and f["language"] == "javascript"
            for f in project_map["files"]
        ))
        self.assertIn("src/server.js", project_map["entry_points"])
        self.assertIn("tests/server.test.js", project_map["test_files"])
        self.assertIn("express", project_map["architecture"]["signals"])
        self.assertTrue(any(e["name"] == "server" for e in project_map["entities"]))
        self.assertEqual(precedent_index["schema"], PRECEDENT_SCHEMA)
        self.assertTrue(any(
            item["path"] == "tests/server.test.js" and item["change_type"] == "test"
            for item in precedent_index["items"]
        ))

    def test_build_artifacts_ignores_generated_dependency_and_cache_dirs(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "generated-dirs-host"}))
        _write(self.dir, "GeneratedDirsHost.csproj", "<Project Sdk=\"Microsoft.NET.Sdk\" />\n")
        _write(self.dir, "src/index.ts", "export const answer = 42;\n")
        _write(self.dir, ".angular/cache/chunk.js", "export const cached = true;\n")
        _write(self.dir, "bin/Debug/net9.0/app.dll", "binary-ish text\n")
        _write(self.dir, "obj/project.assets.json", "{}\n")
        _write(self.dir, "output/playwright/report/index.html", "<html></html>\n")
        _write(self.dir, "output/playwright/results/.last-run.json", "{}\n")
        _write(self.dir, ".pytest_cache/README.md", "# cache\n")

        result = build_artifacts(
            cwd=str(self.dir),
            meta={"product_name": "Generated Dirs Host", "stack": "node-angular", "project_mode": "root"},
        )

        paths = {item["path"] for item in result["project_map"]["files"]}
        self.assertIn("src/index.ts", paths)
        self.assertNotIn(".angular/cache/chunk.js", paths)
        self.assertNotIn("bin/Debug/net9.0/app.dll", paths)
        self.assertNotIn("obj/project.assets.json", paths)
        self.assertNotIn("output/playwright/report/index.html", paths)
        self.assertNotIn("output/playwright/results/.last-run.json", paths)
        self.assertNotIn(".pytest_cache/README.md", paths)

    def test_write_mapping_artifacts_persists_files(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "write-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

        out = write_mapping_artifacts(cwd=str(self.dir), meta={"stack": "node"})
        self.assertTrue(os.path.exists(out["project_map_path"]))
        self.assertTrue(os.path.exists(out["precedent_path"]))
        self.assertTrue((self.dir / ".simplicio" / "cache").exists())

        on_disk = json.loads(Path(out["project_map_path"]).read_text())
        self.assertEqual(on_disk["update_mode"], "full")

    def test_incremental_records_changed_files(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "incremental-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")
        write_mapping_artifacts(cwd=str(self.dir), meta={"stack": "node"})

        _write(self.dir, "src/index.js", "export function run() { return 2; }\n")
        result = write_mapping_artifacts(cwd=str(self.dir), meta={"stack": "node"}, incremental=True)

        project_map = result["project_map"]
        self.assertEqual(project_map["update_mode"], "incremental")
        self.assertIn("src/index.js", project_map["changed_files"])

    def test_git_status_marks_untracked_files_inside_new_dirs(self) -> None:
        subprocess.run(["git", "init"], cwd=self.dir, check=True, capture_output=True)
        _write(self.dir, "package.json", json.dumps({"name": "untracked-host"}))
        _write(self.dir, "src/new/index.js", "export function run() { return 1; }\n")

        result = build_artifacts(cwd=str(self.dir), meta={"stack": "node"}, incremental=True)

        project_map = result["project_map"]
        file_entry = next(item for item in project_map["files"] if item["path"] == "src/new/index.js")
        self.assertEqual(file_entry["git_status"], "??")
        self.assertIn("src/new/index.js", project_map["changed_files"])
        self.assertIn(
            {"path": "src/new/index.js", "status": "??"},
            project_map["recent_changes"],
        )


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_main_map_writes_artifacts(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "cli-host"}))
        _write(self.dir, "src/index.js", "export function run() {}\n")

        code = main(["map", "--root", str(self.dir), "--stack", "node",
                     "--product-name", "CLI Host", "--silent"])
        self.assertEqual(code, 0)

        project_map = json.loads((self.dir / ".simplicio" / "project-map.json").read_text())
        self.assertEqual(project_map["product"]["name"], "CLI Host")
        self.assertEqual(project_map["product"]["stack"], "node")

    def test_unknown_option_exits_with_code_2(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["map", "--bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_help_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_version_matches_package(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertTrue(__version__)

    def test_index_writes_json_contract(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "index-host"}))
        _write(self.dir, "src/index.js", "export function run() {}\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.mapper-index/v1")
        self.assertEqual(payload["status"], "updated")
        self.assertEqual(payload["skipped_reason"], None)
        self.assertTrue(payload["paths"]["project_map"].endswith(".simplicio/project-map.json"))
        self.assertTrue(payload["paths"]["precedent_index"].endswith(".simplicio/precedent-index.json"))
        self.assertGreaterEqual(payload["counts"]["files"], 2)
        self.assertGreaterEqual(payload["counts"]["precedents"], 1)

    def test_index_skips_fresh_artifacts_quietly(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "fresh-host"}))
        _write(self.dir, "src/index.js", "export function run() {}\n")

        self.assertEqual(main(["index", str(self.dir)]), 0)

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["skipped_reason"], "already_fresh")

        quiet_out = StringIO()
        with redirect_stdout(quiet_out):
            quiet_code = main(["index", str(self.dir)])
        self.assertEqual(quiet_code, 0)
        self.assertEqual(quiet_out.getvalue(), "")

    def test_endpoints_compares_client_calls_against_server_routes(self) -> None:
        client_dir = self.dir / "client"
        server_dir = self.dir / "server"
        _write(client_dir, "frontend/api_client.py", """
class ApiClient:
    def get(self, path): ...
    def post(self, path, json=None): ...
    def list_skills(self):
        return self.get("/governance/skills")
    def create_snapshot(self, project_id):
        return self.post(f"/projects/{project_id}/snapshots", json={})
""")
        _write(server_dir, "Functions/GovernanceFunctions.cs", """
public sealed class GovernanceFunctions
{
    [Function("ListSkills")]
    public IActionResult ListSkills(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "api/v1/governance/skills")] HttpRequest req) => null!;
}
""")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["endpoints", str(client_dir), "--against", str(server_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.endpoint-inventory/v1")
        self.assertEqual(payload["counts"]["client_calls"], 2)
        self.assertEqual(payload["counts"]["server_routes"], 1)
        self.assertEqual(
            payload["missing_from_server"],
            [{"method": "POST", "path": "/api/v1/projects/{id}/snapshots"}],
        )

    def test_index_refreshes_after_file_change(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "refresh-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        _write(self.dir, "src/index.js", "export function run() { return 2; }\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "updated")
        self.assertIn("src/index.js", payload["changed_files"])


if __name__ == "__main__":
    unittest.main()
