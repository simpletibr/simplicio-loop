"""Unit tests for simplicio_loop.quality_events (dashboard test/lint/coverage/apply payloads).

The parsers are pure: real check output in, a payload or None out. Output that is not recognised
must produce nothing, never an invented count.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import dashboard_events as de
import pytest
from diff_escalation import evaluate

from simplicio_loop import dashboard_events as package_events
from simplicio_loop import quality_events as qe

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "contracts" / "dashboard-event" / "v1" / "schema.json"

PYTEST_FAIL = "==== 3 failed, 10 passed, 2 skipped, 1 error in 1.23s ===="
PYTEST_Q = "3 failed, 10 passed in 1.2s"
UNITTEST_FAILED = (
    "E\n"
    "ERROR: test_b (tests.test_x.B)\n"
    "----------------------------------------------------------------------\n"
    "Ran 5 tests in 0.010s\n"
    "\n"
    "FAILED (failures=1, errors=2)\n"
)
JEST_FAIL = (
    "Tests:       1 failed, 4 passed, 5 total\n"
    "Test Suites: 1 failed, 1 total\n"
    "Time:        1.234 s\n"
)
VITEST_FAIL = (
    " Test Files  1 failed | 1 passed (2)\n"
    "      Tests  1 failed | 4 passed (5)\n"
    "   Duration  850ms (transform 5ms)\n"
)
GO_MIXED = (
    "ok  \texample.com/a\t0.012s\n"
    "FAIL\texample.com/b\t0.034s\n"
    "--- FAIL: TestX (0.00s)\n"
    "FAIL\n"
    "FAIL\texample.com/c [build failed]\n"
)
RUFF_FAIL = (
    "src/a.py:1:1: F401 `os` imported but unused\n"
    "src/b.py:10:80: E501 Line too long (120 > 88)\n"
    "Found 2 errors.\n"
)
MYPY_FAIL = (
    "src/a.py:3: error: Incompatible types in assignment  [assignment]\n"
    "src/a.py:9:5: error: Missing return statement  [return]\n"
    "src/b.py:1: note: See https://mypy.readthedocs.io\n"
    "Found 2 errors in 1 file (checked 2 source files)\n"
)
TERM_MISSING = (
    "Name       Stmts   Miss  Cover   Missing\n"
    "---------------------------------------\n"
    "src/a.py      10      2    80%   3-5, 9\n"
    "src/b.py      20      0   100%\n"
    "---------------------------------------\n"
    "TOTAL         30      2    93%\n"
)


def _read(run_dir):
    path = Path(run_dir) / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _measurement(files=("a.py", "b.py"), added=10, deleted=5, mode="fast-path"):
    return evaluate(mode, list(files), added, deleted, [], [])


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DASHBOARD_EVENTS", raising=False)
    monkeypatch.delenv("SIMPLICIO_ITERATION", raising=False)
    monkeypatch.chdir(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    return run, {"SIMPLICIO_RUN_DIR": str(run)}


# ---------------------------------------------------------------- parse_tests: pytest

def test_pytest_decorated_summary_counts_every_bucket():
    p = qe.parse_tests("pytest -q", "...\n" + PYTEST_FAIL + "\n", 1, 9.9)
    assert p == {
        "tool": "pytest", "command": "pytest -q", "passed": 10, "failed": 3, "skipped": 2,
        "errors": 1, "total": 16, "duration_s": 1.23, "status": "fail",
    }


def test_pytest_short_q_form_without_decoration():
    p = qe.parse_tests("pytest -q", PYTEST_Q, 1, 0)
    assert (p["tool"], p["passed"], p["failed"], p["skipped"], p["errors"], p["total"]) == (
        "pytest", 10, 3, 0, 0, 13)
    assert p["duration_s"] == 1.2 and p["status"] == "fail"


def test_pytest_green_run_is_pass_and_tool_reported_duration_wins():
    p = qe.parse_tests("pytest", "==== 12 passed in 0.5s ====", 0, 1.0)
    assert p["status"] == "pass" and p["passed"] == 12 and p["failed"] == 0 and p["total"] == 12
    assert p["duration_s"] == 0.5


def test_pytest_long_duration_and_warnings_are_not_counted():
    p = qe.parse_tests("pytest", "=== 10 passed, 1 warning in 65.43s (0:01:05) ===", 0, None)
    assert p["passed"] == 10 and p["total"] == 10 and p["duration_s"] == 65.43
    assert p["status"] == "pass"


def test_pytest_ansi_colour_codes_are_ignored():
    text = "\x1b[1m\x1b[32m==== \x1b[0m\x1b[32m\x1b[1m4 passed\x1b[0m\x1b[32m in 0.20s\x1b[0m"
    p = qe.parse_tests("pytest", text, 0, None)
    assert p["passed"] == 4 and p["status"] == "pass"


def test_pytest_nonzero_exit_with_no_failures_is_still_fail():
    p = qe.parse_tests("pytest", "5 passed in 0.1s", 2, 0.1)
    assert p["passed"] == 5 and p["status"] == "fail"


# ---------------------------------------------------------------- parse_tests: unittest

def test_unittest_failed_counts_failures_and_errors_separately():
    p = qe.parse_tests("python -m unittest", UNITTEST_FAILED, 1, 0.5)
    assert (p["tool"], p["total"], p["passed"], p["failed"], p["errors"], p["skipped"]) == (
        "unittest", 5, 2, 1, 2, 0)
    assert p["duration_s"] == 0.01 and p["status"] == "fail"


def test_unittest_ok_with_skips():
    p = qe.parse_tests("python -m unittest", "Ran 5 tests in 0.002s\n\nOK (skipped=1)\n", 0, None)
    assert (p["passed"], p["skipped"], p["failed"], p["total"], p["status"]) == (4, 1, 0, 5, "pass")


def test_unittest_plain_ok_singular_test():
    p = qe.parse_tests("python -m unittest", "Ran 1 test in 0.001s\n\nOK\n", 0, None)
    assert (p["tool"], p["passed"], p["total"], p["status"]) == ("unittest", 1, 1, "pass")


# ---------------------------------------------------------------- parse_tests: jest / vitest

def test_jest_summary_and_time():
    p = qe.parse_tests("npx jest", JEST_FAIL, 1, None)
    assert (p["tool"], p["passed"], p["failed"], p["skipped"], p["total"]) == ("jest", 4, 1, 0, 5)
    assert p["duration_s"] == 1.234 and p["status"] == "fail"


def test_jest_green_with_skipped_falls_back_to_caller_duration():
    p = qe.parse_tests("npx jest", "Tests:  2 skipped, 3 passed, 5 total\n", 0, 2.0)
    assert (p["passed"], p["skipped"], p["total"], p["status"]) == (3, 2, 5, "pass")
    assert p["duration_s"] == 2.0


def test_vitest_summary_and_millisecond_duration():
    p = qe.parse_tests("npx vitest run", VITEST_FAIL, 1, None)
    assert (p["tool"], p["passed"], p["failed"], p["total"]) == ("vitest", 4, 1, 5)
    assert p["duration_s"] == 0.85 and p["status"] == "fail"


# ---------------------------------------------------------------- parse_tests: go

def test_go_counts_package_lines_and_build_failures():
    p = qe.parse_tests("go test ./...", GO_MIXED, 1, 2.5)
    assert (p["tool"], p["passed"], p["failed"], p["errors"], p["total"]) == ("go", 1, 1, 1, 3)
    assert p["duration_s"] == 2.5 and p["status"] == "fail"


def test_go_cached_ok_counts_as_a_passing_package():
    p = qe.parse_tests("go test", "ok  \texample.com/a\t(cached)\n", 0, 0.3)
    assert (p["tool"], p["passed"], p["failed"], p["status"]) == ("go", 1, 0, "pass")


# ---------------------------------------------------------------- parse_tests: negatives

@pytest.mark.parametrize("text", [
    None,
    "",
    "hello world",
    "collected 5 items",
    "3 failed in 1.2 seconds",
    "Tests: no results",
    "Ran 3 tests in 0.1s",
    "a.py:1:1: E501 long line\nFound 1 error.",
])
def test_unrecognised_test_output_returns_none(text):
    assert qe.parse_tests("whatever", text, 0, 1.0) is None


# ---------------------------------------------------------------- parse_lint

def test_ruff_concise_lines_with_summary():
    p = qe.parse_lint("ruff check .", RUFF_FAIL, 1)
    assert p == {
        "tool": "ruff", "command": "ruff check .", "errors": 2, "warnings": 0,
        "by_rule": {"E501": 1, "F401": 1}, "status": "fail",
    }


def test_ruff_all_checks_passed_is_pass():
    p = qe.parse_lint("ruff check .", "All checks passed!\n", 0)
    assert (p["tool"], p["errors"], p["warnings"], p["by_rule"], p["status"]) == (
        "ruff", 0, 0, {}, "pass")


def test_ruff_fixed_summary_counts_only_remaining():
    p = qe.parse_lint("ruff check --fix .", "Found 3 errors (2 fixed, 1 remaining).\n", 1)
    assert p["errors"] == 1 and p["status"] == "fail"


def test_ruff_summary_alone_is_recognised():
    p = qe.parse_lint("ruff check .", "Found 3 errors.\n", 1)
    assert p["tool"] == "ruff" and p["errors"] == 3


def test_flake8_counts_lines_when_there_is_no_summary_and_splits_warnings():
    text = "a.py:1:1: E501 long\na.py:2:1: W291 trailing whitespace\n"
    p = qe.parse_lint("flake8 src", text, 1)
    assert p["tool"] == "flake8" and p["errors"] == 1 and p["warnings"] == 1
    assert p["by_rule"] == {"E501": 1, "W291": 1} and p["status"] == "fail"


def test_flake8_warnings_only_is_pass():
    p = qe.parse_lint("flake8", "a.py:2:1: W291 trailing whitespace\n", 0)
    assert p["errors"] == 0 and p["warnings"] == 1 and p["status"] == "pass"


def test_mypy_errors_with_rule_codes_and_summary():
    p = qe.parse_lint("mypy src", MYPY_FAIL, 1)
    assert p["tool"] == "mypy" and p["errors"] == 2 and p["warnings"] == 0
    assert p["by_rule"] == {"assignment": 1, "return": 1} and p["status"] == "fail"


def test_mypy_success_is_pass():
    p = qe.parse_lint("mypy src", "Success: no issues found in 3 source files\n", 0)
    assert (p["tool"], p["errors"], p["by_rule"], p["status"]) == ("mypy", 0, {}, "pass")


def test_mypy_error_without_code_counts_but_adds_no_rule():
    p = qe.parse_lint("mypy x.py", "x.py:1: error: boom\n", 1)
    assert p["errors"] == 1 and p["by_rule"] == {}


def test_mypy_summary_alone_is_recognised():
    p = qe.parse_lint("mypy", "Found 2 errors in 1 file (checked 1 source file)\n", 1)
    assert p["tool"] == "mypy" and p["errors"] == 2


def test_by_rule_keeps_the_20_most_frequent_rules():
    lines = [f"a.py:{i}:1: E{i:03d} msg" for i in range(1, 26)]
    lines += [f"b.py:{i}:1: E999 msg" for i in range(1, 6)]
    p = qe.parse_lint("ruff check .", "\n".join(lines) + "\nFound 30 errors.\n", 1)
    assert len(p["by_rule"]) == 20
    assert next(iter(p["by_rule"])) == "E999" and p["by_rule"]["E999"] == 5
    assert "E025" not in p["by_rule"]


@pytest.mark.parametrize("text", [None, "", "all good", "3 failed, 10 passed in 1.2s"])
def test_unrecognised_lint_output_returns_none(text):
    assert qe.parse_lint("x", text, 0) is None


# ---------------------------------------------------------------- parse_coverage

@pytest.mark.parametrize("line, percent", [
    ("TOTAL   123   10   90%", 90.0),
    ("TOTAL 100 5 40 4 91%", 91.0),
    ("TOTAL 1000 0 0 0 99.5%", 99.5),
])
def test_coverage_total_with_and_without_branch_columns(line, percent):
    p = qe.parse_coverage("pytest --cov", line + "\n")
    assert p == {"tool": "coverage", "command": "pytest --cov", "percent": percent, "scope": "total"}


def test_coverage_term_missing_table_adds_per_file_rows():
    p = qe.parse_coverage("pytest --cov --cov-report term-missing", TERM_MISSING)
    assert p["percent"] == 93.0 and p["scope"] == "total"
    assert p["files"] == [{"path": "src/a.py", "percent": 80.0},
                          {"path": "src/b.py", "percent": 100.0}]


def test_coverage_files_are_capped_at_50_rows():
    rows = "\n".join(f"src/m{i:02d}.py      10      0   100%" for i in range(60))
    p = qe.parse_coverage("pytest --cov", rows + "\nTOTAL  600  0  100%\n")
    assert len(p["files"]) == 50 and p["files"][0]["path"] == "src/m00.py"


def test_jest_all_files_row_is_coverage_total():
    text = "File      | % Stmts | % Branch\n All files | 85.5 |  80 | 90 | 85.5 |\n"
    p = qe.parse_coverage("npx jest --coverage", text)
    assert p["tool"] == "jest" and p["percent"] == 85.5 and p["scope"] == "total"
    assert "files" not in p


@pytest.mark.parametrize("text", [None, "", "random output", "TOTAL 5 passed in 1s"])
def test_unrecognised_coverage_output_returns_none(text):
    assert qe.parse_coverage("x", text) is None


# ---------------------------------------------------------------- parse_check

def test_parse_check_returns_test_result_tuple_only_for_recognised_output():
    out = qe.parse_check("pytest -q", PYTEST_Q, "", 1, 1.2)
    assert [kind for kind, _ in out] == ["test_result"]
    assert out[0][1]["failed"] == 3


def test_parse_check_orders_test_then_coverage_and_reads_stderr_too():
    stdout = "5 passed in 0.50s\n"
    out = qe.parse_check("pytest --cov", stdout, TERM_MISSING, 0, 0.5)
    assert [kind for kind, _ in out] == ["test_result", "coverage_result"]
    assert out[1][1]["percent"] == 93.0


def test_parse_check_splits_stdout_and_stderr_correctly():
    out = qe.parse_check("python -m unittest", "Ran 2 tests in 0.1s\n", "\nOK\n", 0, 0.1)
    assert [kind for kind, _ in out] == ["test_result"] and out[0][1]["status"] == "pass"


def test_parse_check_lint_output_is_lint_result():
    out = qe.parse_check("ruff check .", "", RUFF_FAIL, 1, 0.2)
    assert [kind for kind, _ in out] == ["lint_result"]


def test_parse_check_unrecognised_or_missing_output_is_empty():
    assert qe.parse_check("make build", "compiling...\ndone\n", "", 0, 3.0) == []
    assert qe.parse_check("x", None, None, 0, None) == []


# ---------------------------------------------------------------- diff_payload

def test_diff_payload_from_the_real_evaluate_result():
    p = qe.diff_payload(_measurement(("a.py", "b.py"), added=10, deleted=5))
    assert p == {"step": "diff", "files": ["a.py", "b.py"], "files_total": 2, "added": 10,
                 "deleted": 5}


def test_diff_payload_converge_mode_is_measured_too():
    p = qe.diff_payload(_measurement(("c.py",), added=1, deleted=0, mode="converge"))
    assert p["files"] == ["c.py"] and p["files_total"] == 1


def test_diff_payload_caps_files_at_200_but_keeps_the_total():
    files = [f"f{i:03d}.py" for i in range(250)]
    p = qe.diff_payload(_measurement(files))
    assert len(p["files"]) == 200 and p["files_total"] == 250


@pytest.mark.parametrize("measurement", [
    None,
    "diff",
    {"measured": False, "measurements": {}},
    {"measured": True},
    {"measured": True, "measurements": {"changed_files": ["a.py"], "added_lines": -1,
                                        "deleted_lines": 0}},
])
def test_diff_payload_refuses_unmeasured_or_malformed_input(measurement):
    assert qe.diff_payload(measurement) is None


# ---------------------------------------------------------------- emit_check

def test_emit_check_writes_one_valid_test_result(run_env):
    run, env = run_env
    written = qe.emit_check("T1", "pytest -q", PYTEST_Q, "", 1, 1.2, env=env)
    assert [e["kind"] for e in written] == ["test_result"]
    events = _read(run)
    assert len(events) == 1
    evt = events[0]
    assert de.validate_envelope(evt) == []
    assert evt["kind"] == "test_result" and evt["source"] == "worker"
    assert evt["task_id"] == "T1" and evt["scope"] == "task"
    assert evt["severity"] == "warning" and evt["iteration"] is None
    assert evt["payload"]["status"] == "fail" and evt["payload"]["failed"] == 3


def test_emit_check_pass_is_info_severity(run_env):
    run, env = run_env
    qe.emit_check("T1", "pytest", "4 passed in 0.1s", "", 0, 0.1, env=env)
    assert _read(run)[0]["severity"] == "info"


def test_emit_check_emits_each_recognised_kind_in_order_with_contiguous_seq(run_env):
    run, env = run_env
    written = qe.emit_check("T1", "pytest --cov", "5 passed in 0.50s\n" + TERM_MISSING, "", 0,
                            0.5, env=env)
    assert [e["kind"] for e in written] == ["test_result", "coverage_result"]
    events = _read(run)
    assert [e["seq"] for e in events] == [1, 2]
    assert all(de.validate_envelope(e) == [] for e in events)
    assert events[1]["payload"]["percent"] == 93.0


def test_emit_check_reads_iteration_from_env_and_explicit_wins(run_env):
    run, env = run_env
    env = dict(env, SIMPLICIO_ITERATION="4")
    qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=env)
    qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, iteration=7, env=env)
    iterations = [e["iteration"] for e in _read(run)]
    assert iterations == [4, 7]


@pytest.mark.parametrize("value", ["x", "-1", "", "2.5"])
def test_emit_check_drops_an_invalid_iteration(run_env, value):
    run, env = run_env
    qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=dict(env, SIMPLICIO_ITERATION=value))
    assert _read(run)[0]["iteration"] is None


def test_emit_check_unrecognised_output_writes_nothing(run_env):
    run, env = run_env
    assert qe.emit_check("T1", "make", "building...\n", "", 0, 1.0, env=env) == []
    assert not (run / "events.jsonl").exists()


def test_emit_check_without_a_run_dir_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_DASHBOARD_EVENTS", raising=False)
    monkeypatch.chdir(tmp_path)
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env={}) == []
    missing = {"SIMPLICIO_RUN_DIR": str(tmp_path / "does-not-exist")}
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=missing) == []


def test_emit_check_respects_the_kill_switch(run_env):
    run, env = run_env
    env = dict(env, SIMPLICIO_DASHBOARD_EVENTS="0")
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=env) == []
    assert not (run / "events.jsonl").exists()


def test_emit_check_never_raises_when_the_emitter_fails(run_env, monkeypatch):
    _run, env = run_env

    def boom():
        raise RuntimeError("loader broke")

    monkeypatch.setattr(package_events, "load", boom)
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=env) == []


def test_emit_check_returns_empty_when_the_emitter_is_missing(run_env, monkeypatch):
    _run, env = run_env
    monkeypatch.setattr(package_events, "load", lambda: None)
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=env) == []


def test_emit_check_survives_an_exception_inside_the_emit_call(run_env, monkeypatch):
    run, env = run_env

    def exploding_emit(*_args, **_kwargs):
        raise OSError("disk full")

    fake = SimpleNamespace(enabled=lambda env=None: True, resolve_run_dir=lambda env=None: str(run),
                           emit=exploding_emit)
    monkeypatch.setattr(package_events, "load", lambda: fake)
    assert qe.emit_check("T1", "pytest", PYTEST_Q, "", 1, 1.2, env=env) == []


def test_emit_check_with_no_stdout_or_stderr_is_empty(run_env):
    _run, env = run_env
    assert qe.emit_check("T1", "pytest", None, None, 0, None, env=env) == []


# ---------------------------------------------------------------- emit_diff

def test_emit_diff_writes_one_apply_result_from_a_real_measurement(run_env):
    run, env = run_env
    written = qe.emit_diff("T2", _measurement(("a.py", "b.py"), added=10, deleted=5), env=env)
    assert len(written) == 1
    evt = _read(run)[0]
    assert de.validate_envelope(evt) == []
    assert evt["kind"] == "apply_result" and evt["source"] == "worker"
    assert evt["task_id"] == "T2" and evt["scope"] == "task" and evt["severity"] == "info"
    assert evt["payload"] == {"step": "diff", "files": ["a.py", "b.py"], "files_total": 2,
                              "added": 10, "deleted": 5}


def test_emit_diff_unmeasured_writes_nothing(run_env):
    run, env = run_env
    assert qe.emit_diff("T2", {"measured": False, "measurements": {}}, env=env) == []
    assert not (run / "events.jsonl").exists()


def test_emit_diff_respects_the_kill_switch_and_iteration(run_env):
    run, env = run_env
    assert qe.emit_diff("T2", _measurement(), env=dict(env, SIMPLICIO_DASHBOARD_EVENTS="off")) == []
    qe.emit_diff("T2", _measurement(), iteration=3, env=env)
    assert [e["iteration"] for e in _read(run)] == [3]


def test_emitted_envelopes_match_the_json_schema(run_env):
    jsonschema = pytest.importorskip("jsonschema")
    run, env = run_env
    qe.emit_check("T1", "pytest --cov", "5 passed in 0.50s\n" + TERM_MISSING, "", 0, 0.5, env=env)
    qe.emit_check("T1", "ruff check .", RUFF_FAIL, "", 1, 0.2, env=env)
    qe.emit_diff("T1", _measurement(), env=env)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    events = _read(run)
    assert len(events) == 4
    for evt in events:
        jsonschema.validate(evt, schema)
