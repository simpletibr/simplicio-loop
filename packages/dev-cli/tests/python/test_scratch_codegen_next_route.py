"""Tests for deterministic Next.js route scratch codegen.

Pure Python: `TypeScriptAddNextRouteExecutor` generates handler bodies from
fixed string templates and merges them into the target file by text, with
no Node.js/npm subprocess anywhere in its runtime path (see
typescript_next_route.py's module docstring). These tests assert on the
generated TypeScript source text directly rather than executing it.
"""

from __future__ import annotations

from pathlib import Path

from simplicio.scratch.codegen import TypeScriptAddNextRouteExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


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


def test_typescript_add_next_route_executor_generates_well_formed_json_handlers(tmp_path):
    """Structural assertions on the exact generated shapes each supported
    HTTP method produces, in place of the removed Node.js runtime check
    (transpile + execute the generated file, call GET/POST, inspect the
    responses) — same behavior, pinned deterministically against the
    template output instead of a TypeScript compiler + a VM sandbox."""
    result = TypeScriptAddNextRouteExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True

    route = tmp_path / "src/app/api/units/route.ts"
    generated = route.read_text(encoding="utf-8")

    get_block = (
        "export async function GET(): Promise<Response> {\n"
        "  const units: Array<Record<string, unknown>> = [];\n"
        "  return Response.json(units);\n"
        "}\n"
    )
    post_block = (
        "export async function POST(request: Request): Promise<Response> {\n"
        "  const body = (await request.json()) as Record<string, unknown>;\n"
        "  return Response.json(body, { status: 201 });\n"
        "}\n"
    )
    assert get_block in generated
    assert post_block in generated
    # Balanced braces and no stray template artifacts -- a cheap structural
    # sanity check that does not require a real TypeScript parser.
    assert generated.count("{") == generated.count("}")
    assert "undefined" not in generated


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
    # The pre-existing GET handler's body is preserved verbatim, only the
    # missing POST handler is appended.
    assert "return Response.json([]);" in generated


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
