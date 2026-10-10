"""Red-to-green check: the new tests must fail on main without the change and pass with it (Parte de #1649)."""
import sys
import textwrap

import pytest

from simplicio_loop.review_gate import diffs, mutation, redgreen
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


def test_tests_only_runs_the_tests_on_the_head_and_docs_only_is_skipped_with_the_reason(tmp_path):
    base = _tree(tmp_path / "base", NEW, "")
    head = _tree(tmp_path / "head", NEW, TEST)
    only_tests = redgreen.check_redgreen(base, head, _changes(TEST, mod=False), python=sys.executable, env={"PYTHONPATH": "."})
    assert only_tests.status == PASS and only_tests.measured["mode"] == "tests_only" and only_tests.measured["tests"] == 3
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


def test_novo_teste_importa_modulo_que_so_existe_com_a_mudanca_e_vermelho_em_main(tmp_path):
    """The test imports `dead`, which main does not have: on main the file fails to import, and that is red, not an error."""
    test = "from dead import double\n\n\ndef test_double():\n    assert double(2) == 4\n"
    base = tmp_path / "base"
    head = tmp_path / "head"
    for root, extra in ((base, {}), (head, {"dead.py": "def double(x):\n    return x * 2\n", "tests/test_mod.py": test})):
        (root / "tests").mkdir(parents=True)
        for name, text in extra.items():
            (root / name).write_text(text)
    changes = [diffs.FileChange("dead.py", "A", (1, 2)), diffs.FileChange("tests/test_mod.py", "A", (1, 2, 3, 4, 5))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons
    assert result.measured["red"] == ["tests/test_mod.py::test_double"]
    assert result.measured["vacuous"] == [] and result.measured["head_failed"] == []


def test_arquivo_que_nao_importa_em_main_nao_esconde_o_teste_vacuo_de_outro_arquivo(tmp_path):
    """One file fails to import on main; the vacuous test of the other file still runs there and is reported."""
    head_files = {"dead.py": "def double(x):\n    return x * 2\n", "mod.py": NEW,
                  "tests/test_a.py": "from dead import double\n\n\ndef test_double():\n    assert double(2) == 4\n",
                  "tests/test_b.py": "from mod import add\n\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n"}
    for root, files in ((tmp_path / "base", {"mod.py": OLD}), (tmp_path / "head", head_files)):
        (root / "tests").mkdir(parents=True)
        for name, text in files.items():
            (root / name).write_text(text)
    changes = [diffs.FileChange("dead.py", "A", (1, 2)), diffs.FileChange("mod.py", "M", (2,)),
               diffs.FileChange("tests/test_a.py", "A", (1, 2, 3, 4, 5)), diffs.FileChange("tests/test_b.py", "A", (1, 2, 3, 4, 5))]
    result = redgreen.check_redgreen(tmp_path / "base", tmp_path / "head", changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == FAIL, result.reasons
    assert result.measured["vacuous"] == ["tests/test_b.py::test_add_zero"]
    assert result.measured["red"] == ["tests/test_a.py::test_double"]


def test_conftest_is_never_read_for_tests(tmp_path):
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", NEW, TEST)
    (head / "tests" / "conftest.py").write_text("def test_helper_that_is_not_a_test():\n    raise SystemExit(9)\n")
    changes = [*_changes(TEST), diffs.FileChange("tests/conftest.py", "A", (1, 2))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons
    assert result.measured["tests"] == 3  # the three tests of test_mod.py, none from conftest.py


def test_a_test_file_that_does_not_parse_is_an_error_with_its_path(tmp_path):
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", NEW, "def test_broken(:\n    pass\n")
    result = redgreen.check_redgreen(base, head, _changes("x\ny\n"), python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == ERROR and result.reasons[0].startswith("cannot read the tests of tests/test_mod.py: ")


def test_only_characterization_tests_new_means_nothing_fails_on_main_and_is_rejected(tmp_path):
    only_exempt = 'from mod import add\n\n\ndef test_guard():\n    """characterization: already true on main"""\n    assert add(1, 0) == 1\n'
    result = _run(tmp_path, OLD, NEW, only_exempt)
    assert result.status == FAIL and result.reasons == ("nenhum teste novo falha em main: todos sao isentos (characterization)",)
    assert result.measured["exempt"] == ["tests/test_mod.py::test_guard"] and result.measured["red"] == []


def test_failing_head_tests_are_listed_by_id(tmp_path):
    result = _run(tmp_path, OLD, OLD, TEST)
    (reason,) = [r for r in result.reasons if "falham com a mudanca" in r]
    assert "tests/test_mod.py::test_add_sums" in reason and "tests/test_mod.py::test_add_zero" in reason
    assert result.measured["head_failed"] == ["tests/test_mod.py::test_add_sums", "tests/test_mod.py::test_add_zero"]


def test_the_trees_get_no_pytest_cache_and_no_bytecode(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)  # the gate itself must switch it off for the pytest it runs
    result = _run(tmp_path, OLD, NEW, TEST)
    assert result.status == PASS
    for tree in (tmp_path / "base", tmp_path / "head"):
        assert not (tree / ".pytest_cache").exists() and list(tree.rglob("__pycache__")) == []


def test_verdict_prefers_the_test_then_its_file_then_missing():
    ref = redgreen.TestRef("tests/t.py", "test_a", None, False)
    assert redgreen._verdict({"tests/t.py::test_a": "passed", "tests/t.py": "error"}, ref) == "passed"
    assert redgreen._verdict({"tests/t.py::test_a": "failed"}, ref) == "failed"
    assert redgreen._verdict({"tests/t.py": "error"}, ref) == "error"
    assert redgreen._verdict({"tests/other.py::test_a": "passed", "tests/other.py": "passed"}, ref) == "missing"
    assert redgreen._verdict({}, ref) == "missing"


def test_new_tests_sees_decorators_nested_classes_and_the_exempt_word_in_name_or_docstring():
    src = textwrap.dedent('''\
        import pytest


        @pytest.mark.parametrize("x", [1, 2])
        def test_decorated(x):
            assert x


        class TestOuter:
            class TestInner:
                def test_deep(self):
                    """Characterization of the old behavior"""

            def helper_not_a_test(self):
                pass

            async def test_async(self):
                pass


        class Helper:
            def test_not_collected(self):
                pass


        def test_characterization_by_name():
            pass
        ''')
    every = {r.node_id: r.exempt for r in redgreen.new_tests("tests/t.py", src, range(1, 99))}
    assert every == {"tests/t.py::test_decorated": False, "tests/t.py::TestOuter::TestInner::test_deep": True,
                     "tests/t.py::TestOuter::test_async": False, "tests/t.py::test_characterization_by_name": True}
    only_decorator_line = redgreen.new_tests("tests/t.py", src, [4])
    assert [r.name for r in only_decorator_line] == ["test_decorated"]  # a changed decorator counts as a changed test
    assert redgreen.new_tests("tests/t.py", src, [1]) == []


def test_parse_outcomes_ignores_other_lines_and_a_pass_never_hides_a_failure_of_a_parametrized_test():
    out = ("collected 3 items\nPASSED tests/a.py::test_x[1]\nFAILED tests/a.py::test_x[2] - boom\nPASSED tests/a.py::test_x[3]\n"
           "ERROR tests/b.py::test_y\nSKIPPED [1] tests/c.py:3: because\n1 failed, 2 passed in 0.1s\n")
    assert redgreen.parse_outcomes(out) == {"tests/a.py::test_x": "failed", "tests/b.py::test_y": "error"}
    assert redgreen.parse_outcomes("PASSED tests/a.py::test_x\nPASSED tests/a.py::test_x[1]\n") == {"tests/a.py::test_x": "passed"}


def test_an_error_of_a_parametrized_case_is_not_hidden_by_a_later_pass():
    out = "ERROR tests/b.py::test_y[1] - boom\nPASSED tests/b.py::test_y[2]\n"
    assert redgreen.parse_outcomes(out) == {"tests/b.py::test_y": "error"}


def test_pytest_exit_2_with_an_error_line_is_a_verdict_and_without_one_a_crash(tmp_path):
    def fake(line, code):
        return lambda argv: ["sh", "-c", f"printf '%s\\n' '{line}'; exit {code}"]

    erroring = _run(tmp_path, OLD, NEW, TEST, wrap=fake("ERROR tests/test_mod.py - ImportError", 2))
    assert erroring.status == FAIL and any("falham com a mudanca" in r for r in erroring.reasons)  # the head file did not import
    silent = _run(tmp_path / "b", OLD, NEW, TEST, wrap=fake("interrupted", 2))
    assert silent.status == ERROR and "exited 2" in silent.reasons[0]


CHAR_FAILING = 'from mod import add\n\n\ndef test_char_sum():\n    """characterization: declared true on main"""\n    assert add(1, 2) == 3\n'


def test_a_characterization_test_that_is_red_on_main_is_exempt_and_is_not_listed_red(tmp_path):
    test = TEST + "\n\n" + CHAR_FAILING.split("\n\n\n", 1)[1]
    result = _run(tmp_path, OLD, NEW, test)
    assert result.status == PASS, result.reasons
    assert result.measured["red"] == ["tests/test_mod.py::test_add_sums", "tests/test_mod.py::test_add_zero"]
    assert result.measured["exempt"] == ["tests/test_mod.py::test_guard", "tests/test_mod.py::test_char_sum"]


def test_only_exempt_tests_that_fail_on_head_give_the_head_reason_alone(tmp_path):
    result = _run(tmp_path, OLD, OLD, CHAR_FAILING)  # exempt, red on main, and still red with the change
    assert result.status == FAIL
    assert len(result.reasons) == 1 and result.reasons[0].startswith("testes novos que falham com a mudanca: ")
    assert result.measured["head_failed"] == ["tests/test_mod.py::test_char_sum"] and result.measured["red"] == []


NOT_PYTHON = "production change is not Python: no behavior check ran"


def test_a_skip_caused_by_non_python_production_says_so_and_a_real_tests_only_pr_keeps_its_text(tmp_path):
    js = diffs.FileChange("web/app.js", "M", (1,))
    conftest = diffs.FileChange("tests/conftest.py", "M", (1,))
    base, head = tmp_path / "base", tmp_path / "head"
    for changes in ([js], [js, conftest], [js, diffs.FileChange("tests/test_mod.py", "D", ())]):  # nothing runs: not a "tests only" PR
        result = redgreen.check_redgreen(base, head, changes, python=sys.executable)
        assert result.status == SKIPPED and result.reasons[0].startswith(NOT_PYTHON) and "web/app.js" in result.reasons[0], changes
    tests_only = redgreen.check_redgreen(base, head, [conftest], python=sys.executable)
    assert tests_only.status == SKIPPED and tests_only.reasons[0].startswith("PR so de testes sem teste novo")
    docs = redgreen.check_redgreen(base, head, [diffs.FileChange("docs/a.md", "M", (1,))], python=sys.executable)
    assert docs.status == SKIPPED and docs.reasons[0] == "sem codigo de producao nem teste alterado"
    deleted = redgreen.check_redgreen(base, head, [diffs.FileChange("web/app.js", "D", ())], python=sys.executable)
    assert deleted.reasons[0] == "sem codigo de producao nem teste alterado"  # a deleted file is not a production change that went unchecked


# Attribution (#1649): the red set of the real red/green run feeds the mutation sample, and each new test that fails on main must kill a mutant.
# The mutants of `mod.py` line 2 are `return a - b` (flip) and `return None`; the test run is a fake that names which tests fail for each.
TWO_NEW = textwrap.dedent('''\
    from mod import add


    def test_add_sums():
        assert add(1, 2) == 3


    def test_add_zero():
        assert add(0, 5) == 5
    ''')
CHARACTERIZED = TWO_NEW.replace("def test_add_zero():", 'def test_add_zero_characterization():\n    """characterization: declared as already true on main"""')


def _attribute(tmp_path, monkeypatch, test, kills):
    """The red/green result of `test` over OLD and the mutation sample over NEW; `kills(mutated_text)` names the tests that fail."""
    base = _tree(tmp_path / "base", OLD, "")
    head = _tree(tmp_path / "head", NEW, test)
    changes = _changes(test)
    red = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})

    def run(root, argv, timeout, wrap, env, home):
        text = (root / "mod.py").read_text(encoding="utf-8")
        failed = [] if text == NEW else list(kills(text))
        return (1 if failed else 0), "".join(f"FAILED {node} - assert 0\n" for node in failed)

    monkeypatch.setattr(mutation, "_run", run)
    sampled = mutation.check_mutation(head, changes, [sys.executable, "-m", "pytest", "tests"], n=12, seed="s", red=red.measured["red"])
    return red, sampled


def _kill_by_op(add_fails, none_fails):
    return lambda text: add_fails if "a - b" in text else none_fails


def test_a_new_test_that_fails_on_main_and_kills_no_mutant_is_rejected_with_its_id(tmp_path, monkeypatch):
    red, sampled = _attribute(tmp_path, monkeypatch, TWO_NEW,
                              _kill_by_op(["tests/test_mod.py::test_add_sums"], ["tests/test_mod.py::test_add_sums"]))
    assert red.status == PASS and red.measured["red"] == ["tests/test_mod.py::test_add_sums", "tests/test_mod.py::test_add_zero"]
    assert sampled.status == FAIL and sampled.reasons[-1].startswith("test_kills_no_mutant:")
    assert "tests/test_mod.py::test_add_zero" in sampled.reasons[-1] and "test_add_sums" not in sampled.reasons[-1]


def test_a_new_test_that_fails_on_main_and_kills_a_mutant_is_attributed_and_passes(tmp_path, monkeypatch):
    _, sampled = _attribute(tmp_path, monkeypatch, TWO_NEW,
                            _kill_by_op(["tests/test_mod.py::test_add_sums"], ["tests/test_mod.py::test_add_zero"]))
    assert sampled.status == PASS, sampled.reasons
    assert sampled.measured["unattributed"] == []


def test_a_characterization_test_is_exempt_from_the_kill_rule(tmp_path, monkeypatch):
    red, sampled = _attribute(tmp_path, monkeypatch, CHARACTERIZED,
                              _kill_by_op(["tests/test_mod.py::test_add_sums"], ["tests/test_mod.py::test_add_sums"]))
    assert red.measured["exempt"] == ["tests/test_mod.py::test_add_zero_characterization"]
    assert red.measured["red"] == ["tests/test_mod.py::test_add_sums"] and sampled.status == PASS, sampled.reasons

