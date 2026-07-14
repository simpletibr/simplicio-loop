"""Additional unit coverage for simplicio/scratch/codegen/python_pydantic.py."""

from __future__ import annotations

import ast
from pathlib import Path

from simplicio.scratch.codegen import python_pydantic as pd
from simplicio.scratch.codegen import PythonAddPydanticSchemaExecutor
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path, slug: str = "py-fastapi", language: str = "Python", framework: str = "FastAPI") -> Stack:
    return Stack(slug=slug, path=tmp_path, meta={"language": language, "framework": framework})


def _task(**overrides) -> Task:
    defaults = dict(
        id="T02-api-schemas",
        goal="Create Pydantic schemas for User create, update, and read flows.",
        target="src/api/schemas/user.py",
        criteria="- UserCreate, UserUpdate, and UserRead schemas exist",
        constraints="- keep schemas framework-agnostic",
        verify="pytest tests/api/test_users.py -q",
    )
    defaults.update(overrides)
    return Task(**defaults)


def _write_model(tmp_path: Path, content: str, name: str = "user.py") -> Path:
    path = tmp_path / f"src/db/{name}"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    return path


BASIC_MODEL = """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
"""


# ---------------------------------------------------------------------------
# can_handle branches
# ---------------------------------------------------------------------------


def test_can_handle_rejects_non_fastapi_non_py_stack(tmp_path):
    executor = PythonAddPydanticSchemaExecutor()
    stack = _stack(tmp_path, slug="ts-nextjs", language="TypeScript", framework="Next.js")
    assert executor.can_handle(_task(), stack) is False


def test_can_handle_rejects_non_py_target(tmp_path):
    executor = PythonAddPydanticSchemaExecutor()
    task = _task(target="src/api/schemas/user.rs")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_rejects_without_schema_dir_or_stem(tmp_path):
    executor = PythonAddPydanticSchemaExecutor()
    task = _task(target="src/api/other/user.py")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_accepts_schema_stem_without_dir(tmp_path):
    executor = PythonAddPydanticSchemaExecutor()
    task = _task(target="src/other/user_schema.py")
    assert executor.can_handle(task, _stack(tmp_path)) is True


def test_can_handle_rejects_without_pydantic_or_schema_keyword(tmp_path):
    executor = PythonAddPydanticSchemaExecutor()
    task = _task(goal="Do something with User", criteria="", constraints="")
    assert executor.can_handle(task, _stack(tmp_path)) is False


# ---------------------------------------------------------------------------
# execute() branches
# ---------------------------------------------------------------------------


def test_execute_falls_back_when_target_is_a_directory(tmp_path):
    _write_model(tmp_path, BASIC_MODEL)
    target_dir = tmp_path / "src/api/schemas/user.py"
    target_dir.mkdir(parents=True)

    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "not a file" in result.log


def test_execute_falls_back_when_no_fields_derivable(tmp_path):
    _write_model(
        tmp_path,
        'from sqlalchemy.orm import DeclarativeBase\n\n\n'
        'class Base(DeclarativeBase):\n    pass\n\n\n'
        'class User(Base):\n    __tablename__ = "users"\n',
    )
    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "could not derive fields" in result.log


def test_execute_falls_back_on_existing_target_syntax_error(tmp_path):
    _write_model(tmp_path, BASIC_MODEL)
    schema_path = tmp_path / "src/api/schemas/user.py"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text("class Broken(:\n", encoding="utf-8")

    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "not valid Python" in result.log


def test_execute_all_schemas_already_exist_is_noop(tmp_path):
    _write_model(tmp_path, BASIC_MODEL)
    schema_path = tmp_path / "src/api/schemas/user.py"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(
        "from pydantic import BaseModel\n\n\n"
        "class UserCreate(BaseModel):\n    name: str\n\n\n"
        "class UserUpdate(BaseModel):\n    name: str | None = None\n\n\n"
        "class UserRead(BaseModel):\n    id: int\n    name: str\n",
        encoding="utf-8",
    )
    original = schema_path.read_text(encoding="utf-8")

    result = PythonAddPydanticSchemaExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True
    assert result.files_modified == []
    assert "already exist" in result.log
    assert schema_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# _parse_model_name branches
# ---------------------------------------------------------------------------


def test_parse_model_name_schemas_for_phrase():
    assert pd._parse_model_name("schemas for the Invoice", "invoice.py") == "Invoice"


def test_parse_model_name_model_schemas_phrase():
    assert pd._parse_model_name("Invoice schemas needed", "invoice.py") == "Invoice"


def test_parse_model_name_for_model_phrase():
    assert pd._parse_model_name("write schemas for the Invoice model", "invoice.py") == "Invoice"


def test_parse_model_name_falls_back_to_target_stem():
    assert pd._parse_model_name("no useful hints here", "invoices.py") == "Invoice"


# ---------------------------------------------------------------------------
# _pascal_case / _snake_case edge cases
# ---------------------------------------------------------------------------


