"""Tests for deterministic SQLAlchemy ORM scratch codegen."""

from __future__ import annotations

import ast
from pathlib import Path

from simplicio.scratch.codegen import PythonAddOrmFieldExecutor
from simplicio.scratch.codegen import registry as codegen_registry
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path) -> Stack:
    return Stack(
        slug="py-fastapi",
        path=tmp_path,
        meta={"language": "Python", "framework": "FastAPI"},
    )


def _task(goal: str = "Add email: Mapped[str] field to User model") -> Task:
    return Task(
        id="T01-db-model",
        goal=goal,
        target="src/db/models.py",
        criteria="- User has email: Mapped[str]",
        constraints="- use SQLAlchemy 2.0 declarative style",
        verify="pytest tests/db/test_models.py -q",
    )


def _write_models(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "src/db/models.py"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_python_add_orm_field_adds_email_to_sqlalchemy_model(tmp_path):
    models_path = _write_models(
        tmp_path,
        """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
""",
    )

    executor = PythonAddOrmFieldExecutor()
    task = _task()
    result = executor.execute(task, tmp_path, _stack(tmp_path))

    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [models_path]
    updated = models_path.read_text(encoding="utf-8")
    ast.parse(updated)
    assert "    name: Mapped[str]\n    email: Mapped[str]\n" in updated
    assert "from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column" in updated


def test_python_add_orm_field_creates_recipe_model_file(tmp_path):
    target = tmp_path / "src/db/app.py"

    result = PythonAddOrmFieldExecutor().execute(
        Task(
            id="T01-db-model",
            goal="Define the App SQLAlchemy model.",
            target="src/db/app.py",
            criteria="- App class exists with id, name, and created_at fields\n- table name is apps",
            constraints="- use SQLAlchemy 2.0 declarative style",
            verify="pytest tests/db/test_app.py -q",
        ),
        tmp_path,
        _stack(tmp_path),
    )

    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [target]
    generated = target.read_text(encoding="utf-8")
    ast.parse(generated)
    assert "class App(Base):" in generated
    assert '__tablename__ = "apps"' in generated
    assert "id: Mapped[int] = mapped_column(primary_key=True)" in generated
    assert "name: Mapped[str]" in generated
    assert "created_at: Mapped[datetime]" in generated


def test_python_add_orm_field_falls_back_when_model_shape_is_unsupported(tmp_path):
    models_path = _write_models(
        tmp_path,
        """class User:
    pass
""",
    )
    original = models_path.read_text(encoding="utf-8")

    result = PythonAddOrmFieldExecutor().execute(_task(), tmp_path, _stack(tmp_path))

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "not a SQLAlchemy model" in result.log
    assert models_path.read_text(encoding="utf-8") == original


def test_default_registry_includes_python_add_orm_field_executor():
    assert any(
        isinstance(executor, PythonAddOrmFieldExecutor)
        for executor in codegen_registry.registered_executors()
    )
