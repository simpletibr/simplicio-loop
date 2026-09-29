from __future__ import annotations

import json
import sys
from pathlib import Path

from simplicio_loop.installed_artifact import query_installed_artifact


def test_independent_interpreter_requery_matches_real_installed_module():
    import pytest as module

    observed = query_installed_artifact(
        python_executable=sys.executable,
        distribution="pytest",
        module="pytest",
        expected_commit="commit-under-test",
        expected_file=Path(module.__file__),
    )
    assert observed["exit_code"] == 0
    assert observed["installed_commit"] == "commit-under-test"
    assert observed["match"] is True
    assert observed["sha256"] == observed["expected_sha256"]
    assert observed["path"]


def test_installed_requery_fails_closed_on_unimportable_module(tmp_path):
    expected = tmp_path / "expected.py"
    expected.write_text("pass\n")
    observed = query_installed_artifact(
        python_executable=sys.executable,
        distribution="simplicio-loop",
        module="module_that_does_not_exist_785",
        expected_commit="commit-under-test",
        expected_file=expected,
    )
    assert observed["exit_code"] != 0
    assert observed["installed_commit"] is None
    assert observed["match"] is False


def test_installed_requery_rejects_malformed_probe_output(tmp_path):
    expected = tmp_path / "expected.py"
    expected.write_text("pass\n")
    observed = query_installed_artifact(
        python_executable=sys.executable,
        distribution="unused",
        module="unused",
        expected_commit="commit-under-test",
        expected_file=expected,
        command=(sys.executable, "-c", "print('not-json')"),
    )
    assert observed["exit_code"] == 0
    assert observed["installed_commit"] is None
    assert observed["match"] is False


def test_checked_in_wheel_requery_proves_installed_bytes_match_checkout():
    path = Path(__file__).parent / "fixtures" / "installed_artifact_e2e_785.json"
    observed = json.loads(path.read_text(encoding="utf-8"))
    assert observed["classification"] == "MEASURED_LOCAL"
    assert observed["local_llm"] is False
    assert observed["exit_code"] == 0
    assert observed["match"] is True
    assert observed["installed_commit"] == observed["expected_commit"]
    assert observed["sha256"] == observed["expected_sha256"]
    assert observed["wheel"]["size"] > 0
