"""Line-execution check: the new tests must EXECUTE the changed production lines (Parte de #1649, finding m3).

A test that reads the source text (`"return a - b" in src`) passes without running the code it names, so it proves nothing.
Each test here builds a real git repo with one commit on `main` and one on `head`, and runs the check on the head tree.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from simplicio_loop.review_gate import diffs, line_coverage
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, SKIPPED

BASE_MOD = "def sub(a, b):\n    return b\n"
HEAD_MOD = "def sub(a, b):\n    return a - b\n"  # line 2 is the changed production line

SOURCE_ONLY_TEST = textwrap.dedent('''\
    from pathlib import Path


    def test_sub_source_text():
        src = (Path(__file__).parents[1] / "mod.py").read_text()
        assert "return a - b" in src
    ''')

CALLS_TEST = textwrap.dedent('''\
    from mod import sub


    def test_sub_subtracts():
        assert sub(5, 2) == 3
    ''')

GIT = ("git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")


def _git(repo, *args):
    subprocess.run([*GIT, *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path, test_text, mod_text=HEAD_MOD, extra=None):
    """A git repo: `main` has BASE_MOD, `head` changes mod.py, adds tests/test_mod.py and the `extra` files. Returns (repo, changes)."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main", str(repo))
    (repo / "mod.py").write_text(BASE_MOD)
    _git(repo, "-C", str(repo), "add", "-A")
    _git(repo, "-C", str(repo), "commit", "-q", "-m", "base")
    _git(repo, "-C", str(repo), "checkout", "-q", "-b", "head")
    (repo / "mod.py").write_text(mod_text)
    (repo / "tests" / "test_mod.py").write_text(test_text)
    for name, text in (extra or {}).items():
        (repo / name).write_text(text)
    _git(repo, "-C", str(repo), "add", "-A")
    _git(repo, "-C", str(repo), "commit", "-q", "-m", "head")
    return repo, diffs.changed_files(repo, "main", "head")


def _shadow_coverage(tmp_path):
    """A directory first on PYTHONPATH whose `coverage` import fails: the check must skip, not pass."""
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "coverage.py").write_text("raise ImportError('coverage is not installed here')\n")
    return shadow


def _run(repo, changes, **kw):
    kw.setdefault("env", {"PYTHONPATH": "."})
    kw.setdefault("python", sys.executable)
    kw.setdefault("timeout", 120.0)
    return line_coverage.check_line_coverage(repo, changes, **kw)


def test_trivial_lines_are_headers_pass_comments_and_imports_only():
    assert line_coverage.is_trivial("    pass") and line_coverage.is_trivial("# comment")
    assert line_coverage.is_trivial("def sub(a, b):") and line_coverage.is_trivial("from x import y")
    assert not line_coverage.is_trivial("    return a - b")


def test_source_text_test_is_rejected_because_the_changed_line_never_runs(tmp_path):
    repo, changes = _repo(tmp_path, SOURCE_ONLY_TEST)
    result = _run(repo, changes)
    assert result.name == "line_coverage" and result.status == FAIL, result
    assert any(r.startswith("lines_not_executed") and "mod.py" in r and "2" in r for r in result.reasons), result.reasons
    assert result.measured["files"]["mod.py"]["executed"] == 0


def test_test_that_calls_the_function_is_accepted(tmp_path):
    repo, changes = _repo(tmp_path, CALLS_TEST)
    result = _run(repo, changes)
    assert result.status == PASS, result
    assert result.measured["files"]["mod.py"]["executed"] >= 1


def test_missing_coverage_skips_with_the_reason_and_never_passes(tmp_path):
    repo, changes = _repo(tmp_path, CALLS_TEST)
    result = _run(repo, changes, env={"PYTHONPATH": f"{_shadow_coverage(tmp_path)}{os.pathsep}."})
    assert result.status == SKIPPED, result
    assert "coverage" in result.reasons[0] and "not installed" in result.reasons[0], result.reasons


def test_pr_without_production_python_is_skipped_not_run(tmp_path):
    repo, changes = _repo(tmp_path, CALLS_TEST, mod_text=BASE_MOD)
    changes = [c for c in changes if c.kind == "test"]
    result = _run(repo, changes)
    assert result.status == SKIPPED and "codigo de producao" in result.reasons[0], result


def test_a_crashing_run_is_an_error_not_a_pass(tmp_path):
    repo, changes = _repo(tmp_path, CALLS_TEST)
    result = _run(repo, changes, python="/nonexistent/python")
    assert result.status == ERROR and result.reasons, result


def test_a_one_line_def_is_not_a_trivial_header():
    # `def f(): return x` carries its body on the header line: it is behavior, not a header to skip
    assert not line_coverage.is_trivial("def sub(a, b): return a - b")
    assert line_coverage.is_trivial("async def run(self):")


