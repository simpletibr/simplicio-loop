"""TDD unit tests for the harness-owned bench/llm_ab/fixture/tests/check_cadastro.py.

Loaded by file path (it is not an importable package -- it ships inside the
benchmark fixture repo, one file, stdlib only) and exercised purely in
memory: no benchmark run, no LLM call, no subprocess.
"""
import importlib.util
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CHECK_PATH = os.path.join(REPO, "bench", "llm_ab", "fixture", "tests", "check_cadastro.py")

spec = importlib.util.spec_from_file_location("check_cadastro", CHECK_PATH)
check_cadastro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_cadastro)

STAGE1_VALID = """
<html><body>
<form id="cadastro">
  <label>Name <input name="name" type="text" required></label>
  <label>Email <input name="email" type="email" required></label>
  <label>Password <input name="password" type="password" required minlength="8"></label>
  <button type="submit">Send</button>
</form>
</body></html>
"""

STAGE2_VALID = """
<html><body>
<form id="cadastro">
  <label>Name <input name="name" type="text" required></label>
  <label>Email <input name="email" type="email" required></label>
  <label>Password <input name="password" type="password" required minlength="8"></label>
  <label>Phone <input name="phone" type="tel"></label>
  <label>Confirm <input name="password_confirm" type="password" required minlength="8"></label>
  <button type="submit">Send</button>
</form>
</body></html>
"""


def parse(html_text):
    return check_cadastro.parse_cadastro(html_text)


def test_stage1_passes_on_valid_form():
    assert check_cadastro.check_stage1(parse(STAGE1_VALID)) == []


def test_stage1_fails_without_form_id():
    html = STAGE1_VALID.replace('id="cadastro"', 'id="other"')
    failures = check_cadastro.check_stage1(parse(html))
    assert any("form" in f for f in failures)


def test_stage1_fails_on_missing_required_email():
    html = STAGE1_VALID.replace(
        '<input name="email" type="email" required>',
        '<input name="email" type="email">',
    )
    failures = check_cadastro.check_stage1(parse(html))
    assert any("email" in f and "required" in f for f in failures)


def test_stage1_fails_on_wrong_password_type():
    html = STAGE1_VALID.replace(
        '<input name="password" type="password" required minlength="8">',
        '<input name="password" type="text" required minlength="8">',
    )
    failures = check_cadastro.check_stage1(parse(html))
    assert any("password" in f and "type=password" in f for f in failures)


def test_stage1_fails_on_missing_minlength():
    html = STAGE1_VALID.replace(
        '<input name="password" type="password" required minlength="8">',
        '<input name="password" type="password" required>',
    )
    failures = check_cadastro.check_stage1(parse(html))
    assert any("minlength" in f for f in failures)


def test_stage1_fails_without_submit_control():
    html = STAGE1_VALID.replace('<button type="submit">Send</button>', "")
    failures = check_cadastro.check_stage1(parse(html))
    assert any("submit" in f for f in failures)


def test_stage1_accepts_input_type_submit_instead_of_button():
    html = STAGE1_VALID.replace(
        '<button type="submit">Send</button>',
        '<input type="submit" value="Send">',
    )
    assert check_cadastro.check_stage1(parse(html)) == []


def test_stage1_accepts_plain_button_defaulting_to_submit():
    html = STAGE1_VALID.replace('<button type="submit">Send</button>', "<button>Send</button>")
    assert check_cadastro.check_stage1(parse(html)) == []


def test_stage2_passes_on_valid_form():
    assert check_cadastro.check_stage2(parse(STAGE2_VALID)) == []


def test_stage2_fails_when_missing_phone():
    html = STAGE2_VALID.replace('<input name="phone" type="tel">', "")
    failures = check_cadastro.check_stage2(parse(html))
    assert any("phone" in f for f in failures)


def test_stage2_fails_on_wrong_phone_type():
    html = STAGE2_VALID.replace('type="tel"', 'type="text"')
    failures = check_cadastro.check_stage2(parse(html))
    assert any("phone" in f and "tel" in f for f in failures)


def test_stage2_fails_when_missing_password_confirm():
    html = STAGE2_VALID.replace(
        '<input name="password_confirm" type="password" required minlength="8">', ""
    )
    failures = check_cadastro.check_stage2(parse(html))
    assert any("password_confirm" in f for f in failures)


def test_stage2_still_enforces_stage1_fields():
    # Stage 2 must not silently accept a regressed stage-1 field.
    html = STAGE2_VALID.replace(
        '<input name="email" type="email" required>',
        '<input name="email" type="email">',
    )
    failures = check_cadastro.check_stage2(parse(html))
    assert any("email" in f and "required" in f for f in failures)


def test_check_file_reports_missing_file(tmp_path):
    missing = tmp_path / "cadastro.html"
    failures = check_cadastro.check_file(missing, 1)
    assert failures and "does not exist" in failures[0]


def test_check_file_reads_and_checks_real_file(tmp_path):
    path = tmp_path / "cadastro.html"
    path.write_text(STAGE1_VALID, encoding="utf-8")
    assert check_cadastro.check_file(path, 1) == []


def test_main_cli_exit_codes(tmp_path, capsys):
    path = tmp_path / "cadastro.html"
    path.write_text(STAGE1_VALID, encoding="utf-8")
    assert check_cadastro.main(["--stage", "1", "--path", str(path)]) == 0
    assert check_cadastro.main(["--stage", "2", "--path", str(path)]) == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err


@pytest.mark.parametrize("stage", [1, 2])
def test_default_path_points_at_repo_root_relative_to_module(stage):
    # tests/check_cadastro.py -> parent (tests/) -> parent (repo root) -> cadastro.html
    expected_name = "cadastro.html"
    assert check_cadastro.DEFAULT_PATH.name == expected_name
    assert check_cadastro.DEFAULT_PATH.parent.name != "tests"
