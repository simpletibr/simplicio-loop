"""issue #1331: `edit --apply` verification must never run an unbounded,
unrelated full-suite `pytest -q` by default.

- an explicit ``check`` (task/plan-declared) runs only that command;
- otherwise a scoped default limited to tests referencing the changed
  files, or no verification at all when none are found -- never the whole
  suite;
- the default timeout is bounded (120s) and configurable;
- a timed-out verification kills the whole process group, not just the
  direct child.
"""
from __future__ import annotations

import os
import time

from simplicio import pipeline_stages as stages
from simplicio.commands import edit as edit_cmd


def test_default_timeout_is_bounded_not_unlimited(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_TIMEOUT_S", raising=False)
    assert stages._verification_timeout_seconds() == 120


def test_scoped_command_finds_sibling_test_file(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_widget.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_other.py").write_text("def test_y():\n    assert True\n", encoding="utf-8")
    command = stages._scoped_verification_command(str(tmp_path), ["widget.py"])
    assert command is not None
    assert "test_widget.py" in command
    assert "test_other.py" not in command


def test_scoped_command_none_when_no_matching_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_z():\n    pass\n", encoding="utf-8")
    assert stages._scoped_verification_command(str(tmp_path), ["some_module.py"]) is None
    assert stages._scoped_verification_command(str(tmp_path), None) is None


def test_verification_payload_uses_explicit_check_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")  # must be ignored: explicit check wins
    verify = edit_cmd._verification_payload(
        str(tmp_path), applied=True, check="python3 -c \"print('ok')\"", changed_files=["anything.py"],
    )
    assert verify["status"] == "passed"
    assert verify["commands"] == ["python3 -c \"print('ok')\""]


def test_verification_payload_skips_when_no_scoped_tests_and_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    verify = edit_cmd._verification_payload(str(tmp_path), applied=True, changed_files=["nothing.py"])
    assert verify["status"] == "skipped"
    assert verify["reason_code"] == "verify_skipped_no_scoped_tests"


def test_verification_payload_never_falls_back_to_whole_suite(tmp_path, monkeypatch):
    """A repo with an unrelated, slow-looking test tree must not be run in
    full just because a change landed somewhere else in it."""
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_benchmark_unrelated.py").write_text(
        "def test_slow():\n    assert True\n", encoding="utf-8"
    )
    verify = edit_cmd._verification_payload(str(tmp_path), applied=True, changed_files=["scripts/thing.py"])
    assert verify["status"] == "skipped"
    for result in verify["results"]:
        assert "test_benchmark_unrelated.py" not in result.get("command", "")


def test_bounded_subprocess_kills_whole_process_group_on_timeout(tmp_path):
    marker = tmp_path / "child_alive"
    # The shell exits almost immediately, but leaves a detached grandchild
    # sleeping in the background -- exactly the orphan shape #1327/#1328
    # observed from `pytest -q` under a shell.
    script = f"(sleep 5; echo dead > {marker}) &\nsleep 30\n"
    returncode, _stdout, _stderr, timed_out = stages.run_bounded_subprocess(
        script, shell=True, cwd=str(tmp_path), env=dict(os.environ), timeout=0.3,
    )
    assert timed_out is True
    assert returncode == 124
    time.sleep(1.0)
    assert not marker.exists(), "background grandchild survived the timeout: process group was not killed"
