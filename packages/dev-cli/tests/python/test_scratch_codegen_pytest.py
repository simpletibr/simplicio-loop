"""Tests for deterministic pytest scratch codegen."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from simplicio.scratch.codegen import PythonAddPytestTestExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="py-fastapi",
        path=tmp_path,
        meta={"language": "Python", "framework": "FastAPI"},
    )


def _task(
    goal: str = ("Generate a happy-path pytest for function double in src/utils/math_ops.py"),
) -> Task:
    return Task(
        id="T02-pytest",
        goal=goal,
        target="tests/unit/test_math_ops.py",
        criteria="- imports the function under test\n- has a sane assert",
        constraints="- use pytest",
        verify="pytest tests/unit/test_math_ops.py -q",
    )


def _write_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """[tool.pytest.ini_options]
pythonpath = ["src"]
""",
        encoding="utf-8",
    )


def _write_source(tmp_path: Path) -> Path:
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        """def double(value: int) -> int:
    return value * 2
""",
        encoding="utf-8",
    )
    return source


def test_python_add_pytest_test_generates_runnable_happy_path(tmp_path):
    _write_pyproject(tmp_path)
    _write_source(tmp_path)

    executor = PythonAddPytestTestExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    test_path = tmp_path / "tests/unit/test_math_ops.py"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [test_path]

    generated = test_path.read_text(encoding="utf-8")
    ast.parse(generated)
    assert "from utils.math_ops import double" in generated
    assert "def test_double_happy_path() -> None:" in generated
    assert "result = double(1)" in generated
    assert "assert isinstance(result, int)" in generated

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/unit/test_math_ops.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_python_add_pytest_test_generates_recipe_crud_flow(tmp_path):
    result = PythonAddPytestTestExecutor().execute(
        Task(
            id="T04-api-tests",
            goal="Cover the App CRUD router with route tests.",
            target="tests/api/test_apps.py",
            criteria="- create/list/read/update/delete paths are tested\n- missing app returns 404",
            constraints="- use FastAPI TestClient",
            verify="pytest tests/api/test_apps.py -q",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    test_path = tmp_path / "tests/api/test_apps.py"
    assert result.passed is True
    assert result.fallback_to_llm is False
    generated = test_path.read_text(encoding="utf-8")
    ast.parse(generated)
    assert "def test_app_crud_flow() -> None:" in generated
    assert 'client.post("/apps", json={"name": "Demo"})' in generated
    assert 'missing = client.get(f"/apps/{item_id}")' in generated


def test_python_add_pytest_test_falls_back_when_function_cannot_be_resolved(tmp_path):
    _write_pyproject(tmp_path)

    result = PythonAddPytestTestExecutor().execute(
        _task("Generate a happy-path pytest for function missing in src/missing.py"),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "could not resolve" in result.log
    assert not (tmp_path / "tests/unit/test_math_ops.py").exists()


def test_default_registry_includes_python_add_pytest_test_executor():
    assert any(
        isinstance(executor, PythonAddPytestTestExecutor)
        for executor in codegen_registry.registered_executors()
    )
