"""Deterministic detection of the target repo's test command (the --verify passed to turbo)."""
from __future__ import annotations

import asyncio
import json

from simplicio_loop.watcher247 import verify


def detect(path):
    return asyncio.run(verify.detect(path))


def with_tests(path):
    """A python test file: pytest only counts as a test command when there is something to collect."""
    (path / "tests").mkdir(exist_ok=True)
    (path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    return path


def test_pyproject_with_tests_gives_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    with_tests(tmp_path)
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_pyproject_without_tests_is_none(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    assert detect(tmp_path) is None


def test_pytest_ini_with_tests_gives_pytest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    with_tests(tmp_path)
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_setup_cfg_with_pytest_section_and_tests_gives_pytest(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")
    with_tests(tmp_path)
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_tox_ini_with_pytest_section_and_tests_gives_pytest(tmp_path):
    (tmp_path / "tox.ini").write_text("[pytest]\naddopts = -q\n")
    with_tests(tmp_path)
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_setup_cfg_without_pytest_section_is_none(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = a\n")
    with_tests(tmp_path)
    assert detect(tmp_path) is None


def test_test_file_named_suffix_style_counts(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "thing_test.py").write_text("def test_x():\n    pass\n")
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_hidden_or_vendored_test_files_do_not_count(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "test_vendored.py").write_text("def test_x():\n    pass\n")
    assert detect(tmp_path) is None


def test_package_json_test_script_gives_npm(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detect(tmp_path) == "npm test --silent"


def test_package_json_placeholder_test_script_is_none(tmp_path):
    placeholder = 'echo "Error: no test specified" && exit 1'
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": placeholder}}))
    assert detect(tmp_path) is None


def test_package_json_without_test_script_is_none(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))
    assert detect(tmp_path) is None


def test_malformed_package_json_is_none(tmp_path):
    (tmp_path / "package.json").write_text("{not json")
    assert detect(tmp_path) is None


def test_cargo_toml_gives_cargo_test(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'a'\n")
    assert detect(tmp_path) == "cargo test"


def test_makefile_test_target_gives_make_test(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tcc main.c\n\ntest:\n\t./run-tests\n")
    assert detect(tmp_path) == "make test"


def test_makefile_without_test_target_is_none(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tcc main.c\n\ntests-slow:\n\t./slow\n")
    assert detect(tmp_path) is None


def test_no_project_files_is_none(tmp_path):
    (tmp_path / "README.md").write_text("hi\n")
    assert detect(tmp_path) is None


def test_python_wins_over_node_when_both_exist(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    with_tests(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detect(tmp_path) == "python3 -m pytest -q"
