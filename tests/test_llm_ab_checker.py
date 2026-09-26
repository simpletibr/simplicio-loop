"""TDD unit tests for bench/llm_ab/checker.py's checker-name parameter
(needed once login.html tasks use a different acceptance script than
cadastro.html's).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import checker  # noqa: E402


def _write_fake_checker(repo, name, exit_code):
    tests_dir = os.path.join(repo, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    path = os.path.join(tests_dir, name)
    with open(path, "w") as f:
        f.write(
            "import argparse, sys\n"
            "ap = argparse.ArgumentParser()\n"
            "ap.add_argument('--stage', type=int, required=True)\n"
            "args = ap.parse_args()\n"
            f"print('stage', args.stage)\n"
            f"sys.exit({exit_code})\n"
        )
    return path


def test_run_check_defaults_to_check_cadastro(tmp_path):
    _write_fake_checker(str(tmp_path), "check_cadastro.py", 0)
    passed, out, metrics = checker.run_check(str(tmp_path), 1, sys.executable)
    assert passed is True
    assert "stage 1" in out
    assert metrics["returncode"] == 0


def test_run_check_uses_named_checker_when_given(tmp_path):
    _write_fake_checker(str(tmp_path), "check_login.py", 0)
    passed, out, _ = checker.run_check(str(tmp_path), 2, sys.executable, checker="check_login.py")
    assert passed is True
    assert "stage 2" in out


def test_run_check_reports_failure_from_nonzero_exit(tmp_path):
    _write_fake_checker(str(tmp_path), "check_login.py", 1)
    passed, _out, metrics = checker.run_check(str(tmp_path), 1, sys.executable, checker="check_login.py")
    assert passed is False
    assert metrics["returncode"] == 1


def test_verifier_line_defaults_to_check_cadastro():
    assert checker.verifier_line(1) == "python3 tests/check_cadastro.py --stage 1"


def test_verifier_line_accepts_checker_name():
    assert checker.verifier_line(2, checker="check_login.py") == "python3 tests/check_login.py --stage 2"
