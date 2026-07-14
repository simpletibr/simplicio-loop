"""Additional unit coverage for simplicio/scratch/codegen/python_pytest.py."""

from __future__ import annotations

import ast
from pathlib import Path

from simplicio.scratch.codegen import python_pytest as pt
from simplicio.scratch.codegen import PythonAddPytestTestExecutor
from simplicio.scratch.plan_schema import Task
from simplicio.scratch.stack_registry import Stack


def _stack(tmp_path: Path, slug: str = "py-fastapi", language: str = "Python") -> Stack:
    return Stack(slug=slug, path=tmp_path, meta={"language": language, "framework": "FastAPI"})


def _task(**overrides) -> Task:
    defaults = dict(
        id="T02-pytest",
        goal="Generate a happy-path pytest for function double in src/utils/math_ops.py",
        target="tests/unit/test_math_ops.py",
        criteria="- imports the function under test",
        constraints="- use pytest",
        verify="pytest tests/unit/test_math_ops.py -q",
    )
    defaults.update(overrides)
    return Task(**defaults)


# ---------------------------------------------------------------------------
# can_handle branches
# ---------------------------------------------------------------------------


def test_can_handle_rejects_non_python_stack(tmp_path):
    executor = PythonAddPytestTestExecutor()
    assert executor.can_handle(_task(), _stack(tmp_path, slug="ts-nextjs", language="TypeScript")) is False


def test_can_handle_rejects_non_py_target(tmp_path):
    executor = PythonAddPytestTestExecutor()
    task = _task(target="tests/unit/test_math_ops.rs")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_rejects_non_tests_dir(tmp_path):
    executor = PythonAddPytestTestExecutor()
    task = _task(target="src/utils/math_ops.py")
    assert executor.can_handle(task, _stack(tmp_path)) is False


def test_can_handle_accepts_test_prefixed_filename_without_pytest_keyword(tmp_path):
    executor = PythonAddPytestTestExecutor()
    task = _task(
        target="tests/unit/test_math_ops.py",
        goal="cover the double function",
        criteria="",
        constraints="",
    )
    assert executor.can_handle(task, _stack(tmp_path)) is True


# ---------------------------------------------------------------------------
# execute: target-not-a-file / cannot resolve / cannot synthesize args
# ---------------------------------------------------------------------------


def test_execute_falls_back_when_target_is_a_directory(tmp_path):
    target_dir = tmp_path / "tests/unit/test_math_ops.py"
    target_dir.mkdir(parents=True)

    result = PythonAddPytestTestExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "not a file" in result.log


def test_execute_falls_back_when_call_args_cannot_be_synthesized(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8"
    )
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text("def double(value) -> int:\n    return value * 2\n", encoding="utf-8")

    result = PythonAddPytestTestExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "could not synthesize happy-path arguments" in result.log


def test_execute_test_already_exists_is_noop(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8"
    )
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text("def double(value: int) -> int:\n    return value * 2\n", encoding="utf-8")

    test_path = tmp_path / "tests/unit/test_math_ops.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_double_happy_path() -> None:\n    assert True\n", encoding="utf-8"
    )
    original = test_path.read_text(encoding="utf-8")

    result = PythonAddPytestTestExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True
    assert result.files_modified == []
    assert "already exists" in result.log
    assert test_path.read_text(encoding="utf-8") == original


def test_execute_falls_back_on_existing_test_syntax_error(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8"
    )
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text("def double(value: int) -> int:\n    return value * 2\n", encoding="utf-8")

    test_path = tmp_path / "tests/unit/test_math_ops.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text("def broken(:\n", encoding="utf-8")

    result = PythonAddPytestTestExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is False
    assert "not valid Python" in result.log


def test_execute_auto_detects_single_top_level_function(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8"
    )
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text("def triple(value: int) -> int:\n    return value * 3\n", encoding="utf-8")

    task = _task(
        goal="Generate a happy-path pytest, source at src/utils/math_ops.py",
        criteria="",
        constraints="",
    )
    result = PythonAddPytestTestExecutor().execute(task, tmp_path, _stack(tmp_path))
    assert result.passed is True
    generated = (tmp_path / "tests/unit/test_math_ops.py").read_text(encoding="utf-8")
    assert "triple" in generated


def test_execute_async_function_generates_asyncio_run(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n', encoding="utf-8"
    )
    source = tmp_path / "src/utils/math_ops.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "async def double(value: int) -> int:\n    return value * 2\n", encoding="utf-8"
    )

    result = PythonAddPytestTestExecutor().execute(_task(), tmp_path, _stack(tmp_path))
    assert result.passed is True
    generated = (tmp_path / "tests/unit/test_math_ops.py").read_text(encoding="utf-8")
    assert "import asyncio" in generated
    assert "asyncio.run(double(1))" in generated


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def test_pascal_case_test_prefixed_pluralized():
    assert pt._pascal_case("test_categories") == "Category"


def test_pascal_case_all_underscores_returns_none():
    assert pt._pascal_case("___") is None


