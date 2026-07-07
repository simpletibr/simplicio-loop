"""Tests for deterministic Pydantic schema scratch codegen."""

from __future__ import annotations

import ast
from pathlib import Path

from simplicio.scratch.codegen import PythonAddPydanticSchemaExecutor
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
    goal: str = "Create Pydantic schemas for User create, update, and read flows.",
) -> Task:
    return Task(
        id="T02-api-schemas",
        goal=goal,
        target="src/api/schemas/user.py",
        criteria=(
            "- UserCreate, UserUpdate, and UserRead schemas exist\n- optional update fields are supported"
        ),
        constraints="- keep schemas framework-agnostic",
        verify="pytest tests/api/test_users.py -q",
    )


def _write_model(tmp_path: Path, content: str, name: str = "user.py") -> Path:
    path = tmp_path / f"src/db/{name}"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_python_add_pydantic_schema_derives_crud_schemas_from_model(tmp_path):
    _write_model(
        tmp_path,
        """from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
""",
    )

    executor = PythonAddPydanticSchemaExecutor()
    result = executor.execute(_task(), tmp_path, _stack(tmp_path))

    schema_path = tmp_path / "src/api/schemas/user.py"
    assert result.passed is True
    assert result.fallback_to_llm is False
    assert result.files_modified == [schema_path]

    generated = schema_path.read_text(encoding="utf-8")
    ast.parse(generated)
    assert "from __future__ import annotations" in generated
    assert "from datetime import datetime" in generated
    assert "from pydantic import BaseModel, ConfigDict" in generated
    assert "class UserCreate(BaseModel):\n    name: str\n    email: str | None = None" in generated
    assert (
        "class UserUpdate(BaseModel):\n    name: str | None = None\n    email: str | None = None"
    ) in generated
    assert (
        "class UserRead(BaseModel):\n"
        "    model_config = ConfigDict(from_attributes=True)\n\n"
        "    id: int\n"
        "    name: str\n"
        "    email: str | None\n"
        "    created_at: datetime"
    ) in generated


def test_python_add_pydantic_schema_appends_missing_classes(tmp_path):
    _write_model(
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
    schema_path = tmp_path / "src/api/schemas/user.py"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(
        """from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
""",
        encoding="utf-8",
    )

    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))

    assert result.passed is True
    updated = schema_path.read_text(encoding="utf-8")
    ast.parse(updated)
    assert "from pydantic import BaseModel, ConfigDict" in updated
    assert updated.count("class UserCreate(BaseModel):") == 1
    assert "class UserUpdate(BaseModel):" in updated
    assert "class UserRead(BaseModel):" in updated


def test_python_add_pydantic_schema_falls_back_when_model_is_missing(tmp_path):
    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))

    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported Pydantic schema task shape" in result.log
    assert not (tmp_path / "src/api/schemas/user.py").exists()


def test_default_registry_includes_python_add_pydantic_schema_executor():
    assert any(
        isinstance(executor, PythonAddPydanticSchemaExecutor)
        for executor in codegen_registry.registered_executors()
    )
