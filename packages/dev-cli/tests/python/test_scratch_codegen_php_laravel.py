"""Tests for deterministic Laravel scratch codegen."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio.scratch.codegen import PhpLaravelCrudRoutesExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="php-laravel",
        path=tmp_path,
        meta={"language": "PHP", "framework": "Laravel"},
    )


def _task() -> Task:
    return Task(
        id="T01-laravel-routes",
        goal="Implement Laravel JSON CRUD routes for CondoUnits.",
        target="routes/api.php",
        criteria=(
            "- list, create, and read routes are present\n"
            "- route prefix is /condo_units\n"
            "- health route stays compatible with the feature test"
        ),
        constraints="- keep the service self-contained and typed",
        verify="php vendor/bin/phpunit --configuration phpunit.xml",
    )


def test_php_laravel_crud_routes_executor_generates_routes(tmp_path):
    executor = PhpLaravelCrudRoutesExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    routes = tmp_path / "routes/api.php"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [routes]
    generated = routes.read_text(encoding="utf-8")
    assert "simplicio generated php-laravel CRUD" in generated
    assert "Route::get('/condo_units'" in generated
    assert "Route::post('/condo_units'" in generated
    assert "Route::get('/condo_units/{id}'" in generated


def test_php_laravel_crud_routes_executor_is_idempotent(tmp_path):
    executor = PhpLaravelCrudRoutesExecutor()
    first = executor.execute(_task(), tmp_path, _stack(tmp_path))
    second = executor.execute(_task(), tmp_path, _stack(tmp_path))

    assert first.passed is True
    assert second.passed is True
    assert second.files_modified == []
    assert "already has generated Laravel CRUD routes" in second.log


def test_php_laravel_crud_routes_executor_falls_back_for_non_routes_target(tmp_path):
    result = PhpLaravelCrudRoutesExecutor().execute(
        Task(
            id="T01-laravel-routes",
            goal="Implement Laravel JSON CRUD routes for Unit.",
            target="app/Models/Unit.php",
            criteria="- route prefix is /units",
            constraints="",
            verify="php vendor/bin/phpunit --configuration phpunit.xml",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported php-laravel CRUD task shape" in result.log


def test_default_registry_includes_php_laravel_crud_routes_executor():
    assert any(
        isinstance(executor, PhpLaravelCrudRoutesExecutor)
        for executor in codegen_registry.registered_executors()
    )


def test_php_laravel_generated_routes_pass_php_lint(tmp_path):
    php = shutil.which("php")
    if php is None:
        pytest.skip("php not available")

    result = PhpLaravelCrudRoutesExecutor().execute(_task(), tmp_path, _stack(tmp_path))

    assert result.passed is True
    proc = subprocess.run(
        [php, "-l", str(tmp_path / "routes/api.php")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
