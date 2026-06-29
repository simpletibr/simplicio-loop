"""Unit tests for the simplicio_mapper Python CLI and mapper.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper import __version__  # noqa: E402
from simplicio_mapper.cache import FileProcessingCache  # noqa: E402
from simplicio_mapper.cli import (  # noqa: E402
    _normalize_endpoint_path,
    build_service_flowchart,
    main,
    render_service_flowchart_markdown,
)
from simplicio_mapper.mapper import (  # noqa: E402
    ARCHITECTURE_INVENTORY_SCHEMA,
    ARTIFACT_SCHEMA,
    CALL_GRAPH_SCHEMA,
    PRECEDENT_SCHEMA,
    SYMBOL_INDEX_SCHEMA,
    build_artifacts,
    build_macro_map,
    export_architecture_docs,
    write_architecture_docs,
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
        self.assertEqual(result["architecture_inventory"]["schema"], ARCHITECTURE_INVENTORY_SCHEMA)
        self.assertEqual(result["symbol_index"]["schema"], SYMBOL_INDEX_SCHEMA)
        self.assertEqual(result["call_graph"]["schema"], CALL_GRAPH_SCHEMA)
        self.assertTrue(any(
            module["name"] == "src" and "entrypoint" in module["layers"]
            for module in result["architecture_inventory"]["modules"]
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
        self.assertTrue(os.path.exists(out["architecture_inventory_path"]))
        self.assertTrue(os.path.exists(out["symbol_index_path"]))
        self.assertTrue(os.path.exists(out["call_graph_path"]))
        self.assertTrue((self.dir / ".simplicio" / "cache").exists())

        on_disk = json.loads(Path(out["project_map_path"]).read_text())
        self.assertEqual(on_disk["update_mode"], "full")

    def test_architecture_inventory_tracks_layers_symbols_and_relationships(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "inventory-host"}))
        _write(self.dir, "src/controllers/user.controller.js", """
const { listUsers } = require('../services/user.service');
function getUsers() {
  return listUsers();
}
module.exports = { getUsers };
""")
        _write(self.dir, "src/services/user.service.js", """
const { findUsers } = require('../repositories/user.repository');
function listUsers() {
  return findUsers();
}
module.exports = { listUsers };
""")
        _write(self.dir, "src/repositories/user.repository.js", """
