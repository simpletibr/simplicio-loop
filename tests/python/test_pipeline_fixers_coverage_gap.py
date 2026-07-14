"""Additional unit coverage for simplicio/pipeline_fixers.py."""

from __future__ import annotations

import subprocess
import sys

import pytest

from simplicio import pipeline_fixers as pf
from simplicio.pipeline_fixers import (
    MissingCargoCrateFixer,
    MissingGoModuleFixer,
    MissingNpmPackageFixer,
    MissingPipPackageFixer,
    RuffFormatFixer,
)


def _ok(argv):
    return subprocess.CompletedProcess(argv, 0, "", "")


def _fail(argv, out="boom-stdout", err="boom-stderr"):
    return subprocess.CompletedProcess(argv, 1, out, err)


# ---------------------------------------------------------------------------
# _safe_* helper functions
# ---------------------------------------------------------------------------


def test_safe_python_package_rejects_traversal():
    assert pf._safe_python_package("../secret") is None


def test_safe_python_package_accepts_simple_name():
    assert pf._safe_python_package("my_package") == "my-package"


def test_safe_node_package_rejects_relative_path():
    assert pf._safe_node_package("./local") is None
    assert pf._safe_node_package("") is None


def test_safe_node_package_accepts_scoped_package():
    assert pf._safe_node_package("@scope/pkg/sub") == "@scope/pkg"


def test_safe_go_module_rejects_relative():
    assert pf._safe_go_module("../secret") is None


def test_safe_go_module_rejects_bare_stdlib_name():
    assert pf._safe_go_module("fmt") is None


def test_safe_go_module_accepts_dotted_host_path():
    assert pf._safe_go_module("github.com/gin-gonic/gin") == "github.com/gin-gonic/gin"


def test_safe_cargo_crate_rejects_std_module():
    assert pf._safe_cargo_crate("std") is None


def test_safe_cargo_crate_accepts_simple_name():
    assert pf._safe_cargo_crate("`serde_json`") == "serde_json"


def test_dependency_name_normalizes():
    assert pf._dependency_name("My_Package>=1.0") == "my-package"


def test_declares_dependency_true_and_false():
    lines = ['  "httpx>=0.28.1",']
    assert pf._declares_dependency(lines, "httpx") is True
    assert pf._declares_dependency(lines, "fastapi") is False


# ---------------------------------------------------------------------------
# _add_pyproject_dependency branches
# ---------------------------------------------------------------------------


