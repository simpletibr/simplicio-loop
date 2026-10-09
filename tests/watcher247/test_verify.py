"""Deterministic detection of the target repo's test command (the --verify passed to turbo)."""
from __future__ import annotations

import asyncio
import json

from simplicio_loop.watcher247 import verify


def detect(path):
    return asyncio.run(verify.detect(path))


def test_pyproject_gives_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_pytest_ini_gives_pytest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n")
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_setup_cfg_with_pytest_section_gives_pytest(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_tox_ini_with_pytest_section_gives_pytest(tmp_path):
    (tmp_path / "tox.ini").write_text("[pytest]\naddopts = -q\n")
    assert detect(tmp_path) == "python3 -m pytest -q"


def test_setup_cfg_without_pytest_section_is_none(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = a\n")
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
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detect(tmp_path) == "python3 -m pytest -q"