function findUsers() {
  return [];
}
module.exports = { findUsers };
""")
        _write(self.dir, "tests/user.test.js", "test('users', () => {});\n")

        result = build_artifacts(cwd=str(self.dir), meta={"stack": "node"})

        inventory = result["architecture_inventory"]
        symbols = result["symbol_index"]["symbols"]
        edges = result["call_graph"]["edges"]
        self.assertEqual(inventory["schema"], ARCHITECTURE_INVENTORY_SCHEMA)
        self.assertTrue(any(layer["name"] == "controller" for layer in inventory["layers"]))
        self.assertTrue(any(layer["name"] == "service" for layer in inventory["layers"]))
        self.assertTrue(any(layer["name"] == "repository" for layer in inventory["layers"]))
        self.assertTrue(any(symbol["name"] == "listUsers" for symbol in symbols))
        self.assertTrue(any(edge["type"] == "imports" for edge in edges))

    def test_architecture_docs_and_export_render_markdown(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "docs-host"}))
        _write(self.dir, "src/services/user.service.py", "def list_users():\n    return []\n")
        write_mapping_artifacts(cwd=str(self.dir), meta={"stack": "python"})

        docs = write_architecture_docs(str(self.dir))
        architecture_doc = self.dir / ".simplicio" / "docs" / "architecture.md"
        self.assertTrue(architecture_doc.exists())
        self.assertIn("Architecture Inventory", architecture_doc.read_text())
        self.assertGreaterEqual(docs["counts"]["files"], 4)

        target = self.dir / "wiki"
        exported = export_architecture_docs(str(self.dir), str(target))
        self.assertTrue((target / "architecture.md").exists())
        self.assertEqual(exported["counts"]["files"], docs["counts"]["files"])

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


class EndpointNormalizationTest(unittest.TestCase):
    """Endpoint path normalization must stay project-agnostic (issue #104)."""

    def test_placeholders_collapse_to_id(self) -> None:
        self.assertEqual(
            _normalize_endpoint_path("/api/v1/projects/{projectId}/snapshots"),
            "/api/v1/projects/{id}/snapshots",
        )
        self.assertEqual(
            _normalize_endpoint_path("/api/v1/projects/${id}/snapshots"),
            "/api/v1/projects/{id}/snapshots",
        )

    def test_uuid_segments_collapse_to_id(self) -> None:
        self.assertEqual(
            _normalize_endpoint_path(
                "/api/v1/users/12345678-1234-1234-1234-123456789012"
            ),
            "/api/v1/users/{id}",
        )

    def test_numeric_segments_collapse_to_id(self) -> None:
        self.assertEqual(
            _normalize_endpoint_path("/users/42"),
            "/users/{id}",
        )
        self.assertEqual(
            _normalize_endpoint_path("/api/v1/orders/1001/items/55"),
            "/api/v1/orders/{id}/items/{id}",
        )

    def test_unknown_slug_segments_stay_literal(self) -> None:
        # Pre-#104 the EVT-specific regex collapsed `/api/v1/areas/<slug>` to
        # `/api/v1/areas/{id}`. After generalization a slug that is neither
        # numeric nor a UUID is kept as-is so the mapper does not invent IDs
        # for arbitrary downstream resources.
        self.assertEqual(
            _normalize_endpoint_path("/api/v1/areas/some-slug"),
            "/api/v1/areas/some-slug",
        )
        self.assertEqual(
            _normalize_endpoint_path("/api/v1/governance/skills/foo-bar"),
            "/api/v1/governance/skills/foo-bar",
        )

    def test_query_string_and_leading_slash_normalization(self) -> None:
        self.assertEqual(
            _normalize_endpoint_path("api/v1/users/42?expand=details"),
            "/api/v1/users/{id}",
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

    def test_index_accepts_update_compatibility_flag(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "index-update-host"}))
        _write(self.dir, "src/index.js", "export function run() {}\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", "--update", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.mapper-index/v1")
        self.assertEqual(payload["status"], "updated")

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
            [{
                "method": "POST",
                "path": "/api/v1/projects/{id}/snapshots",
                "sources": ["frontend/api_client.py"],
            }],
        )

    def test_endpoints_resolves_angular_service_base_urls(self) -> None:
        client_dir = self.dir / "angular-client"
        server_dir = self.dir / "server"
        _write(client_dir, "src/app/core/services/users.service.ts", """
import { environment } from '../../../environments/environment';

export class UsersService {
    private readonly baseUrl = `${environment.apiUrl}/admin/users`;

    list() {
        return this.http.get<User[]>(this.baseUrl);
    }
    filters() {
        return this.http.get(`${this.baseUrl}/filters`);
    }
    create(payload: unknown) {
        return this.http.post(this.baseUrl, payload);
    }
    status(userId: string) {
        return this.http.patch(`${this.baseUrl}/${userId}/status`, {});
    }
    demoEvidence() {
        return this.http.get('/api/v1/projects/42/evidence');
    }
}
""")
        _write(server_dir, "Functions/UsersFunctions.cs", """
public sealed class UsersFunctions
{
    [Function("UsersList")]
    public IActionResult List(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "api/v1/admin/users")] HttpRequest req) => null!;
    [Function("UsersFilters")]
    public IActionResult Filters(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "api/v1/admin/users/filters")] HttpRequest req) => null!;
    [Function("UsersCreate")]
    public IActionResult Create(
        [HttpTrigger(AuthorizationLevel.Anonymous, "post", Route = "api/v1/admin/users")] HttpRequest req) => null!;
    [Function("UsersStatus")]
    public IActionResult Status(
        [HttpTrigger(AuthorizationLevel.Anonymous, "patch", Route = "api/v1/admin/users/{userId:guid}/status")] HttpRequest req) => null!;
    [Function("EvidenceList")]
    public IActionResult Evidence(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "api/v1/projects/{projectId}/evidence")] HttpRequest req) => null!;
}
""")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["endpoints", str(client_dir), "--against", str(server_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["counts"]["client_calls"], 5)
        self.assertEqual(payload["missing_from_server"], [])

    def test_screens_extracts_angular_routes(self) -> None:
        app_dir = self.dir / "angular-app"
        _write(app_dir, "src/app/app.routes.ts", """
import { Routes } from '@angular/router';
import { LoginPageComponent } from './login';
import { AdminShellComponent } from './admin-shell';
import { AdminUsersComponent } from './users';
import { ClientProjectComponent } from './client-project';
import { authGuard } from './auth.guard';

export const routes: Routes = [
  {
    path: '',
    component: LoginPageComponent,
  },
  {
    path: 'client',
    pathMatch: 'full',
    component: LoginPageComponent,
    data: { defaultUserType: 'client' },
  },
  {
    path: 'admin',
    component: AdminShellComponent,
    canActivate: [authGuard],
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'users' },
      { path: 'users', component: AdminUsersComponent },
    ],
  },
  {
    path: 'clients/projects/:projectId',
    component: ClientProjectComponent,
    canActivate: [authGuard],
  },
];
""")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["screens", str(app_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.screen-inventory/v1")
        self.assertEqual(payload["counts"]["screens"], 5)
        self.assertEqual(payload["counts"]["redirects"], 1)
        self.assertEqual(payload["counts"]["dynamic"], 1)
        self.assertTrue(any(
            item["path"] == "/admin/users"
            and item["component"] == "AdminUsersComponent"
            and item["persona"] == "admin"
            for item in payload["screens"]
        ))
        self.assertTrue(any(
            item["path"] == "/client"
            and item["component"] == "LoginPageComponent"
            and item["persona"] == "client"
            for item in payload["screens"]
        ))
        self.assertTrue(any(
            item["path"] == "/admin"
            and item["redirect_to"] == "users"
            for item in payload["redirects"]
        ))

    def test_docs_command_writes_markdown_json_contract(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "cli-docs-host"}))
        _write(self.dir, "src/services/user.service.py", "def list_users():\n    return []\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["docs", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.architecture-docs/v1")
        self.assertTrue((self.dir / ".simplicio" / "docs" / "architecture.md").exists())
        self.assertGreaterEqual(payload["counts"]["files"], 4)

    def test_export_docs_command_copies_markdown(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "cli-export-host"}))
        _write(self.dir, "src/repositories/user.repository.py", "def find_users():\n    return []\n")
        target = self.dir / "exported-wiki"

        out = StringIO()
        with redirect_stdout(out):
            code = main(["export-docs", str(self.dir), "--target", str(target), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.docs-export/v1")
        self.assertTrue((target / "architecture.md").exists())
        self.assertGreaterEqual(payload["counts"]["files"], 4)

    def _flowchart_app(self) -> Path:
        app_dir = self.dir / "flow-app"
        _write(app_dir, "src/app/app.routes.ts", """
import { Routes } from '@angular/router';
import { AdminUsersComponent } from './admin/users/users.component';
import { ClientProjectComponent } from './client/project.component';
import { authGuard } from './auth.guard';

export const routes: Routes = [
  {
    path: 'admin/users',
    component: AdminUsersComponent,
    canActivate: [authGuard],
  },
  {
    path: 'clients/:projectId',
    component: ClientProjectComponent,
  },
];
""")
        _write(app_dir, "src/app/admin/users/users.component.ts", """
import { Component } from '@angular/core';
import { Validators } from '@angular/forms';

@Component({
  selector: 'app-admin-users',
  template: `<section>
    <button (click)="save()">Save user</button>
    <button (click)="refresh()" aria-label="Reload list">Refresh</button>
  </section>`,
})
export class AdminUsersComponent {
  form = { name: ['', Validators.required] };
  save() { this.http.post('/api/v1/admin/users', this.payload); }
  refresh() { this.list(); }
}
""")
        _write(app_dir, "src/app/admin/users/users.service.ts", """
import { environment } from '../../../environments/environment';

export class UsersService {
  private readonly baseUrl = `${environment.apiUrl}/admin/users`;
  list() { return this.http.get(this.baseUrl); }
}
""")
        _write(app_dir, "src/app/client/project.component.ts", """
import { Component } from '@angular/core';

@Component({ selector: 'app-client-project', template: `<div>project</div>` })
export class ClientProjectComponent {}
""")
        _write(app_dir, "src/app/shared/orphan.service.ts", """
export class OrphanService {
  ping() { return this.http.get('/api/v1/health/ping'); }
}
""")
        _write(app_dir, "server/Functions/UsersFunctions.cs", """
public sealed class UsersFunctions {
  [Function("UsersCreate")]
  public IActionResult Create(
    [HttpTrigger(AuthorizationLevel.Function, "post", Route = "api/v1/admin/users")] HttpRequest req,
    [FromBody] CreateUserDto dto) {
    var saved = _repository.Save(dto);
    _dbContext.SaveChanges();
    return Ok(new UserResponse());
  }
}
""")
        _write(app_dir, "server/api/health.py", """
from fastapi import APIRouter

router = APIRouter(prefix="/health")

@router.get("/ping")
async def ping(limit: int) -> PingResult:
    rows = session.query(Heartbeat).all()
    return PingResult(items=rows)
""")
        return app_dir

    def test_flowchart_builds_frontend_and_backend_faces(self) -> None:
        app_dir = self._flowchart_app()
        model = build_service_flowchart(str(app_dir))

        self.assertEqual(model["schema"], "simplicio.service-flowchart/v1")
        admin = next(s for s in model["screens"] if s["path"] == "/admin/users")
        self.assertEqual(admin["persona"], "admin")
        self.assertTrue(admin["guarded"])
        self.assertIn(
            ("GET", "/api/v1/admin/users"),
            {(s["method"], s["path"]) for s in admin["services"]},
        )
        save = next(b for b in admin["buttons"] if b["handler"] == "save")
        self.assertEqual(save["label"], "Save user")
        self.assertEqual(
            save["services"], [{"method": "POST", "path": "/api/v1/admin/users"}]
        )
        refresh = next(b for b in admin["buttons"] if b["handler"] == "refresh")
        self.assertEqual(refresh["label"], "Refresh")
        self.assertEqual(refresh["services"], [])
        rule_kinds = {rule["kind"] for rule in admin["rules"]}
        self.assertEqual(rule_kinds, {"guard", "persona", "validator"})

        client = next(s for s in model["screens"] if s["path"] == "/clients/:projectId")
        self.assertTrue(any(rule["kind"] == "dynamic-route" for rule in client["rules"]))

        self.assertEqual(
            model["unlinked_services"],
            [{"method": "GET", "path": "/api/v1/health/ping", "file": "src/app/shared/orphan.service.ts"}],
        )

        flows = {(f["method"], f["path"]): f for f in model["backend"]}
        create = flows[("POST", "/api/v1/admin/users")]
        self.assertEqual(create["auth"], "Function")
        self.assertEqual(create["request"], ["CreateUserDto"])
        self.assertEqual(create["response"], ["UserResponse"])
        self.assertTrue(create["db_access"])
        self.assertEqual(create["external_count"], 2)
        self.assertEqual(create["layer"], "function")
        self.assertTrue(any(step.startswith("Receive POST") for step in create["steps"]))

        ping = flows[("GET", "/api/v1/health/ping")]
        self.assertEqual(ping["request"], ["int"])
        self.assertEqual(ping["response"], ["PingResult"])
        self.assertTrue(ping["db_access"])

        self.assertEqual(model["counts"]["db_flows"], 2)

    def test_flowchart_command_writes_doc_and_json(self) -> None:
        app_dir = self._flowchart_app()

        out = StringIO()
        with redirect_stdout(out):
            code = main(["flowchart", str(app_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.service-flowchart/v1")
        doc = app_dir / ".simplicio" / "docs" / "flowchart.md"
        self.assertTrue(doc.exists())
        text = doc.read_text(encoding="utf-8")
        self.assertIn("```mermaid", text)
        self.assertIn("flowchart TD", text)
        self.assertIn("flowchart LR", text)
        self.assertIn("## Backend Flows", text)
        self.assertIn("Read/write database", text)

    def test_flowchart_reads_external_template_url(self) -> None:
        app_dir = self.dir / "tpl-app"
        _write(app_dir, "src/app/app.routes.ts", """
import { Routes } from '@angular/router';
import { ReportComponent } from './report/report.component';

export const routes: Routes = [
  { path: 'admin/report', component: ReportComponent },
];
""")
        _write(app_dir, "src/app/report/report.component.ts", """
import { Component } from '@angular/core';

@Component({
  selector: 'app-report',
  templateUrl: './report.component.html',
})
export class ReportComponent {
  download() { this.http.get('/api/v1/admin/report'); }
}
""")
        _write(app_dir, "src/app/report/report.component.html", """
<button (click)="download()">Download report</button>
""")

        model = build_service_flowchart(str(app_dir))
        screen = next(s for s in model["screens"] if s["path"] == "/admin/report")
        button = next(b for b in screen["buttons"] if b["handler"] == "download")
        self.assertEqual(button["label"], "Download report")
        self.assertEqual(
            button["services"], [{"method": "GET", "path": "/api/v1/admin/report"}]
        )

    def test_flowchart_renders_empty_project_safely(self) -> None:
        empty = self.dir / "empty-app"
        _write(empty, "README.md", "# nothing here\n")
        model = build_service_flowchart(str(empty))
        markdown = render_service_flowchart_markdown(model)
        self.assertIn("No frontend screens", markdown)
        self.assertEqual(model["counts"]["backend_flows"], 0)

    def test_docs_pipeline_includes_flowchart(self) -> None:
        app_dir = self._flowchart_app()
        write_architecture_docs(str(app_dir))
        flowchart_doc = app_dir / ".simplicio" / "docs" / "flowchart.md"
        self.assertTrue(flowchart_doc.exists())
        self.assertIn("# Service Flowchart", flowchart_doc.read_text(encoding="utf-8"))

    def test_endpoints_captures_python_page_api_calls(self) -> None:
        client_dir = self.dir / "streamlit-client"
        server_dir = self.dir / "server"
        _write(client_dir, "frontend/pages/admin_users.py", """
@router.get("/should-not-count-as-client")
def route_definition():
    return {}

@app.get("/also-not-a-client-call")
def app_route_definition():
    return {}

def save(api, user_id, area_ids):
    api.patch(f"/users/{user_id}", json={"full_name": "A"})
    api._client.put(f"/users/{user_id}/areas", json={"area_ids": area_ids})
    api.get("/api/v1/users")
""")
        _write(client_dir, "tests/unit/test_app.py", """
def test_openapi(client):
    client.get("/openapi.json")
""")
        _write(server_dir, "Functions/UsersFunctions.cs", """
public sealed class UsersFunctions
{
    [Function("UsersPatch")]
    public IActionResult PatchUser(
        [HttpTrigger(AuthorizationLevel.Anonymous, "patch", Route = "api/v1/users/{userId:guid}")] HttpRequest req) => null!;
    [Function("UsersAreasPut")]
    public IActionResult PutAreas(
        [HttpTrigger(AuthorizationLevel.Anonymous, "put", Route = "api/v1/users/{userId:guid}/areas")] HttpRequest req) => null!;
    [Function("UsersList")]
    public IActionResult List(
        [HttpTrigger(AuthorizationLevel.Anonymous, "get", Route = "api/v1/users")] HttpRequest req) => null!;
}
""")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["endpoints", str(client_dir), "--against", str(server_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["counts"]["client_calls"], 3)
        self.assertEqual(payload["missing_from_server"], [])

    def test_endpoints_json_includes_sources_for_missing_routes(self) -> None:
        client_dir = self.dir / "source-client"
        server_dir = self.dir / "source-server"
        _write(client_dir, "frontend/page.py", """
def load(api):
    return api.get("/widgets")
""")
        _write(server_dir, "backend/routes.py", "from fastapi import APIRouter\nrouter = APIRouter()\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["endpoints", str(client_dir), "--against", str(server_dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        missing = payload["missing_from_server"]
        self.assertEqual(1, len(missing))
        self.assertEqual(["frontend/page.py"], missing[0]["sources"])

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

    def test_index_refreshes_when_dirty_file_changes_again(self) -> None:
        subprocess.run(["git", "init"], cwd=self.dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.dir, check=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.dir, check=True)
        _write(self.dir, "package.json", json.dumps({"name": "dirty-refresh-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")
        subprocess.run(["git", "add", "."], cwd=self.dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.dir, check=True, capture_output=True)

        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        _write(self.dir, "src/index.js", "export function run() { return 2; }\n")
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        _write(self.dir, "src/index.js", "export function run() { return 3; }\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "updated")

    def test_index_skips_with_explicit_lock(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "locked-host"}))
        lock = self.dir / ".simplicio" / "index.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("123\n", encoding="utf-8")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["skipped_reason"], "locked")

    def test_background_index_reports_pid_and_log(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "background-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main([
                "index",
                str(self.dir),
                "--background",
                "--stack",
                "python",
                "--product-name",
                "Background Host",
                "--json",
            ])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.background-index/v1")
        self.assertEqual(payload["status"], "started")
        self.assertGreater(payload["pid"], 0)
        self.assertTrue(payload["log"].endswith(".simplicio/background-index.log"))
        project_map = self.dir / ".simplicio" / "project-map.json"
        for _ in range(40):
            if project_map.exists():
                break
            time.sleep(0.05)
        self.assertTrue(project_map.exists())
        mapped = json.loads(project_map.read_text())
        self.assertEqual(mapped["product"]["name"], "Background Host")
        self.assertEqual(mapped["product"]["stack"], "python")

    def test_docs_only_renders_without_index_payload(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "docs-only-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--docs-only", "--json"])

        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.architecture-docs/v1")
        self.assertTrue((self.dir / ".simplicio" / "docs" / "architecture.md").exists())

    def _seed_multi_stack(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "macro-host"}))
        _write(self.dir, "pyproject.toml", "[project]\nname = 'macro-host'\n")
        _write(self.dir, "src/app/page.tsx", "export default function Page() {}\n")
        _write(self.dir, "src/app/users.component.ts", "export class UsersComponent {}\n")
        _write(self.dir, "api/Users.cs", "public class UsersController {}\n")
        _write(self.dir, "services/user_service.py", "def get_user():\n    return 1\n")
        _write(self.dir, "tests/test_user.py", "def test_x():\n    assert True\n")

    def test_macro_no_full_content_reads(self) -> None:
        # build_macro_map must not read arbitrary file content: a binary,
        # unreadable-as-text file under the tree must not raise.
        self._seed_multi_stack()
        (self.dir / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
        macro = build_macro_map(str(self.dir))
        self.assertEqual(macro["schema"], "simplicio.macro-map/v1")
        self.assertEqual(macro["confidence"], "shallow")

    def test_macro_deterministic_counts(self) -> None:
        self._seed_multi_stack()
        first = build_macro_map(str(self.dir))
        second = build_macro_map(str(self.dir))
        self.assertEqual(first["counts"], second["counts"])
        counts = first["counts"]
        self.assertGreaterEqual(counts["screens"], 2)  # page.tsx + users.component.ts
        self.assertEqual(counts["tests"], 1)
        self.assertGreaterEqual(counts["by_language"]["python"], 2)
        self.assertGreaterEqual(counts["by_language"]["csharp"], 1)
        self.assertGreaterEqual(counts["endpoint_files"], 4)

    def test_macro_command_json_schema(self) -> None:
        self._seed_multi_stack()
        out = StringIO()
        with redirect_stdout(out):
            code = main(["macro", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.macro-map/v1")
        for key in ("product", "counts", "modules", "layers", "entry_points",
                    "config_files", "git", "confidence"):
            self.assertIn(key, payload)

    def test_scan_sync_returns_complete_envelope(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "scan-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["scan", str(self.dir), "--sync", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.map-job/v1")
        self.assertEqual(payload["phase"], "complete")
        self.assertTrue(payload["sync"])
        self.assertEqual(payload["macro"]["schema"], "simplicio.macro-map/v1")
        self.assertTrue((self.dir / ".simplicio" / "project-map.json").exists())
        self.assertTrue((self.dir / ".simplicio" / "map-job.json").exists())

    def test_scan_async_returns_before_deep_completes(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "async-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["scan", str(self.dir), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["phase"], "macro_done")
        self.assertFalse(payload["sync"])
        self.assertGreater(payload["deep"]["pid"], 0)
        # Wait for the detached deep pass to finish, then status must report complete.
        project_map = self.dir / ".simplicio" / "project-map.json"
        for _ in range(80):
            if project_map.exists():
                break
            time.sleep(0.05)
        self.assertTrue(project_map.exists())

    def test_scan_sync_lock_guarded(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "guard-host"}))
        lock = self.dir / ".simplicio" / "index.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("123\n", encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["scan", str(self.dir), "--sync", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        # Lock held by another run: deep skips, artifacts absent -> failed.
        self.assertEqual(payload["phase"], "failed")

    def test_status_reports_running_then_complete(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "status-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")
        lock = self.dir / ".simplicio" / "index.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("123\n", encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["status", str(self.dir), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["phase"], "deep_running")

        lock.unlink()
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["status", str(self.dir), "--await", "--timeout", "5", "--json"]), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["phase"], "complete")
        self.assertTrue(payload["fresh"])

    def test_status_unknown_without_run(self) -> None:
        _write(self.dir, "package.json", json.dumps({"name": "unknown-host"}))
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(["status", str(self.dir), "--json"]), 0)
        self.assertEqual(json.loads(out.getvalue())["phase"], "unknown")


class TierLanguageSupportTest(unittest.TestCase):
    """Tier 1/2 language coverage: detection + symbol/import extraction."""

    FILES = {
        "lib/main.dart": "import 'package:flutter/material.dart';\nclass MyApp {}\nenum Color { red, green }\nvoid main() {}\n",
        "db/schema.sql": "CREATE TABLE users (id int);\nCREATE OR REPLACE VIEW active_users AS SELECT 1;\nCREATE FUNCTION get_user() RETURNS int AS $$ BEGIN END $$;\n",
        "src/main.c": "#include <stdio.h>\nstruct Point { int x; };\nint add(int a, int b) {\n  return a + b;\n}\n",
        "src/app.cpp": "#include \"app.h\"\nclass Engine {\npublic:\n  void run() {\n    start();\n  }\n};\n",
        "ios/App.swift": "import Foundation\nclass ViewController {}\nstruct Model {}\nfunc greet() {}\n",
        "ios/Legacy.m": "#import <UIKit/UIKit.h>\n@interface Foo\n@end\n@implementation Foo\n- (void)doThing {}\n@end\n",
        "ui/Button.vue": "<script>\nimport x from './x';\nexport function handleClick() {}\n</script>\n",
        "ui/Card.svelte": "<script>\nimport y from './y';\nfunction render() {}\n</script>\n",
        "be/Service.scala": "import scala.collection.mutable\nobject Main\nclass Repo\ndef compute() = 1\n",
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for rel, content in self.FILES.items():
            _write(self.dir, rel, content)
        self.result = build_artifacts(cwd=str(self.dir), meta={})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_language_detection(self) -> None:
        langs = {f["path"]: f["language"] for f in self.result["project_map"]["files"]}
        self.assertEqual(langs["lib/main.dart"], "dart")
        self.assertEqual(langs["db/schema.sql"], "sql")
        self.assertEqual(langs["src/main.c"], "c")
        self.assertEqual(langs["src/app.cpp"], "cpp")
        self.assertEqual(langs["ios/App.swift"], "swift")
        self.assertEqual(langs["ios/Legacy.m"], "objectivec")
        self.assertEqual(langs["ui/Button.vue"], "vue")
        self.assertEqual(langs["ui/Card.svelte"], "svelte")
        self.assertEqual(langs["be/Service.scala"], "scala")

    def test_symbols_extracted_per_language(self) -> None:
        by_file: dict[str, set[str]] = {}
        for s in self.result["symbol_index"]["symbols"]:
            by_file.setdefault(s["defined_in"], set()).add(f"{s['kind']}:{s['name']}")
        self.assertIn("class:MyApp", by_file["lib/main.dart"])
        self.assertIn("enum:Color", by_file["lib/main.dart"])
        self.assertIn("table:users", by_file["db/schema.sql"])
        self.assertIn("view:active_users", by_file["db/schema.sql"])
        self.assertIn("function:get_user", by_file["db/schema.sql"])
        self.assertIn("struct:Point", by_file["src/main.c"])
        self.assertIn("class:Engine", by_file["src/app.cpp"])
        self.assertIn("class:ViewController", by_file["ios/App.swift"])
        self.assertIn("class:Foo", by_file["ios/Legacy.m"])
        self.assertIn("function:handleClick", by_file["ui/Button.vue"])
        self.assertIn("function:render", by_file["ui/Card.svelte"])
        self.assertIn("class:Repo", by_file["be/Service.scala"])

    def test_imports_extracted_per_language(self) -> None:
        imports = {f["path"]: f.get("imports", []) for f in self.result["project_map"]["files"]}
        self.assertIn("package:flutter/material.dart", imports["lib/main.dart"])
        self.assertIn("Foundation", imports["ios/App.swift"])
        self.assertIn("stdio.h", imports["src/main.c"])
        self.assertIn("UIKit/UIKit.h", imports["ios/Legacy.m"])
        self.assertIn("scala.collection.mutable", imports["be/Service.scala"])
        self.assertIn("./x", imports["ui/Button.vue"])

    def test_new_languages_in_call_graph(self) -> None:
        from simplicio_mapper.mapper import _CALL_GRAPH_LANGUAGES
        for lang in ("dart", "swift", "objectivec", "c", "cpp", "scala", "vue", "svelte"):
            self.assertIn(lang, _CALL_GRAPH_LANGUAGES)
        # SQL is intentionally excluded from the call graph (it has no call sites).
        self.assertNotIn("sql", _CALL_GRAPH_LANGUAGES)

    def test_dart_control_flow_not_captured_as_function(self) -> None:
        _write(
            self.dir,
            "w.dart",
            "class W {\n  void build() {\n    if (cond) { x(); }\n    for (var i = 0;;) {}\n  }\n}\n",
        )
        result = build_artifacts(cwd=str(self.dir), meta={})
        names = {f"{s['kind']}:{s['name']}" for s in result["symbol_index"]["symbols"]}
        self.assertIn("function:build", names)
        self.assertNotIn("function:if", names)
        self.assertNotIn("function:for", names)

    def test_sql_schema_qualified_captures_table_name(self) -> None:
        _write(
            self.dir,
            "s.sql",
            "CREATE TABLE `db`.`users` (id int);\nCREATE TABLE public.orders (id int);\n",
        )
        result = build_artifacts(cwd=str(self.dir), meta={})
        tables = {s["name"] for s in result["symbol_index"]["symbols"] if s["kind"] == "table"}
        self.assertIn("users", tables)
        self.assertIn("orders", tables)
        self.assertNotIn("db", tables)


class LlmDirectivesTest(unittest.TestCase):
    """The mapper hands a no-think / no-internet / minimal-tools-skills contract
    to any LLM that consumes its artifacts."""

    EXPECTED = {
        "no_thinking": True,
        "no_internet": True,
        "tools": "only_necessary",
        "skills": "only_necessary",
    }

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "directive-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_project_map_carries_directives(self) -> None:
        result = build_artifacts(cwd=str(self.dir), meta={})
        directives = result["project_map"]["integration"]["llm_directives"]
        for key, value in self.EXPECTED.items():
            self.assertEqual(directives[key], value)
        self.assertIn("No-thinking", directives["instruction"])
        self.assertIn("No-internet", directives["instruction"])

    def test_context_pack_carries_directives(self) -> None:
        from simplicio_mapper.context_pack import build_context_pack
        build_artifacts(cwd=str(self.dir), meta={})
        from simplicio_mapper.mapper import write_mapping_artifacts
        write_mapping_artifacts(cwd=str(self.dir), meta={})
        pack = build_context_pack(
            root=str(self.dir),
            targets=[{"path": "src/index.js"}],
        )
        for key, value in self.EXPECTED.items():
            self.assertEqual(pack["llm_directives"][key], value)


if __name__ == "__main__":
    unittest.main()