def test_add_pyproject_dependency_creates_new_file(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is True
    assert '"fastapi"' in pyproject.read_text(encoding="utf-8")


def test_add_pyproject_dependency_no_project_section_appends_one(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.other]\nkey = 1\n", encoding="utf-8")
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is True
    text = pyproject.read_text(encoding="utf-8")
    assert "[project]" in text
    assert '"fastapi"' in text


def test_add_pyproject_dependency_already_declared_returns_false(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = [\n  "fastapi>=1.0",\n]\n', encoding="utf-8"
    )
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is False


def test_add_pyproject_dependency_no_dependencies_key_inserts_one(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n\n[tool.other]\n', encoding="utf-8")
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is True
    text = pyproject.read_text(encoding="utf-8")
    assert "dependencies = [" in text
    assert '"fastapi"' in text


def test_add_pyproject_dependency_single_line_list(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = ["httpx>=0.28.1"]\n', encoding="utf-8"
    )
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is True
    text = pyproject.read_text(encoding="utf-8")
    assert '"fastapi"' in text
    assert '"httpx>=0.28.1"' in text


def test_add_pyproject_dependency_multiline_list_appends_before_close(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\ndependencies = [\n  "httpx>=0.28.1",\n]\n', encoding="utf-8"
    )
    changed = pf._add_pyproject_dependency(pyproject, "fastapi")
    assert changed is True
    text = pyproject.read_text(encoding="utf-8")
    assert '"fastapi",' in text
    assert '"httpx>=0.28.1",' in text


def test_find_project_section_missing_returns_none():
    assert pf._find_project_section(["[tool.other]", "key = 1"]) is None


# ---------------------------------------------------------------------------
# Fixer failure branches (no match / subprocess failure / exception)
# ---------------------------------------------------------------------------


def test_missing_pip_package_fixer_no_match_in_log(tmp_path):
    result = MissingPipPackageFixer().try_fix("some unrelated error", tmp_path)
    assert result.applied is False
    assert "no safe Python package" in result.details


def test_missing_pip_package_fixer_install_failure(tmp_path):
    def fake_run(argv, **kwargs):
        return _fail(argv)

    result = MissingPipPackageFixer().try_fix(
        "ModuleNotFoundError: No module named 'fastapi'", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "pip install fastapi failed" in result.details


def test_missing_pip_package_fixer_runner_raises_timeout(tmp_path):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    result = MissingPipPackageFixer().try_fix(
        "ModuleNotFoundError: No module named 'fastapi'", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "pip install failed" in result.details


def test_missing_npm_package_fixer_no_match(tmp_path):
    result = MissingNpmPackageFixer().try_fix("unrelated error", tmp_path)
    assert result.applied is False
    assert "no safe npm package" in result.details


def test_missing_npm_package_fixer_no_lockfile_uses_npm(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    result = MissingNpmPackageFixer().try_fix(
        "Cannot find module 'lodash'", tmp_path, runner=fake_run
    )
    assert result.applied is True
    assert calls[0] == ["npm", "install", "lodash"]


def test_missing_npm_package_fixer_yarn_lockfile(tmp_path):
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _ok(argv)

    MissingNpmPackageFixer().try_fix("Cannot find module 'lodash'", tmp_path, runner=fake_run)
    assert calls[0] == ["yarn", "add", "lodash"]


def test_missing_npm_package_fixer_install_failure(tmp_path):
    def fake_run(argv, **kwargs):
        return _fail(argv)

    result = MissingNpmPackageFixer().try_fix(
        "Cannot find module 'lodash'", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "npm install lodash failed" in result.details


def test_missing_npm_package_fixer_runner_raises(tmp_path):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no npm")

    result = MissingNpmPackageFixer().try_fix(
        "Cannot find module 'lodash'", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "npm install failed" in result.details


def test_missing_go_module_fixer_no_match(tmp_path):
    result = MissingGoModuleFixer().try_fix("unrelated", tmp_path)
    assert result.applied is False
    assert "no safe Go module" in result.details


def test_missing_go_module_fixer_install_failure(tmp_path):
    def fake_run(argv, **kwargs):
        return _fail(argv)

    result = MissingGoModuleFixer().try_fix(
        "no required module provides package github.com/gin-gonic/gin", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "go get github.com/gin-gonic/gin failed" in result.details


def test_missing_go_module_fixer_runner_raises(tmp_path):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no go")

    result = MissingGoModuleFixer().try_fix(
        "no required module provides package github.com/gin-gonic/gin", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "go get failed" in result.details


def test_missing_cargo_crate_fixer_no_match(tmp_path):
    result = MissingCargoCrateFixer().try_fix("unrelated", tmp_path)
    assert result.applied is False
    assert "no safe Cargo crate" in result.details


def test_missing_cargo_crate_fixer_install_failure(tmp_path):
    def fake_run(argv, **kwargs):
        return _fail(argv)

    result = MissingCargoCrateFixer().try_fix(
        "use of undeclared crate or module `serde_json`", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "cargo add serde_json failed" in result.details


def test_missing_cargo_crate_fixer_runner_raises(tmp_path):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("no cargo")

    result = MissingCargoCrateFixer().try_fix(
        "use of undeclared crate or module `serde_json`", tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "cargo add failed" in result.details


def test_ruff_format_fixer_no_match_returns_early(tmp_path):
    result = RuffFormatFixer().try_fix("AssertionError: nope", tmp_path)
    assert result.applied is False
    assert "no syntax or indentation" in result.details


def test_ruff_format_fixer_cannot_identify_target(tmp_path):
    result = RuffFormatFixer().try_fix("SyntaxError: invalid syntax", tmp_path)
    assert result.applied is False
    assert "could not identify a Python target" in result.details


def test_ruff_format_fixer_runner_raises(tmp_path):
    target = tmp_path / "bad.py"
    target.write_text("x=1\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    result = RuffFormatFixer().try_fix(
        f'SyntaxError: invalid syntax\n  File "{target}", line 1', tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "ruff failed" in result.details


def test_ruff_format_fixer_still_fails_after_running(tmp_path):
    target = tmp_path / "bad.py"
    target.write_text("x=1\n", encoding="utf-8")

    def fake_run(argv, **kwargs):
        return _fail(argv)

    result = RuffFormatFixer().try_fix(
        f'SyntaxError: invalid syntax\n  File "{target}", line 1', tmp_path, runner=fake_run
    )
    assert result.applied is False
    assert "ruff could not fix" in result.details


def test_python_error_target_rejects_path_outside_root(tmp_path):
    other_root = tmp_path / "elsewhere"
    other_root.mkdir()
    outside_file = other_root / "outside.py"
    outside_file.write_text("x=1\n", encoding="utf-8")
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    log = f'File "{outside_file}", line 1'
    assert pf._python_error_target(log, project_dir) is None


def test_python_error_target_rejects_nonexistent_file(tmp_path):
    log = 'File "does_not_exist.py", line 1'
    assert pf._python_error_target(log, tmp_path) is None


def test_python_error_target_finds_relative_colon_style(tmp_path):
    target = tmp_path / "src" / "bad.py"
    target.parent.mkdir()
    target.write_text("x=1\n", encoding="utf-8")
    log = "src/bad.py:3:2: syntax error"
    found = pf._python_error_target(log, tmp_path)
    assert found == target.resolve()