def test_pascal_case_empty_returns_none():
    assert pd._pascal_case("___") is None


def test_pascal_case_pluralized_ies():
    assert pd._pascal_case("categories") == "Category"


def test_snake_case_converts_camel():
    assert pd._snake_case("CondoUnit") == "condo_unit"


# ---------------------------------------------------------------------------
# _find_model_path / _has_sqlalchemy_model
# ---------------------------------------------------------------------------


def test_find_model_path_via_rglob(tmp_path):
    _write_model(tmp_path, BASIC_MODEL, name="nested_user.py")
    path = pd._find_model_path(tmp_path, "User", "user.py")
    assert path is not None
    assert path.name == "nested_user.py"


def test_find_model_path_missing_returns_none(tmp_path):
    assert pd._find_model_path(tmp_path, "User", "user.py") is None


def test_has_sqlalchemy_model_bad_syntax_returns_false(tmp_path):
    path = tmp_path / "bad.py"
    path.write_text("class Broken(:\n", encoding="utf-8")
    assert pd._has_sqlalchemy_model(path, "Broken") is False


# ---------------------------------------------------------------------------
# _extract_model_fields / field parsing branches
# ---------------------------------------------------------------------------


def test_extract_model_fields_skips_relationship_and_private_and_classvar(tmp_path):
    model = """from typing import ClassVar
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    _private: Mapped[str]
    posts: Mapped[list] = relationship("Post")
    some_classvar: ClassVar[int] = 3
    name: Mapped[str]
"""
    path = _write_model(tmp_path, model, name="user2.py")
    fields = pd._extract_model_fields(path, "User")
    names = {f.name for f in fields}
    assert names == {"id", "name"}


def test_extract_model_fields_bad_syntax_returns_empty(tmp_path):
    path = tmp_path / "bad2.py"
    path.write_text("class User(:\n", encoding="utf-8")
    assert pd._extract_model_fields(path, "User") == []


def test_extract_model_fields_not_sqlalchemy_model_returns_empty(tmp_path):
    path = _write_model(tmp_path, "class User:\n    pass\n", name="plain.py")
    assert pd._extract_model_fields(path, "User") == []


def test_normalize_type_optional_and_union_variants():
    assert pd._normalize_type("Optional[str]") == "str | None"
    assert pd._normalize_type("Union[str, None]") == "str | None"
    assert pd._normalize_type("Union[None, str]") == "str | None"
    assert pd._normalize_type("int") == "int"


def test_is_optional_type_variants():
    assert pd._is_optional_type("str | None") is True
    assert pd._is_optional_type("None | str") is True
    assert pd._is_optional_type("str") is False


def test_optionalize_idempotent():
    assert pd._optionalize("str | None") == "str | None"
    assert pd._optionalize("str") == "str | None"


# ---------------------------------------------------------------------------
# _needed_type_imports / _render_imports
# ---------------------------------------------------------------------------


def test_needed_type_imports_maps_known_types():
    fields = [
        pd._ModelField(name="created_at", type_text="datetime"),
        pd._ModelField(name="uid", type_text="UUID"),
        pd._ModelField(name="amount", type_text="Decimal"),
        pd._ModelField(name="d", type_text="date"),
        pd._ModelField(name="plain", type_text="str"),
    ]
    imports = pd._needed_type_imports(fields)
    assert imports["datetime"] == {"datetime", "date"}
    assert imports["uuid"] == {"UUID"}
    assert imports["decimal"] == {"Decimal"}


def test_render_imports_no_type_imports_returns_only_pydantic():
    fields = [pd._ModelField(name="name", type_text="str")]
    assert pd._render_imports(fields) == "from pydantic import BaseModel, ConfigDict"


# ---------------------------------------------------------------------------
# _ensure_from_import branches — star import + multi-line import untouched
# ---------------------------------------------------------------------------


def test_ensure_from_import_skips_when_star_import_present():
    lines = ["from pydantic import *\n"]
    tree = ast.parse("".join(lines))
    pd._ensure_from_import(lines, tree, "pydantic", ["BaseModel"], "\n")
    assert lines == ["from pydantic import *\n"]


def test_ensure_from_import_adds_missing_names_to_existing_line():
    lines = ["from pydantic import BaseModel\n"]
    tree = ast.parse("".join(lines))
    pd._ensure_from_import(lines, tree, "pydantic", ["BaseModel", "ConfigDict"], "\n")
    assert "ConfigDict" in lines[0]


def test_ensure_from_import_inserts_new_import_when_absent():
    lines = ["x = 1\n"]
    tree = ast.parse("".join(lines))
    pd._ensure_from_import(lines, tree, "pydantic", ["BaseModel"], "\n")
    assert any("from pydantic import BaseModel" in line for line in lines)


def test_detect_newline_crlf():
    assert pd._detect_newline("a\r\nb") == "\r\n"


def test_detect_newline_lf():
    assert pd._detect_newline("a\nb") == "\n"