def test_snake_case_converts_camel():
    assert pt._snake_case("CondoUnit") == "condo_unit"


def test_parse_prefix_from_target_strips_test_prefix():
    assert pt._parse_prefix_from_target("tests/api/test_apps.py") == "/apps"


def test_parse_model_name_from_crud_router_phrase():
    assert pt._parse_model_name("Cover the App CRUD router with tests") == "App"


def test_parse_model_name_no_match_returns_none():
    assert pt._parse_model_name("nothing relevant") is None


def test_function_name_from_text_various_patterns():
    assert pt._function_name_from_text("function double()") == "double"
    assert pt._function_name_from_text("target triple") == "triple"
    assert pt._function_name_from_text("for quadruple(") == "quadruple"
    assert pt._function_name_from_text("test half") == "half"
    assert pt._function_name_from_text("`fifth` function") == "fifth"
    assert pt._function_name_from_text("no hints here") is None


def test_pytest_pythonpath_missing_pyproject(tmp_path):
    assert pt._pytest_pythonpath(tmp_path) == []


def test_pytest_pythonpath_missing_key(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nkey = 1\n", encoding="utf-8")
    assert pt._pytest_pythonpath(tmp_path) == []


def test_pytest_pythonpath_string_value(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = "src"\n', encoding="utf-8"
    )
    assert pt._pytest_pythonpath(tmp_path) == ["src"]


def test_pytest_pythonpath_invalid_literal(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = not_valid_python(\n", encoding="utf-8"
    )
    assert pt._pytest_pythonpath(tmp_path) == []


def test_pytest_pythonpath_non_list_non_str_returns_empty(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = 42\n", encoding="utf-8"
    )
    assert pt._pytest_pythonpath(tmp_path) == []


def test_literal_for_arg_annotation_branches():
    def _arg(annotation_src):
        node = ast.parse(f"def f(x: {annotation_src}): pass").body[0]
        return node.args.args[0]

    assert pt._literal_for_arg(_arg("str")) == '"sample"'
    assert pt._literal_for_arg(_arg("int")) == "1"
    assert pt._literal_for_arg(_arg("float")) == "1.0"
    assert pt._literal_for_arg(_arg("bool")) == "True"
    assert pt._literal_for_arg(_arg("list")) == "[]"
    assert pt._literal_for_arg(_arg("dict")) == "{}"
    assert pt._literal_for_arg(_arg("set")) == "set()"
    assert pt._literal_for_arg(_arg("tuple")) == "()"


def test_literal_for_arg_name_heuristics():
    def _arg(name):
        node = ast.parse(f"def f({name}): pass").body[0]
        return node.args.args[0]

    assert pt._literal_for_arg(_arg("email")) == '"sample"'
    assert pt._literal_for_arg(_arg("count")) == "1"
    assert pt._literal_for_arg(_arg("user_id")) == "1"
    assert pt._literal_for_arg(_arg("id")) == "1"
    assert pt._literal_for_arg(_arg("items")) == "[]"
    assert pt._literal_for_arg(_arg("payload")) == "{}"
    assert pt._literal_for_arg(_arg("is_active")) == "True"
    assert pt._literal_for_arg(_arg("enabled")) == "True"
    assert pt._literal_for_arg(_arg("mystery_thing")) is None


def test_assertion_branches():
    def _fn(src):
        return ast.parse(src).body[0]

    assert pt._assertion(_fn("def f() -> None: pass")) == "assert result is None"
    assert pt._assertion(_fn("def f() -> bool: pass")) == "assert isinstance(result, bool)"
    assert pt._assertion(_fn("def f() -> str: pass")) == "assert isinstance(result, str)"
    assert pt._assertion(_fn("def f() -> int: pass")) == "assert isinstance(result, int)"
    assert pt._assertion(_fn("def f() -> float: pass")) == "assert isinstance(result, float)"
    assert pt._assertion(_fn("def f() -> list: pass")) == "assert isinstance(result, list)"
    assert pt._assertion(_fn("def f() -> dict: pass")) == "assert isinstance(result, dict)"
    assert (
        pt._assertion(_fn("def f():\n    return\n")) == "assert result is None"
    )
    assert (
        pt._assertion(_fn("def f():\n    return compute()\n")) == "assert result is not None"
    )


def test_has_value_return_ignores_bare_none():
    node = ast.parse("def f():\n    return None\n").body[0]
    assert pt._has_value_return(node) is False


def test_append_test_empty_original_returns_rendered():
    assert pt._append_test("", "rendered") == "rendered"


def test_append_test_with_trailing_newline():
    result = pt._append_test("existing\n", "rendered")
    assert result == "existing\n\n\nrendered"


def test_annotation_text_none_returns_empty():
    assert pt._annotation_text(None) == ""


def test_module_name_no_matching_root_returns_none(tmp_path):
    outside = tmp_path.parent / "outside.py"
    assert pt._module_name(outside, tmp_path) is None
