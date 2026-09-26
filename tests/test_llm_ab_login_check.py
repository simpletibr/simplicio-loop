"""TDD unit tests for the harness-owned bench/llm_ab/fixture/tests/check_login.py
(the acceptance checker for the login.html benchmark tasks, --tasks 4).

Loaded by file path, exercised purely in memory: no benchmark run, no LLM
call, no subprocess.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECK_PATH = os.path.join(REPO, "bench", "llm_ab", "fixture", "tests", "check_login.py")

spec = importlib.util.spec_from_file_location("check_login", CHECK_PATH)
check_login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_login)

STAGE1_VALID = """
<html><body>
<form id="login">
  <label>Email <input name="email" type="email" required></label>
  <label>Password <input name="password" type="password" required></label>
  <button type="submit">Enter</button>
</form>
</body></html>
"""

STAGE2_VALID = """
<html><body>
<form id="login">
  <label>Email <input name="email" type="email" required></label>
  <label>Password <input name="password" type="password" required></label>
  <label><input name="remember" type="checkbox"> Remember me</label>
  <button type="submit">Enter</button>
</form>
<a href="cadastro.html">Create an account</a>
</body></html>
"""


def parse(html_text):
    return check_login.parse_login(html_text)


def test_stage1_passes_on_valid_form():
    assert check_login.check_stage1(parse(STAGE1_VALID)) == []


def test_stage1_fails_without_form_id():
    html = STAGE1_VALID.replace('id="login"', 'id="other"')
    failures = check_login.check_stage1(parse(html))
    assert any("form" in f for f in failures)


def test_stage1_fails_on_missing_required_email():
    html = STAGE1_VALID.replace(
        '<input name="email" type="email" required>', '<input name="email" type="email">'
    )
    failures = check_login.check_stage1(parse(html))
    assert any("email" in f and "required" in f for f in failures)


def test_stage1_fails_on_wrong_password_type():
    html = STAGE1_VALID.replace(
        '<input name="password" type="password" required>',
        '<input name="password" type="text" required>',
    )
    failures = check_login.check_stage1(parse(html))
    assert any("password" in f and "type=password" in f for f in failures)


def test_stage1_fails_without_submit_control():
    html = STAGE1_VALID.replace('<button type="submit">Enter</button>', "")
    failures = check_login.check_stage1(parse(html))
    assert any("submit" in f for f in failures)


def test_stage2_passes_on_valid_form():
    assert check_login.check_stage2(parse(STAGE2_VALID)) == []


def test_stage2_still_enforces_stage1_fields():
    html = STAGE2_VALID.replace(
        '<input name="email" type="email" required>', '<input name="email" type="email">'
    )
    failures = check_login.check_stage2(parse(html))
    assert any("email" in f and "required" in f for f in failures)


def test_stage2_fails_when_missing_remember_checkbox():
    html = STAGE2_VALID.replace(
        '<input name="remember" type="checkbox">', ""
    )
    failures = check_login.check_stage2(parse(html))
    assert any("remember" in f for f in failures)


def test_stage2_fails_on_wrong_remember_type():
    html = STAGE2_VALID.replace('type="checkbox"', 'type="text"')
    failures = check_login.check_stage2(parse(html))
    assert any("remember" in f and "checkbox" in f for f in failures)


def test_stage2_fails_when_missing_cadastro_link():
    html = STAGE2_VALID.replace('<a href="cadastro.html">Create an account</a>', "")
    failures = check_login.check_stage2(parse(html))
    assert any("cadastro" in f for f in failures)


def test_stage2_accepts_cadastro_link_outside_the_form():
    # The link is signup navigation, not a form field -- it must not be
    # required to live inside <form id="login">.
    html = STAGE2_VALID
    assert check_login.check_stage2(parse(html)) == []


def test_stage2_accepts_link_with_extra_path_segments():
    html = STAGE2_VALID.replace('href="cadastro.html"', 'href="./cadastro.html"')
    assert check_login.check_stage2(parse(html)) == []


def test_check_file_reports_missing_file(tmp_path):
    missing = tmp_path / "login.html"
    failures = check_login.check_file(missing, 1)
    assert failures and "does not exist" in failures[0]


def test_check_file_reads_and_checks_real_file(tmp_path):
    path = tmp_path / "login.html"
    path.write_text(STAGE1_VALID, encoding="utf-8")
    assert check_login.check_file(path, 1) == []


def test_main_cli_exit_codes(tmp_path, capsys):
    path = tmp_path / "login.html"
    path.write_text(STAGE1_VALID, encoding="utf-8")
    assert check_login.main(["--stage", "1", "--path", str(path)]) == 0
    assert check_login.main(["--stage", "2", "--path", str(path)]) == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err


@pytest.mark.parametrize("stage", [1, 2])
def test_default_path_points_at_repo_root_relative_to_module(stage):
    assert check_login.DEFAULT_PATH.name == "login.html"
    assert check_login.DEFAULT_PATH.parent.name != "tests"
