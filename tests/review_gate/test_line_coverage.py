"""Line-execution check: the new tests must EXECUTE the changed production lines (Parte de #1649, finding m3).

A test that reads the source text (`"return a - b" in src`) passes without running the code it names, so it proves nothing.
Each test here builds a real git repo with one commit on `main` and one on `head`, and runs the check on the head tree.
"""
import os
import subprocess
import sys
import textwrap

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


def _repo(tmp_path, test_text, mod_text=HEAD_MOD):
    """A git repo: `main` has BASE_MOD, `head` changes mod.py and adds tests/test_mod.py. Returns (repo, changes)."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main", str(repo))
    (repo / "mod.py").write_text(BASE_MOD)
    _git(repo, "-C", str(repo), "add", "-A")
    _git(repo, "-C", str(repo), "commit", "-q", "-m", "base")
    _git(repo, "-C", str(repo), "checkout", "-q", "-b", "head")
    (repo / "mod.py").write_text(mod_text)
    (repo / "tests" / "test_mod.py").write_text(test_text)
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
