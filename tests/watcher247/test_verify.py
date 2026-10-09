"""verify.py: detecting the target repo's test command, the turbo argv, and the pr/retry/dead decision."""
from __future__ import annotations

import json

import pytest

from simplicio_loop.watcher247 import verify

PYTEST = "python3 -m pytest -q"


def detect(path):
    return verify.detect_test_command(path)


def with_tests(path):
    (path / "tests").mkdir(exist_ok=True)
    (path / "tests" / "test_sample.py").write_text("def test_ok():\n    assert True\n")
    return path


# --- python: pyproject.toml alone is not pytest evidence ---

def test_bare_pyproject_is_not_pytest_evidence(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    assert detect(tmp_path) is None


def test_pyproject_with_pytest_ini_options_section_gives_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    assert detect(tmp_path) == PYTEST


def test_pytest_ini_gives_pytest(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert detect(tmp_path) == PYTEST


def test_setup_cfg_with_pytest_section_gives_pytest(tmp_path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\ntestpaths = tests\n")
    assert detect(tmp_path) == PYTEST


def test_setup_cfg_without_pytest_section_is_none(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = a\n")
    assert detect(tmp_path) is None


def test_conftest_gives_pytest(tmp_path):
    (tmp_path / "conftest.py").write_text("")
    assert detect(tmp_path) == PYTEST


def test_tests_dir_with_test_files_gives_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'a'\n")
    with_tests(tmp_path)
    assert detect(tmp_path) == PYTEST


def test_tests_dir_without_test_files_is_none(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "helpers.py").write_text("")
    assert detect(tmp_path) is None


# --- the other project types ---

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
    with_tests(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    assert detect(tmp_path) == PYTEST


# --- turbo argv ---

def test_argv_includes_verify_when_a_test_command_exists(tmp_path):
    argv = verify.turbo_argv(tmp_path, "do it", PYTEST)
    assert argv[:2] == ["simplicio-loop", "turbo"]
    assert argv[argv.index("--verify") + 1] == PYTEST
    assert argv[argv.index("--task") + 1] == "do it"
    assert argv[argv.index("--provider") + 1] == "openrouter"


def test_argv_has_no_verify_without_a_test_command(tmp_path):
    assert "--verify" not in verify.turbo_argv(tmp_path, "do it", None)


# --- decision ---

OK = {"status": "ok"}


def ok_with(passed, tail=""):
    return {"status": "ok", "verify": {"passed": passed, "output_tail": tail}}


def test_verified_pass_opens_a_pr():
    decision = verify.decide(ok_with(True), PYTEST, 1, 3)
    assert decision.action == "pr"
    assert decision.label == f"MEASURED|verify_passed: `{PYTEST}`"


def test_no_test_command_opens_a_pr_marked_unverified():
    decision = verify.decide(OK, None, 1, 3)
    assert decision.action == "pr"
    assert decision.label == "UNVERIFIED|no_test_command"


@pytest.mark.parametrize("attempts,action", [(1, "retry"), (2, "retry"), (3, "dead")])
def test_verify_failure_never_opens_a_pr(attempts, action):
    decision = verify.decide(ok_with(False, "1 failed"), PYTEST, attempts, 3)
    assert decision.action == action
    assert "1 failed" in decision.reason
    assert decision.label != f"MEASURED|verify_passed: `{PYTEST}`"


def test_missing_verify_report_fails_closed():
    decision = verify.decide(OK, PYTEST, 1, 3)
    assert decision.action == "retry"
    assert "verify" in decision.reason


def test_turbo_failure_retries_with_its_detail():
    decision = verify.decide({"status": "failed", "detail": "boom"}, None, 1, 3)
    assert decision.action == "retry" and decision.reason == "boom"


def test_retry_or_dead_threshold():
    assert verify.retry_or_dead(2, 3) == "retry"
    assert verify.retry_or_dead(3, 3) == "dead"
