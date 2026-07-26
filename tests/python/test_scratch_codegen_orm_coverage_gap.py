"""Additional unit coverage for simplicio/scratch/codegen/python_orm.py."""

from __future__ import annotations

from pathlib import Path

from simplicio.scratch.codegen import PythonAddOrmFieldExecutor
from simplicio.scratch.codegen import python_orm as orm
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path, slug: str = "py-fastapi", language: str = "Python") -> Stack:
    return Stack(slug=slug, path=tmp_path, meta={"language": language, "framework": "FastAPI"})


def _task(**overrides) -> Task:
    defaults = dict(
        id="T01-db-model",
        goal="Add email: Mapped[str] field to User model",
        target="src/db/models.py",
        criteria="- User has email: Mapped[str]",
        constraints="- use SQLAlchemy 2.0 declarative style",
        verify="pytest tests/db/test_models.py -q",
    )
    defaults.update(overrides)
    return Task(**defaults)


# ---------------------------------------------------------------------------
# can_handle branches
# ---------------------------------------------------------------------------


def test_can_handle_rejects_non_python_stack(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    stack = _stack(tmp_path, slug="ts-nextjs", language="TypeScript")
    assert executor.can_handle(_task(), stack) is False


def test_can_handle_rejects_non_py_target(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    task = _task(target="src/db/models.rs")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_rejects_target_without_model_or_db_dir(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    task = _task(target="src/other/thing.py")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_accepts_model_stem(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    task = _task(target="src/anything/user_model.py")
    assert executor.can_handle(task, _stack(tmp_path)) is True


def test_can_handle_rejects_without_field_or_column_keyword(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    task = _task(goal="Refactor the User model", criteria="- cleanup", constraints="")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_rejects_without_model_orm_keyword(tmp_path):
    executor = PythonAddOrmFieldExecutor()
    task = _task(goal="Add a field somewhere", criteria="- add column", constraints="")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_is_python_stack_by_slug_prefix(tmp_path):
    stack = Stack(slug="py-custom", path=tmp_path, meta={"language": "?"})
    assert orm._is_python_stack(stack) is True


# ---------------------------------------------------------------------------
# execute: target file missing / bad syntax
# ---------------------------------------------------------------------------


def test_execute_falls_back_when_field_spec_unparseable(tmp_path):
    result = PythonAddOrmFieldExecutor().execute(
        _task(goal="do something vague", criteria="", constraints=""),
        tmp_path,
        _stack(tmp_path),
    )
    assert result.passed is False
    assert result.fallback_to_llm is True
    assert "unsupported ORM field task shape" in result.log


def test_execute_falls_back_when_target_file_missing(tmp_path):
    task = _task(
        goal="email: Mapped[str] for class User",
        criteria="",
        constraints="",
    )
    result = PythonAddOrmFieldExecutor().execute(task, tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "target file not found" in result.log


def test_execute_falls_back_on_syntax_error(tmp_path):
    target = tmp_path / "src/db/models.py"
    target.parent.mkdir(parents=True)
    target.write_text("class User(:\n", encoding="utf-8")

    result = PythonAddOrmFieldExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "not valid Python" in result.log


def test_execute_falls_back_when_model_class_not_found(tmp_path):
    target = tmp_path / "src/db/models.py"
    target.parent.mkdir(parents=True)
    target.write_text("class Other:\n    pass\n", encoding="utf-8")

    result = PythonAddOrmFieldExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "could not find SQLAlchemy model class" in result.log


def test_execute_field_already_exists_is_noop(tmp_path):
    target = tmp_path / "src/db/models.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str]
""",
        encoding="utf-8",
    )
    original = target.read_text(encoding="utf-8")

    result = PythonAddOrmFieldExecutor().execute(_task(), tmp_path, _stack(tmp_path))

    assert result.passed is True
    assert result.files_modified == []
    assert "already exists" in result.log
    assert target.read_text(encoding="utf-8") == original


def test_execute_detects_model_via_ann_assign_tablename(tmp_path):
    node_text = """from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class User:
    __tablename__: str = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
"""
    target = tmp_path / "src/db/models.py"
    target.parent.mkdir(parents=True)
    target.write_text(node_text, encoding="utf-8")

    result = PythonAddOrmFieldExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True
    assert "email" in result.log


# ---------------------------------------------------------------------------
# _parse_field / type inference branches
# ---------------------------------------------------------------------------


def test_parse_field_explicit_mapped_annotation():
    field, mapped = orm._parse_field("age: Mapped[int]")
    assert field == "age"
    assert mapped == "int"


def test_parse_field_boolean_keyword():
    field, mapped = orm._parse_field("add the active field, boolean value")
    assert field == "active"
    assert mapped == "bool"


def test_parse_field_no_match_returns_none_none():
    field, mapped = orm._parse_field("nothing relevant here")
    assert field is None
    assert mapped is None


def test_parse_field_name_found_but_no_type_hint():
    field, mapped = orm._parse_field("add the mystery field")
    assert field is None
    assert mapped is None


# ---------------------------------------------------------------------------
# _parse_model_fields / _parse_table_name / _pascal_case / _snake_case
# ---------------------------------------------------------------------------


def test_parse_model_fields_explicit_with_and():
    fields = orm._parse_model_fields("with id, name and created_at fields")
    assert fields == ["id", "name", "created_at"]


def test_parse_model_fields_falls_back_to_known_defaults():
    fields = orm._parse_model_fields("just create a model")
    assert fields == ["id", "name"]


def test_parse_model_fields_detects_known_words_in_free_text():
    fields = orm._parse_model_fields("model has updated_at and name tracked")
    assert "updated_at" in fields
    assert "name" in fields


def test_parse_table_name_explicit():
    assert orm._parse_table_name("table name is `condo_units`") == "condo_units"


def test_parse_table_name_missing_returns_none():
    assert orm._parse_table_name("no table info here") is None


def test_pascal_case_pluralized_ies():
    assert orm._pascal_case("categories") == "Category"


def test_pascal_case_pluralized_s():
    assert orm._pascal_case("apps") == "App"


def test_pascal_case_empty_returns_none():
    assert orm._pascal_case("___") is None


def test_snake_case_converts_camel():
    assert orm._snake_case("CondoUnit") == "condo_unit"


# ---------------------------------------------------------------------------
# _create_model_file field-line branches
# ---------------------------------------------------------------------------


def test_create_model_file_covers_all_field_kinds(tmp_path):
    spec = orm._ModelSpec(
        model_name="Invoice",
        table_name="invoices",
        fields=("id", "customer_id", "created_at", "updated_at", "amount", "description"),
    )
    target = tmp_path / "src/db/invoice.py"
    result = orm._create_model_file(target, spec)

    assert result.passed is True
    content = target.read_text(encoding="utf-8")
    assert "id: Mapped[int] = mapped_column(primary_key=True)" in content
    assert "customer_id: Mapped[int]" in content
    assert "created_at: Mapped[datetime]" in content
    assert "updated_at: Mapped[datetime | None]" in content
    assert "amount: Mapped[float]" in content
    assert "description: Mapped[str]" in content
