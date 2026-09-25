"""Tests for deterministic Rust Axum scratch codegen."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio.scratch.codegen import RustAxumCrudExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="rust-axum",
        path=tmp_path,
        meta={"language": "Rust", "framework": "Axum"},
    )


def _task() -> Task:
    return Task(
        id="T01-axum-crud",
        goal="Implement Axum CRUD routes for CondoUnits.",
        target="src/main.rs",
        criteria=(
            "- list and create routes are present\n"
            "- route prefix is /condo_units\n"
            "- route tests cover health and CRUD status"
        ),
        constraints="- keep the service self-contained and typed",
        verify="cargo test",
    )


def test_rust_axum_crud_executor_generates_routes_and_tests(tmp_path):
    executor = RustAxumCrudExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    main_rs = tmp_path / "src/main.rs"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [main_rs]
    generated = main_rs.read_text(encoding="utf-8")
    assert "simplicio generated rust-axum CRUD" in generated
    assert 'route("/condo_units", get(list_condo_units).post(create_condo_unit))' in generated
    assert "struct CondoUnit" in generated
    assert "async fn condo_units_crud_routes_work()" in generated


def test_rust_axum_crud_executor_is_idempotent(tmp_path):
    executor = RustAxumCrudExecutor()
    first = executor.execute(_task(), tmp_path, _stack(tmp_path))
    second = executor.execute(_task(), tmp_path, _stack(tmp_path))

    assert first.passed is True
    assert second.passed is True
    assert second.files_modified == []
    assert "already has generated Axum CRUD routes" in second.log


def test_rust_axum_crud_executor_falls_back_for_non_main_target(tmp_path):
    result = RustAxumCrudExecutor().execute(
        Task(
            id="T01-axum-crud",
            goal="Implement Axum CRUD routes for Unit.",
            target="src/lib.rs",
            criteria="- route prefix is /units",
            constraints="",
            verify="cargo test",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported rust-axum CRUD task shape" in result.log


def test_default_registry_includes_rust_axum_crud_executor():
    assert any(
        isinstance(executor, RustAxumCrudExecutor) for executor in codegen_registry.registered_executors()
    )


def test_rust_axum_generated_project_passes_cargo_test(tmp_path):
    cargo = shutil.which("cargo")
    if cargo is None:
        pytest.skip("cargo not available")
    if shutil.which("rustc"):
        rustc = subprocess.run(
            ["rustc", "-vV"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if "host:" in rustc.stdout and "-msvc" in rustc.stdout and not shutil.which("link.exe"):
            pytest.skip("MSVC Rust target needs link.exe")

    project = tmp_path / "project"
    project.mkdir()
    (project / "Cargo.toml").write_text(
        """[package]
name = "rust-axum-codegen-test"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.8"
serde = { version = "1", features = ["derive"] }
tokio = { version = "1", features = ["macros", "rt-multi-thread"] }

[dev-dependencies]
tower = { version = "0.5", features = ["util"] }
""",
        encoding="utf-8",
    )

    result = RustAxumCrudExecutor().execute(_task(), project, _stack(tmp_path))

    assert result.passed is True
    proc = subprocess.run(
        [cargo, "test", "--manifest-path", str(project / "Cargo.toml")],
        capture_output=True,
        text=True,
        timeout=300,  # fresh cargo compile under parallel-suite CPU contention can exceed 180s
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
