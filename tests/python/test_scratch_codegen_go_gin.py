"""Tests for deterministic Go Gin scratch codegen."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio.scratch.codegen import GoGinCrudExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack

_PORTABLE_GO = Path.home() / "Pictures" / "m" / "tmp" / "go-portable" / "extract" / "go" / "bin" / "go.exe"


def _go_binary() -> str | None:
    return shutil.which("go") or (str(_PORTABLE_GO) if _PORTABLE_GO.is_file() else None)


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="go-gin",
        path=tmp_path,
        meta={"language": "Go", "framework": "Gin"},
    )


def _task() -> Task:
    return Task(
        id="T01-gin-crud",
        goal="Implement Gin CRUD routes for CondoUnits.",
        target="internal/http/router.go",
        criteria=(
            "- list, create, and read routes are present\n"
            "- route prefix is /condo_units\n"
            "- router stays compatible with the health route test"
        ),
        constraints="- keep the service self-contained and typed",
        verify="go test ./...",
    )


def test_go_gin_crud_executor_generates_routes(tmp_path):
    executor = GoGinCrudExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    router = tmp_path / "internal/http/router.go"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [router]
    generated = router.read_text(encoding="utf-8")
    assert "simplicio generated go-gin CRUD" in generated
    assert 'router.GET("/condo_units", ListCondoUnits)' in generated
    assert 'router.POST("/condo_units", CreateCondoUnit)' in generated
    assert "type CondoUnit struct" in generated


def test_go_gin_crud_executor_is_idempotent(tmp_path):
    executor = GoGinCrudExecutor()
    first = executor.execute(_task(), tmp_path, _stack(tmp_path))
    second = executor.execute(_task(), tmp_path, _stack(tmp_path))

    assert first.passed is True
    assert second.passed is True
    assert second.files_modified == []
    assert "already has generated Gin CRUD routes" in second.log


def test_go_gin_crud_executor_falls_back_for_non_router_target(tmp_path):
    result = GoGinCrudExecutor().execute(
        Task(
            id="T01-gin-crud",
            goal="Implement Gin CRUD routes for Unit.",
            target="cmd/server/main.go",
            criteria="- route prefix is /units",
            constraints="",
            verify="go test ./...",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported go-gin CRUD task shape" in result.log


def test_default_registry_includes_go_gin_crud_executor():
    assert any(
        isinstance(executor, GoGinCrudExecutor) for executor in codegen_registry.registered_executors()
    )


def test_go_gin_generated_router_passes_go_test(tmp_path):
    go = _go_binary()
    if go is None:
        pytest.skip("go not available")

    project = tmp_path / "project"
    project.mkdir()
    (project / "go.mod").write_text(
        """module go-gin-codegen-test

go 1.22

require github.com/gin-gonic/gin v1.10.0
""",
        encoding="utf-8",
    )
    test_path = project / "internal/http/router_test.go"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        """package http

import (
\t"net/http"
\t"net/http/httptest"
\t"testing"
)

func TestHealth(t *testing.T) {
\trouter := NewRouter()
\tresponse := httptest.NewRecorder()
\trequest, err := http.NewRequest(http.MethodGet, "/health", nil)
\tif err != nil {
\t\tt.Fatal(err)
\t}

\trouter.ServeHTTP(response, request)

\tif response.Code != http.StatusOK {
\t\tt.Fatalf("expected 200, got %d", response.Code)
\t}
}
""",
        encoding="utf-8",
    )

    result = GoGinCrudExecutor().execute(_task(), project, _stack(tmp_path))

    assert result.passed is True
    env = os.environ.copy()
    env["PATH"] = str(Path(go).parent) + os.pathsep + env.get("PATH", "")
    tidy = subprocess.run(
        [go, "mod", "tidy"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert tidy.returncode == 0, tidy.stdout + tidy.stderr
    proc = subprocess.run(
        [go, "test", "./..."],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