def test_pragma_does_not_exclude_a_changed_line(tmp_path):
    # the PR author controls the pragma: the changed line is judged as if it had no comment
    repo, changes = _repo(tmp_path, SOURCE_ONLY_TEST, mod_text=HEAD_MOD.replace("a - b\n", "a - b  # pragma: no cover\n"))
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert any(r.startswith("lines_not_executed") and "mod.py" in r for r in result.reasons), result.reasons


@pytest.mark.parametrize("name,text", [
    (".coveragerc", "[report]\nexclude_also =\n    .*\n"),
    ("setup.cfg", "[coverage:report]\nexclude_also =\n    .*\n"),
    ("tox.ini", "[coverage:report]\nexclude_also =\n    .*\n"),
    ("pyproject.toml", '[tool.coverage.report]\nexclude_also = [".*"]\n'),
], ids=[".coveragerc", "setup.cfg", "tox.ini", "pyproject.toml"])
def test_coverage_config_shipped_by_the_pr_is_never_read(tmp_path, name, text):
    repo, changes = _repo(tmp_path, SOURCE_ONLY_TEST, extra={name: text})
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert any(r.startswith("lines_not_executed") and "mod.py" in r for r in result.reasons), result.reasons


FAKE_COVERAGE = textwrap.dedent('''\
    import json


    class Coverage:
        def __init__(self, **kwargs):
            pass

        def set_option(self, *args):
            pass

        def start(self):
            pass

        def stop(self):
            pass

        def json_report(self, outfile):
            with open(outfile, "w") as fh:
                json.dump({"files": {"mod.py": {"executed_lines": [1, 2], "missing_lines": []}}}, fh)
    ''')


def test_a_coverage_module_shipped_by_the_pr_cannot_fake_the_report(tmp_path):
    # `python -c` puts the cwd first on sys.path: a root coverage.py would replace the real module
    repo, changes = _repo(tmp_path, SOURCE_ONLY_TEST, extra={"coverage.py": FAKE_COVERAGE})
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert any(r.startswith("lines_not_executed") and "mod.py" in r for r in result.reasons), result.reasons


def test_changed_file_missing_from_the_report_counts_as_not_executed(tmp_path):
    repo, changes = _repo(tmp_path, CALLS_TEST)
    code = [c for c in changes if c.kind == "code"]
    result = line_coverage._judge(repo, code, {}, ["test_mod.py::test_sub_subtracts"])
    assert result.status == FAIL, result
    assert result.reasons[0].startswith("lines_not_executed") and "mod.py" in result.reasons[0], result.reasons


def test_module_level_run_does_not_cover_a_changed_function_body(tmp_path):
    # the import runs the new module-level constant; the changed function body is never called
    repo, changes = _repo(tmp_path, "from mod import SCALE\n\n\ndef test_scale():\n    assert SCALE == 2\n",
                          mod_text="SCALE = 2\n" + HEAD_MOD)
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert result.reasons[0].startswith("lines_not_executed") and "mod.py" in result.reasons[0], result.reasons


def test_a_one_line_def_is_not_proved_by_its_own_header(tmp_path):
    # the import runs the header line, which holds the body too, but the body is never called: line coverage cannot prove it
    repo, changes = _repo(tmp_path, "from mod import sub\n\n\ndef test_import_only():\n    assert sub is not None\n",
                          mod_text="def sub(a, b): return a - b\n")
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert any("def de uma linha" in r for r in result.reasons), result.reasons


def test_a_trivial_line_in_an_uncalled_body_is_not_judged(tmp_path):
    # kills an `is_trivial` that always answers False: the `pass` runs nowhere, yet it is not behavior
    repo, changes = _repo(tmp_path, "def test_nothing():\n    pass\n", mod_text="def sub(a, b):\n    pass\n    return b\n")
    result = _run(repo, changes)
    assert result.status == PASS, result


def test_no_new_test_is_a_named_failure(tmp_path):
    # kills the removal of the `if not ids` guard: without it the run has no test ids and fails with another reason
    repo, changes = _repo(tmp_path, "X = 1\n")
    result = _run(repo, changes)
    assert result.status == FAIL and "nenhum teste novo" in result.reasons[0], result


def test_a_pr_config_that_omits_the_changed_file_still_fails(tmp_path):
    # the omitted file is not in the report: it counts as not executed, never as ignored
    repo, changes = _repo(tmp_path, SOURCE_ONLY_TEST, extra={".coveragerc": "[run]\nomit =\n    mod.py\n"})
    result = _run(repo, changes)
    assert result.status == FAIL, result
    assert any(r.startswith("lines_not_executed") and "mod.py" in r for r in result.reasons), result.reasons
