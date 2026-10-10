"""Red-to-green check: the new tests must fail on main without the change and pass with it (Parte de #1649)."""
import sys
import textwrap

import pytest

from simplicio_loop.review_gate import diffs, redgreen
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, SKIPPED

OLD = "def add(a, b):\n    return a\n"
NEW = "def add(a, b):\n    return a + b\n"
TEST = textwrap.dedent('''\
    from mod import add


    def test_add_sums():
        assert add(1, 2) == 3


    def test_add_zero():
        assert add(0, 5) == 5


    def test_guard():
        """characterization: already true on main"""
        assert add(1, 0) == 1
    ''')


def _tree(root, mod, test):
    (root / "tests").mkdir(parents=True)
    (root / "mod.py").write_text(mod)
    (root / "tests" / "test_mod.py").write_text(test)
    return root


def _changes(test, mod=True):
    out = [diffs.FileChange("tests/test_mod.py", "A", tuple(range(1, test.count("\n") + 1)))]
    if mod:
        out.append(diffs.FileChange("mod.py", "M", (2,)))
    return out


def _run(tmp_path, base_mod, head_mod, test, **kw):
    base = _tree(tmp_path / "base", base_mod, "")
    head = _tree(tmp_path / "head", head_mod, test)
    kw.setdefault("env", {"PYTHONPATH": "."})
    kw.setdefault("python", sys.executable)
    return redgreen.check_redgreen(base, head, _changes(test), **kw)


def test_new_tests_in_names_and_lines():
    refs = redgreen.new_tests("tests/test_mod.py", TEST, range(8, 11))
    assert [r.name for r in refs] == ["test_add_zero"]
    assert [r.name for r in redgreen.new_tests("tests/test_mod.py", TEST, range(1, 99))] == [
        "test_add_sums", "test_add_zero", "test_guard"]


def test_new_tests_inside_class_get_the_class_in_the_node_id():
    src = "class TestX:\n    def test_a(self):\n        assert 1\n"
    (ref,) = redgreen.new_tests("tests/t.py", src, [3])
    assert ref.node_id == "tests/t.py::TestX::test_a"


def test_parse_outcomes_strips_params_and_marks_file_errors():
    out = "PASSED tests/a.py::test_x[1]\nFAILED tests/a.py::test_x[2] - boom\nERROR tests/b.py - ImportError\n"
    assert redgreen.parse_outcomes(out) == {"tests/a.py::test_x": "failed", "tests/b.py": "error"}


def test_vacuous_tests_are_rejected_with_the_list(tmp_path):
    result = _run(tmp_path, NEW, NEW, TEST)  # production already has the change on "main"
    assert result.status == FAIL
    assert any("test_add_sums" in r and "passam em main" in r for r in result.reasons)
    assert "tests/test_mod.py::test_add_sums" in result.measured["vacuous"]


def test_red_on_base_green_on_head_passes_and_characterization_is_exempt_but_listed(tmp_path):
    result = _run(tmp_path, OLD, NEW, TEST)
    assert result.status == PASS, result.reasons
    assert result.measured["red"] == ["tests/test_mod.py::test_add_sums", "tests/test_mod.py::test_add_zero"]
    assert result.measured["exempt"] == ["tests/test_mod.py::test_guard"]
    assert result.measured["head_failed"] == []


def test_a_test_that_fails_with_the_change_is_rejected(tmp_path):
    result = _run(tmp_path, OLD, OLD, TEST)  # change did not fix production
    assert result.status == FAIL and any("falham com a mudanca" in r for r in result.reasons)


def test_production_change_without_new_tests_fails(tmp_path):
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", NEW, "")
    result = redgreen.check_redgreen(base, head, [diffs.FileChange("mod.py", "M", (2,))], python=sys.executable)
    assert result.status == FAIL and "sem teste novo" in result.reasons[0]


def test_tests_only_and_docs_only_are_skipped_with_the_reason(tmp_path):
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", OLD, TEST)
    only_tests = redgreen.check_redgreen(base, head, _changes(TEST, mod=False), python=sys.executable)
    assert only_tests.status == SKIPPED and "so de testes" in only_tests.reasons[0]
    docs = redgreen.check_redgreen(base, head, [diffs.FileChange("docs/a.md", "M", (1,))], python=sys.executable)
    assert docs.status == SKIPPED and "sem codigo de producao" in docs.reasons[0]


def test_missing_interpreter_is_a_clear_error(tmp_path):
    result = _run(tmp_path, OLD, NEW, TEST, python="/nonexistent/python")
    assert result.status == ERROR and "/nonexistent/python" in result.reasons[0]


def test_timeout_is_an_error_with_the_cause(tmp_path):
    slow = "import time\n\n\ndef test_slow():\n    time.sleep(30)\n"
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", NEW, slow)
    changes = [diffs.FileChange("tests/test_mod.py", "A", (1, 2, 3, 4, 5)), diffs.FileChange("mod.py", "M", (2,))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, timeout=2, env={"PYTHONPATH": "."})
    assert result.status == ERROR and "timeout" in result.reasons[0]


def test_an_interpreter_the_sandbox_hides_is_named_with_the_cause(tmp_path):
    def hidden(argv):  # what bwrap does when the interpreter is outside its binds
        return ["sh", "-c", f"echo 'bwrap: execvp {argv[0]}: No such file or directory' >&2; exit 1"]

    result = _run(tmp_path, OLD, NEW, TEST, python="/tmp/venv/bin/python", wrap=hidden)
    assert result.status == ERROR
    assert "/tmp/venv/bin/python is not visible inside the sandbox" in result.reasons[0] and "/usr or /opt" in result.reasons[0]


def test_other_pytest_crashes_keep_their_own_message(tmp_path):
    result = _run(tmp_path, OLD, NEW, TEST, wrap=lambda argv: ["sh", "-c", "echo boom >&2; exit 3"])
    assert result.status == ERROR and "exited 3" in result.reasons[0] and "sandbox" not in result.reasons[0]
