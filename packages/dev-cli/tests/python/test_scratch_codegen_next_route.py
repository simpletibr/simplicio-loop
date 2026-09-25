"""Tests for deterministic Next.js route scratch codegen."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio.scratch.codegen import TypeScriptAddNextRouteExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.codegen.typescript_next_route import _ts_morph_env
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack

# `TypeScriptAddNextRouteExecutor.execute()` shells out to Node.js + ts-morph
# to do its deterministic (non-LLM) codegen (see `_ts_morph_env`/
# `_ensure_ts_morph_cache` in typescript_next_route.py); the executor itself
# degrades gracefully when Node is absent (`fallback_to_llm=True`, covered by
# `test_typescript_add_next_route_executor_falls_back_for_non_route_target`
# and the registry test below, neither of which needs Node). Node/npm are
# not a declared dependency of this Python package (no `pyproject.toml`
# entry, no `scripts/dev_install.sh` step can install them), so a test that
# actually drives the deterministic path cannot assert anything if Node
# isn't on PATH — same reasoning `test_scratch_codegen_rust_axum.py`
# already applies to `cargo`. Skip with a typed reason rather than fail
# hard when the optional toolchain genuinely isn't installed.
requires_node = pytest.mark.skipif(
    shutil.which("node") is None and shutil.which("node.exe") is None,
    reason="node not available (undeclared toolchain: ts-morph codegen needs Node.js)",
)


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="ts-nextjs",
        path=tmp_path,
        meta={"language": "TypeScript 5", "framework": "Next.js 14 (app router)"},
    )


def _task(goal: str = "Create Next.js route handlers for Unit CRUD") -> Task:
    return Task(
        id="T02-next-route",
        goal=goal,
        target="src/app/api/units/route.ts",
        criteria="- exports GET and POST handlers\n- returns JSON responses",
        constraints="- no external dependencies",
        verify="pnpm vitest run src/app/api/units/route.test.ts",
    )


@requires_node
def test_typescript_add_next_route_executor_creates_json_handlers(tmp_path):
    executor = TypeScriptAddNextRouteExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    route = tmp_path / "src/app/api/units/route.ts"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [route]
    generated = route.read_text(encoding="utf-8")
    assert "export async function GET(): Promise<Response>" in generated
    assert "return Response.json(units);" in generated
    assert "export async function POST(request: Request): Promise<Response>" in generated
    assert "return Response.json(body, { status: 201 });" in generated


@requires_node
def test_typescript_add_next_route_executor_outputs_runnable_json_handlers(tmp_path):
    result = TypeScriptAddNextRouteExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True

    route = tmp_path / "src/app/api/units/route.ts"
    ok, env_or_log = _ts_morph_env(tmp_path)
    assert ok, env_or_log
    node = shutil.which("node") or shutil.which("node.exe")
    assert node is not None

    proc = subprocess.run(
        [
            node,
            "-e",
            _ROUTE_RUNTIME_CHECK,
            str(route),
        ],
        capture_output=True,
        text=True,
        env=env_or_log,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "get": [],
        "post": {"name": "Unit 1"},
        "postStatus": 201,
    }


@requires_node
def test_typescript_add_next_route_executor_appends_missing_handler(tmp_path):
    route = tmp_path / "src/app/api/units/route.ts"
    route.parent.mkdir(parents=True)
    route.write_text(
        """export async function GET(): Promise<Response> {
  return Response.json([]);
}
""",
        encoding="utf-8",
    )

    result = TypeScriptAddNextRouteExecutor().execute(
        _task("Add POST endpoint to `/api/units` route"),
        tmp_path,
        _stack(tmp_path),
    )

    generated = route.read_text(encoding="utf-8")
    assert result.passed is True
    assert generated.count("export async function GET") == 1
    assert "export async function POST(request: Request): Promise<Response>" in generated


def test_typescript_add_next_route_executor_falls_back_for_non_route_target(tmp_path):
    result = TypeScriptAddNextRouteExecutor().execute(
        Task(
            id="T02-next-route",
            goal="Create Next.js route handlers for Unit CRUD",
            target="src/app/units/page.tsx",
            criteria="- no route file",
            constraints="",
            verify="pnpm vitest run",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported Next.js route task shape" in result.log


def test_default_registry_includes_typescript_next_route_executor():
    assert any(
        isinstance(executor, TypeScriptAddNextRouteExecutor)
        for executor in codegen_registry.registered_executors()
    )


_ROUTE_RUNTIME_CHECK = r"""
const fs = require("fs");
const ts = require("typescript");
const vm = require("vm");

(async () => {
  const source = fs.readFileSync(process.argv[1], "utf8");
  const program = ts.createProgram([process.argv[1]], {
    noEmit: true,
    strict: true,
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    lib: ["lib.es2022.d.ts", "lib.dom.d.ts"],
    skipLibCheck: true,
  });
  const diagnostics = ts.getPreEmitDiagnostics(program);
  if (diagnostics.length > 0) {
    console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, {
      getCanonicalFileName: (fileName) => fileName,
      getCurrentDirectory: () => process.cwd(),
      getNewLine: () => "\n",
    }));
    process.exit(1);
  }

  const output = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.CommonJS,
    },
  }).outputText;
  const context = {
    exports: {},
    Response,
    Request,
  };
  vm.runInNewContext(output, context);
  const getResponse = await context.exports.GET();
  const postResponse = await context.exports.POST(new Request("https://example.test/api/units", {
    method: "POST",
    body: JSON.stringify({ name: "Unit 1" }),
    headers: { "content-type": "application/json" },
  }));
  console.log(JSON.stringify({
    get: await getResponse.json(),
    post: await postResponse.json(),
    postStatus: postResponse.status,
  }));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
"""
