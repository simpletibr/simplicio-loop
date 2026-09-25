"""Tests for deterministic Next.js page scratch codegen."""

from __future__ import annotations

from pathlib import Path

from simplicio.scratch.codegen import TypeScriptAddNextPageExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="ts-nextjs",
        path=tmp_path,
        meta={"language": "TypeScript 5", "framework": "Next.js 14 (app router)"},
    )


def _task(goal: str = "Create a Condo Unit CRUD page") -> Task:
    return Task(
        id="T02-page",
        goal=goal,
        target="src/app/condo_units/page.tsx",
        criteria="- page fetches condo_units\n- create form is rendered",
        constraints="- keep component typed and accessible",
        verify="pnpm tsc --noEmit",
    )


def test_typescript_add_next_page_executor_creates_typed_crud_page(tmp_path):
    executor = TypeScriptAddNextPageExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    page = tmp_path / "src/app/condo_units/page.tsx"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [page]
    generated = page.read_text(encoding="utf-8")
    assert 'data-simplicio-crud-page="condo_units"' in generated
    assert "type CondoUnit = {" in generated
    assert "async function fetchCondoUnits(): Promise<CondoUnit[]>" in generated
    assert "export default async function CondoUnitsPage()" in generated
    assert "<form>" in generated
    assert "condoUnits.map((item)" in generated


def test_typescript_add_next_page_executor_is_idempotent(tmp_path):
    executor = TypeScriptAddNextPageExecutor()
    first = executor.execute(_task(), tmp_path, _stack(tmp_path))
    second = executor.execute(_task(), tmp_path, _stack(tmp_path))

    assert first.passed is True
    assert second.passed is True
    assert second.files_modified == []
    assert "already has a generated CRUD page" in second.log


def test_typescript_add_next_page_executor_falls_back_for_api_route(tmp_path):
    result = TypeScriptAddNextPageExecutor().execute(
        Task(
            id="T02-page",
            goal="Create a Unit CRUD page",
            target="src/app/api/units/route.ts",
            criteria="- not a page target",
            constraints="",
            verify="pnpm tsc --noEmit",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported Next.js page task shape" in result.log


def test_default_registry_includes_typescript_next_page_executor():
    assert any(
        isinstance(executor, TypeScriptAddNextPageExecutor)
        for executor in codegen_registry.registered_executors()
    )
