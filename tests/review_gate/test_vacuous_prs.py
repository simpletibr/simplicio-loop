"""The gate does not approve a vacuous PR: empty, tests that cannot fail or never run, docs or scripts as proof (Parte de #1649, round 6)."""
from __future__ import annotations

import sys
import textwrap

import pytest

from simplicio_loop.review_gate import coverage, diffs, gate, identity, redgreen, vacuity
from simplicio_loop.review_gate.diffs import FileChange
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, SKIPPED
from tests.review_gate import scenario

WORKER = identity.Agent("worker-1", "worker", "haiku-5.5", "local")
ISSUE = "- [ ] o cliente de fetch faz retry\n- [ ] o cliente registra log do retry\n"
CLOSES = "Closes #5"


def _src(text: str) -> str:
    return textwrap.dedent(text)


# --- vacuity: which tests can fail ------------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "assert True", "assert 1", 'assert "x"', "assert 1 == 1", "assert not False", "assert (1, 2)", "assert 'a' in 'abc'",
    "pass", "...", "print('ok')", "'''only a docstring'''", "x = 1", "assert True\n    assert 1", "foo()",
    "import os\n    print(os.name)", "assert (x, 'message')",
    "validate_input(5)", "check_output(x)", "verify_all(x)", "expect_ok(x)", "ensure_ready(x)", "result = validate_input(5)",
])
def test_a_test_that_cannot_fail_is_vacuous(body):
    (func,) = vacuity.analyze(f"def test_a():\n    {body}\n")
    assert func.vacuous and not func.usable


@pytest.mark.parametrize("body", [
    "assert x == 1", "assert x", "assert False", "assert foo()", "assert 1 == 2", "raise AssertionError('no')", "self.assertEqual(1, x)",
    "with pytest.raises(ValueError):\n        foo()", "pytest.fail('x')", "mock.assert_called_once()",
    "assert True\n    assert x > 0",
])
def test_a_test_with_an_assertion_that_can_fail_is_not_vacuous(body):
    (func,) = vacuity.analyze(f"def test_a():\n    {body}\n")
    assert not func.vacuous and func.usable


def test_a_call_of_a_helper_of_the_module_that_asserts_counts_and_one_that_does_not_assert_does_not():
    src = _src("""
        def same(a, b):
            assert a == b

        def noop(a):
            return a

        def test_a():
            same(1, 2)

        def test_b():
            noop(1)
        """)
    a, b = vacuity.analyze(src)
    assert not a.vacuous and b.vacuous


@pytest.mark.parametrize("head", [
    "@pytest.mark.skip(reason='later')\ndef test_a():\n    assert False\n",
    "@pytest.mark.skip\ndef test_a():\n    assert False\n",
    "@pytest.mark.xfail\ndef test_a():\n    assert False\n",
    "@pytest.mark.skipif(True, reason='x')\ndef test_a():\n    assert False\n",
    "@unittest.skip('x')\ndef test_a():\n    assert False\n",
    "def test_a():\n    pytest.skip('x')\n    assert False\n",
    "pytestmark = pytest.mark.skip\ndef test_a():\n    assert False\n",
    "pytestmark = [pytest.mark.xfail]\ndef test_a():\n    assert False\n",
    "@pytest.mark.skip\nclass TestX:\n    def test_a(self):\n        assert False\n",
    "class TestX:\n    pytestmark = pytest.mark.skip\n    def test_a(self):\n        assert False\n",
])
def test_a_test_that_is_skipped_or_xfail_is_not_usable(head):
    (func,) = vacuity.analyze(head)
    assert func.skipped and not func.usable and not func.vacuous


@pytest.mark.parametrize("head", [
    "@pytest.mark.skipif(False, reason='x')\ndef test_a():\n    assert x\n",
    "@pytest.mark.skipif(sys.platform == 'win32', reason='x')\ndef test_a():\n    assert x\n",
    "@pytest.mark.parametrize('x', [1])\ndef test_a(x):\n    assert x\n",
    "def test_a():\n    if x:\n        pytest.skip('x')\n    assert x\n",
])
def test_a_condition_that_is_not_a_true_constant_does_not_skip(head):
    (func,) = vacuity.analyze(head)
    assert not func.skipped and func.usable


def test_methods_of_classes_get_the_class_in_their_name_and_unittest_cases_count():
    funcs = vacuity.analyze("class TestA:\n    def test_x(self):\n        assert 1 == 2\n\nclass FooTests(unittest.TestCase):\n"
                            "    def test_y(self):\n        self.assertTrue(x)\n\nclass Helper:\n    def test_z(self):\n        assert x\n")
    assert [f.qualname for f in funcs] == ["TestA::test_x", "FooTests::test_y"]
    assert [f.vacuous for f in funcs] == [False, False]


def test_the_terms_of_a_test_are_name_docstring_identifiers_and_strings_but_not_comments():
    (func,) = vacuity.analyze('def test_a():\n    """registra log"""\n    # retry em comentario\n    assert fetch(url="http://x") == "ok"\n')
    assert "registra log" in func.terms and "fetch" in func.terms and "url" in func.terms and "ok" in func.terms
    assert "retry" not in func.terms and "comentario" not in func.terms


# --- coverage: what counts as evidence --------------------------------------------------------------------------------


def _cov(files, issue_body=ISSUE, pr_body=CLOSES, whole=True, issue=5):
    """files: {path: (status, text)}; a test file is passed whole as `sources` (what the gate does) unless `whole` is False."""
    changes = [FileChange(p, st, tuple(range(1, text.count("\n") + 1))) for p, (st, text) in files.items()]
    added = {p: text for p, (st, text) in files.items() if st != "D"}
    sources = {p: text for p, (st, text) in files.items() if diffs.kind_of(p) == "test"} if whole else None
    return coverage.check_coverage(issue, issue_body, changes, added, pr_body, sources=sources)


VACUOUS_TEST = "def test_retry_do_cliente_de_fetch_registra_log():\n    assert True\n"
PROD = ("A", "answer = 42\n")  # Python production no criterion here is about: a test is evidence only next to production
REAL_TEST = ("def test_retry_do_cliente_de_fetch_registra_log():\n    client = FetchClient(retries=2)\n"
             "    assert client.fetch('http://x').attempts == 2\n    assert client.log == ['retry 1', 'retry 2']\n")


@pytest.mark.parametrize("whole", [True, False])
def test_s1_a_test_whose_name_repeats_the_criterion_but_asserts_true_is_no_evidence(whole):
    result = _cov({"tests/test_fetch.py": ("A", VACUOUS_TEST)}, whole=whole)
    assert result.status == FAIL and len(result.measured["uncovered"]) == 2
    assert any(r.startswith("no_evidence") for r in result.reasons)
    assert _cov({"tests/test_fetch.py": ("A", REAL_TEST), "src/other.py": PROD}, whole=whole).status == PASS


@pytest.mark.parametrize("body", ["assert 1", "assert 'x'", "pass", "...", "print('retry registra log')", "assert 1 == 1"])
def test_every_constant_or_empty_body_is_no_evidence_even_with_the_words_in_the_name(body):
    text = f"def test_retry_do_cliente_de_fetch_registra_log():\n    {body}\n"
    assert _cov({"tests/test_fetch.py": ("A", text)}).status == FAIL


def test_the_words_must_be_in_the_name_docstring_or_body_of_the_test_that_asserts_and_not_in_a_comment():
    comment = "def test_algo():\n    # retry do cliente de fetch registra log\n    assert compute() == 3\n"
    assert _cov({"tests/test_x.py": ("A", comment)}).status == FAIL
    doc = 'def test_algo():\n    """o cliente de fetch faz retry e registra log do retry"""\n    assert compute() == 3\n'
    assert _cov({"tests/test_x.py": ("A", doc), "src/other.py": PROD}).status == PASS
    body = "def test_algo():\n    assert compute('cliente fetch retry registra log') == 3\n"
    assert _cov({"tests/test_x.py": ("A", body), "src/other.py": PROD}).status == PASS


def test_a_vacuous_test_next_to_a_real_one_gives_evidence_only_through_the_real_one():
    text = VACUOUS_TEST + "\n\ndef test_outro():\n    assert compute() == 3\n"
    result = _cov({"tests/test_fetch.py": ("A", text)})
    assert result.status == FAIL
    both = REAL_TEST + "\n\n" + "def test_retry_vazio():\n    assert True\n"
    result = _cov({"tests/test_fetch.py": ("A", both), "src/other.py": PROD})
    assert result.status == PASS
    assert all("test_retry_vazio" not in label for labels in result.measured["evidence"].values() for label in labels)


def test_s2_skipped_tests_with_a_failing_assert_are_no_evidence():
    text = ("import pytest\n\n\n@pytest.mark.skip(reason='later')\ndef test_retry_do_cliente_de_fetch():\n    assert False\n\n\n"
            "@pytest.mark.skip\ndef test_cliente_registra_log_do_retry():\n    assert False\n")
    assert _cov({"tests/test_fetch.py": ("A", text)}).status == FAIL


def test_a_criterion_that_only_asks_for_a_test_needs_a_usable_one():
    issue = "- [ ] adicionar testes\n"
    assert _cov({"tests/test_x.py": ("A", "def test_x():\n    assert True\n")}, issue_body=issue).status == FAIL
    assert _cov({"tests/test_x.py": ("A", "def test_x():\n    assert compute() == 3\n")}, issue_body=issue).status == PASS


def test_a_cited_symbol_in_a_test_file_with_no_usable_test_is_not_evidence():
    issue = "- [ ] `fetch_with_retry` faz retry\n"
    vacuous = {"tests/test_x.py": ("A", "def test_x():\n    fetch_with_retry\n    assert True\n")}
    assert _cov(vacuous, issue_body=issue).status == FAIL


def test_s10_documentation_is_no_evidence_of_behavior():
    docs = {"docs/RETRY.md": ("A", "# Retry\n\nO cliente de fetch faz retry e registra log do retry.\n")}
    result = _cov(docs)
    assert result.status == FAIL and any(r.startswith("no_evidence") for r in result.reasons)
    assert len(result.measured["uncovered"]) == 2


def test_documentation_is_evidence_when_every_criterion_asks_for_documentation():
    docs = {"docs/RETRY.md": ("A", "# Retry\n\nO cliente de fetch faz retry e registra log do retry.\n")}
    for issue in ("- [ ] documentar o retry do cliente de fetch\n", "- [ ] atualizar o README com o retry do cliente de fetch\n",
                  "- [ ] escrever um ADR sobre o retry do cliente de fetch\n", "- [ ] update the docs about the fetch client retry\n",
                  "- [ ] retry do cliente de fetch em `docs/RETRY.md`\n", "- [ ] documentação do retry do cliente de fetch\n"):
        assert _cov(docs, issue_body=issue).status == PASS, issue


def test_a_mixed_issue_needs_evidence_for_the_behavior_criterion():
    docs = {"docs/RETRY.md": ("A", "# Retry\n\nO cliente de fetch faz retry e registra log do retry.\n")}
    issue = "- [ ] documentar o retry do cliente de fetch\n- [ ] o cliente de fetch registra log do retry\n"
    result = _cov(docs, issue_body=issue)
    assert result.status == FAIL and result.measured["uncovered"] == ["o cliente de fetch registra log do retry"]


def test_a_docs_only_pr_that_says_it_is_partial_and_lists_what_is_missing_is_honest():
    docs = {"docs/RETRY.md": ("A", "# Retry\n\nO cliente de fetch faz retry e registra log do retry.\n")}
    body = "Parte de #5\n\nFalta:\n- [ ] o cliente de fetch faz retry\n- [ ] o cliente registra log do retry\n"
    result = _cov(docs, pr_body=body)
    assert result.status == PASS and result.measured["partial"] is True


@pytest.mark.parametrize("path", ["scripts/retry.sh", "web/fetch.js", ".ci/run.yml", "tools/conf.toml", "app/main.ts"])
@pytest.mark.parametrize("issue_body", [ISSUE, ""])
def test_s8_non_python_production_without_a_usable_test_is_no_evidence_with_or_without_a_checklist(path, issue_body):
    result = _cov({path: ("A", "echo retry registra log\n")}, issue_body=issue_body)
    assert result.status == FAIL and result.reasons[0].startswith("no_evidence")
    assert result.measured["reason_code"] == "no_evidence" and result.measured["other"] == [path]


def test_no_evidence_also_without_an_issue_and_with_a_vacuous_test_beside_the_script():
    files = {"scripts/retry.sh": ("A", "echo x\n"), "tests/test_retry.py": ("A", "def test_retry():\n    assert True\n")}
    assert _cov(files, issue=None).status == FAIL
    real = {"scripts/retry.sh": ("A", "echo x\n"), "tests/test_retry.py": ("A", "def test_retry():\n    assert run_script() == 0\n")}
    assert _cov(real, issue=None).status == SKIPPED


@pytest.mark.parametrize("path", ["docs/a.md", "data/table.dat", ".gitignore", "assets/logo.png", "LICENSE"])
def test_files_that_are_not_production_code_are_not_no_evidence_by_themselves(path):
    assert _cov({path: ("A", "x\n")}, issue=None).status == SKIPPED


def test_a_deleted_script_is_not_production_added():
    assert _cov({"scripts/old.sh": ("D", "")}, issue=None).status == SKIPPED


def test_python_production_with_a_test_that_asserts_is_still_covered():
    files = {"src/fetch_client.py": ("A", "class FetchClient:\n    def fetch_retry(self, retries):\n        return retries\n"),
             "tests/test_fetch.py": ("A", REAL_TEST)}
    assert _cov(files).status == PASS


# --- redgreen: a PR of tests only must run its tests -------------------------------------------------------------------

MOD = "def add(a, b):\n    return a + b\n"


def _trees(tmp_path, test):
    for name in ("base", "head"):
        (tmp_path / name / "tests").mkdir(parents=True)
        (tmp_path / name / "mod.py").write_text(MOD)
    (tmp_path / "head" / "tests" / "test_mod.py").write_text(test)
    return tmp_path / "base", tmp_path / "head"


def _only_tests(tmp_path, test):
    base, head = _trees(tmp_path, test)
    changes = [FileChange("tests/test_mod.py", "A", tuple(range(1, test.count("\n") + 1)))]
    return redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})


GOOD = "from mod import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def test_tests_only_pr_runs_the_tests_and_passes_when_they_pass(tmp_path):
    result = _only_tests(tmp_path, GOOD)
    assert result.status == PASS, result.reasons
    assert result.measured["mode"] == "tests_only" and result.measured["tests"] == 1 and result.measured["not_run"] == []


def test_tests_only_pr_fails_when_a_test_fails_on_the_head(tmp_path):
    result = _only_tests(tmp_path, GOOD.replace("== 3", "== 4"))
    assert result.status == FAIL and "falham" in result.reasons[0] and "tests/test_mod.py::test_add" in result.reasons[0]


@pytest.mark.parametrize("test", [
    "import pytest\n\n\n@pytest.mark.skip(reason='later')\ndef test_a():\n    assert False\n",
    "import pytest\n\n\n@pytest.mark.xfail\ndef test_a():\n    assert False\n",
    "import pytest\n\n\n@pytest.mark.xfail\ndef test_a():\n    assert True\n",
    "import pytest\n\n\ndef test_a():\n    pytest.skip('x')\n",
    "import pytest\n\n\n@pytest.mark.skipif(True, reason='x')\ndef test_a():\n    assert 1 == 1\n",
    "import pytest\n\npytestmark = pytest.mark.skip\n\n\ndef test_a():\n    assert False\n",
    "from not_there import nothing\n\n\ndef test_a():\n    assert nothing\n",
])
def test_tests_only_pr_with_a_skipped_xfail_or_uncollectable_test_is_tests_not_run(tmp_path, test):
    result = _only_tests(tmp_path, test)
    assert result.status == FAIL and result.reasons[0].startswith("tests_not_run"), result.reasons
    assert result.measured["not_run"]


def test_tests_only_pr_where_only_one_parameter_is_skipped_is_tests_not_run(tmp_path):
    test = ("import pytest\n\n\n@pytest.mark.parametrize('x', [1, pytest.param(2, marks=pytest.mark.skip)])\n"
            "def test_a(x):\n    assert x\n")
    result = _only_tests(tmp_path, test)
    assert result.status == FAIL and result.reasons[0].startswith("tests_not_run")


@pytest.mark.parametrize("body", ["assert True", "assert 1", "pass", "print('ok')", "assert 'x'"])
def test_tests_only_pr_with_a_vacuous_test_is_rejected(tmp_path, body):
    result = _only_tests(tmp_path, f"def test_retry_registra_log():\n    {body}\n")
    assert result.status == FAIL and any(r.startswith("vacuous_test") for r in result.reasons)
    assert result.measured["vacuous_tests"] == ["tests/test_mod.py::test_retry_registra_log"]


def test_tests_only_pr_with_a_file_that_has_no_test_function_is_tests_not_run(tmp_path):
    result = _only_tests(tmp_path, "def helper():\n    return 1\n")
    assert result.status == FAIL and result.reasons[0].startswith("tests_not_run")


def test_tests_only_pr_that_only_deletes_lines_or_touches_a_conftest_has_no_test_to_run(tmp_path):
    base, head = _trees(tmp_path, GOOD)
    assert redgreen.check_redgreen(base, head, [FileChange("tests/test_mod.py", "M", (), 3)], python=sys.executable).status == SKIPPED
    conf = [FileChange("tests/conftest.py", "A", (1,))]
    assert redgreen.check_redgreen(base, head, conf, python=sys.executable).status == SKIPPED


def test_tests_only_pr_runs_under_the_pytest_infrastructure_of_main(tmp_path):
    base, head = _trees(tmp_path, GOOD)
    (head / "tests" / "conftest.py").write_text("import pytest\n\n\ndef pytest_collection_modifyitems(items):\n    items.clear()\n")
    changes = [FileChange("tests/test_mod.py", "A", (1, 2, 3, 4, 5)), FileChange("tests/conftest.py", "A", (1,))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == PASS, result.reasons  # the conftest of the PR is replaced by main's (none), so the test runs


def test_a_pr_with_production_and_a_skipped_new_test_is_tests_not_run_too(tmp_path):
    test = "import pytest\nfrom mod import add\n\n\n@pytest.mark.skip\ndef test_add():\n    assert add(1, 2) == 3\n"
    base, head = _trees(tmp_path, test)
    (base / "mod.py").write_text("def add(a, b):\n    return a\n")
    changes = [FileChange("tests/test_mod.py", "A", tuple(range(1, 8))), FileChange("mod.py", "M", (2,))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."})
    assert result.status == FAIL and any(r.startswith("tests_not_run") for r in result.reasons)


def test_a_pr_that_only_refactors_a_test_helper_runs_the_tests_that_import_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    scenario.git(repo, "init", "-q", "-b", "main")
    scenario._write(repo, {"mod.py": MOD, "tests/helpers.py": "def expected():\n    return 3\n",
                           "tests/test_uses_helper.py": "from mod import add\nfrom tests.helpers import expected\n\n\n"
                                                        "def test_add():\n    assert add(1, 2) == expected()\n"})
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    base = scenario.git(repo, "rev-parse", "HEAD")
    scenario.git(repo, "checkout", "-q", "-b", "loop/issue-5")
    scenario._write(repo, {"tests/helpers.py": "def _three():\n    return 3\n\n\ndef expected():\n    return _three()\n"})
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "head")
    head = scenario.git(repo, "rev-parse", "HEAD")
    report = gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=5, issue_body=ISSUE, pr_body=CLOSES, base=base, head=head,
                                          author=WORKER, wrap_for=scenario.UNSANDBOXED, n_mutants=2))
    red = next(c for c in report.checks if c.name == "redgreen")
    assert red.status == PASS, red.reasons
    assert red.measured["mode"] == "helper_neighbors" and red.measured["tests"] == 1 and red.measured["head_failed"] == []


def test_a_test_helper_refactor_that_breaks_a_test_that_imports_it_fails_the_pr(tmp_path):
    base, head = _trees(tmp_path, GOOD)
    (base / "tests" / "helpers.py").write_text("def expected():\n    return 3\n")
    (head / "tests" / "helpers.py").write_text("def expected():\n    return 4\n")
    (head / "tests" / "test_uses_helper.py").write_text("from tests.helpers import expected\n\n\ndef test_uses():\n"
                                                        "    assert expected() == 3\n")
    changes = [FileChange("tests/helpers.py", "M", (1,))]
    result = redgreen.check_redgreen(base, head, changes, python=sys.executable, env={"PYTHONPATH": "."},
                                     neighbours=["tests/test_uses_helper.py"])
    assert result.status == FAIL and "tests/test_uses_helper.py" in result.reasons[0], result.reasons


def test_parse_not_run_reads_skips_xfails_and_the_summary():
    out = ("SKIPPED [1] tests/test_a.py:4: later\nXFAIL tests/test_a.py::test_b - reason\nXPASS tests/test_a.py::test_c[1]\n"
           "PASSED tests/test_a.py::test_d\n1 passed, 1 skipped in 0.01s\n")
    assert redgreen.parse_not_run(out) == ["skip tests/test_a.py:4", "xfail tests/test_a.py::test_b", "xpass tests/test_a.py::test_c"]
    assert redgreen.parse_not_run("PASSED tests/a.py::t\n2 passed, 3 skipped in 0.01s\n") == ["3 skipped"]
    assert redgreen.parse_not_run("PASSED tests/a.py::t\n1 passed in 0.01s\n") == []


# --- the gate: the shapes of the review -------------------------------------------------------------------------------


def _repo(tmp_path, head_files):
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    scenario.git(repo, "init", "-q", "-b", "main")
    for name, text in scenario.BASE.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "-m", "base")
    base = scenario.git(repo, "rev-parse", "HEAD")
    scenario.git(repo, "checkout", "-q", "-b", "loop/issue-5")
    for name, text in head_files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    scenario.git(repo, "add", "-A")
    scenario.git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    return repo, base, scenario.git(repo, "rev-parse", "HEAD")


def _gate(tmp_path, head_files, issue_body=ISSUE, pr_body=CLOSES):
    repo, base, head = _repo(tmp_path, head_files)
    return gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=5, issue_body=issue_body, pr_body=pr_body, base=base, head=head,
                                        author=WORKER, wrap_for=scenario.UNSANDBOXED, n_mutants=2)), repo


@pytest.mark.parametrize("issue_body", [ISSUE, "", "Sem checklist aqui.\n"])
def test_s3_an_empty_diff_is_always_rejected_with_empty_diff(tmp_path, issue_body):
    report, repo = _gate(tmp_path, {}, issue_body=issue_body)
    assert not report.approved
    assert [c.name for c in report.checks] == ["diff"] and report.checks[0].status == FAIL
    assert report.checks[0].reasons[0].startswith("empty_diff") and report.checks[0].measured["reason_code"] == "empty_diff"
    assert not (repo / ".simplicio-loop" / "review-gate" / f"pr-11-{report.head[:7]}").exists()  # no tree was created


def test_an_empty_diff_is_rejected_without_a_jail_too(tmp_path, monkeypatch):
    from simplicio_loop.review_gate import isolation

    def no_jail(*_a, **_k):
        raise AssertionError("an empty PR needs no jail")

    monkeypatch.setattr(isolation, "make_jail", no_jail)
    repo, base, head = _repo(tmp_path, {})
    report = gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=None, issue_body="", pr_body="", base=base, head=head, author=WORKER))
    assert not report.approved and report.checks[0].reasons[0].startswith("empty_diff")


def test_s1_the_gate_rejects_tests_that_assert_true_with_the_name_of_the_criterion(tmp_path):
    report, _ = _gate(tmp_path, {"tests/test_fetch.py": VACUOUS_TEST})
    assert not report.approved and report.level.value == "T0"
    by = {c.name: c for c in report.checks}
    assert by["redgreen"].status == FAIL and any(r.startswith("vacuous_test") for r in by["redgreen"].reasons)
    assert by["coverage"].status == FAIL


def test_s2_the_gate_rejects_skipped_tests(tmp_path):
    text = "import pytest\n\n\n@pytest.mark.skip\ndef test_cliente_faz_retry():\n    assert False\n"
    report, _ = _gate(tmp_path, {"tests/test_fetch.py": text})
    by = {c.name: c for c in report.checks}
    assert not report.approved and by["redgreen"].reasons[0].startswith("tests_not_run") and by["coverage"].status == FAIL


def test_s8_the_gate_rejects_scripts_without_a_test_with_and_without_a_checklist(tmp_path):
    for n, issue_body in enumerate((ISSUE, "")):
        report, _ = _gate(tmp_path / str(n), {"scripts/retry.sh": "echo retry\n", "web/fetch.js": "export const x = 1\n"}, issue_body=issue_body)
        by = {c.name: c for c in report.checks}
        assert not report.approved and by["coverage"].reasons[0].startswith("no_evidence")


def test_s10_the_gate_rejects_a_doc_that_says_the_feature_exists(tmp_path):
    report, _ = _gate(tmp_path, {"docs/RETRY.md": "# Retry\n\nO cliente de fetch faz retry e registra log do retry.\n"})
    by = {c.name: c for c in report.checks}
    assert not report.approved and by["coverage"].status == FAIL and any(r.startswith("no_evidence") for r in by["coverage"].reasons)


def test_a_tests_only_pr_with_a_real_test_that_passes_is_no_evidence_of_a_behavior_criterion(tmp_path):
    text = ("from mod import add\n\n\ndef test_retry_do_cliente_de_fetch_registra_log():\n"
            "    \"\"\"o cliente de fetch faz retry e registra log do retry\"\"\"\n    assert add(1, 2) == 3\n")
    report, _ = _gate(tmp_path, {"tests/test_fetch.py": text})
    by = {c.name: c for c in report.checks}
    assert by["redgreen"].status == PASS and by["coverage"].status == FAIL and not report.approved, [c.reasons for c in report.checks]
    assert any(r.startswith("no_evidence") for r in by["coverage"].reasons)


# --- round 7: weak tests with the words of the criterion are no evidence when the PR implements nothing ------------------

BEHAVIOR = "- [ ] adicionar retry ao cliente de fetch\n"
WEAK = {
    "is_not_none": "assert add(1, 2) is not None",
    "callable": "assert callable(add)",
    "truthy_call": "assert add(1, 2)",
    "bare_validate_call": "validate_input(5)",
    "hasattr": "assert hasattr(mod, 'add')",
    "try_except_pass": "try:\n        assert add(1, 2) == 99\n    except Exception:\n        pass",
}


def _weak(body):
    return f"def test_retry_do_cliente_de_fetch():\n    {body}\n"


@pytest.mark.parametrize("whole", [True, False])
@pytest.mark.parametrize("body", WEAK.values(), ids=WEAK.keys())
def test_r7_weak_tests_alone_are_no_evidence_of_a_behavior_criterion(body, whole):
    result = _cov({"tests/test_fetch.py": ("A", _weak(body))}, issue_body=BEHAVIOR, whole=whole)
    assert result.status == FAIL and result.measured["uncovered"] == ["adicionar retry ao cliente de fetch"]
    assert any(r.startswith("no_evidence") for r in result.reasons) and result.measured["reason_code"] == "no_evidence"


@pytest.mark.parametrize("body", [b for k, b in WEAK.items() if k != "bare_validate_call"], ids=[k for k in WEAK if k != "bare_validate_call"])
def test_r7_the_same_tests_count_when_the_pr_also_changes_python_production(body):
    result = _cov({"tests/test_fetch.py": ("A", _weak(body)), "src/other.py": PROD}, issue_body=BEHAVIOR)
    assert result.status == PASS and result.measured["evidence"]["adicionar retry ao cliente de fetch"] == [
        "test:tests/test_fetch.py::test_retry_do_cliente_de_fetch"]


def test_r7_a_test_alone_is_evidence_of_a_criterion_that_asks_for_a_test():
    text = "def test_retry_do_cliente_de_fetch():\n    assert add(1, 2) == 3\n"
    for issue in ("- [ ] adicionar testes do retry do cliente de fetch\n", "- [ ] cobertura do retry do cliente de fetch\n",
                  "- [ ] add tests for the fetch client retry\n", "- [ ] testar o retry do cliente de fetch\n",
                  "- [ ] fetch client retry test coverage\n"):
        assert _cov({"tests/test_fetch.py": ("A", text)}, issue_body=issue).status == PASS, issue


def test_r7_a_test_asking_criterion_that_the_tests_miss_is_uncovered_but_not_no_evidence():
    result = _cov({"tests/test_other.py": ("A", "def test_math():\n    assert 1 + 1 == 2\n    assert abs(-1) == 1\n")},
                  issue_body="- [ ] adicionar testes do retry do cliente de fetch\n")
    assert result.status == FAIL and result.reasons[-1] == "criterio sem cobertura: adicionar testes do retry do cliente de fetch"
    assert not any(r.startswith("no_evidence") for r in result.reasons) and "reason_code" not in result.measured
    mixed = _cov({"tests/test_other.py": ("A", "def test_math():\n    assert 1 + 1 == 2\n")},
                 issue_body="- [ ] adicionar testes do retry do cliente de fetch\n- [ ] o cliente de fetch faz retry\n")
    assert mixed.measured["reason_code"] == "no_evidence" and len(mixed.measured["uncovered"]) == 2


def test_r7_a_cited_symbol_in_a_test_alone_is_no_evidence_of_a_behavior_criterion():
    text = "def test_x():\n    assert fetch_with_retry(1) is not None\n"
    issue = "- [ ] `fetch_with_retry` faz retry\n"
    assert _cov({"tests/test_x.py": ("A", text)}, issue_body=issue).status == FAIL
    assert _cov({"tests/test_x.py": ("A", text), "src/other.py": PROD}, issue_body=issue).status == PASS


def test_r7_a_deleted_or_non_python_file_is_not_production_for_the_test_to_stand_next_to():
    test = ("A", _weak(WEAK["is_not_none"]))
    assert _cov({"tests/test_fetch.py": test, "src/old.py": ("D", "")}, issue_body=BEHAVIOR).status == FAIL
    assert _cov({"tests/test_fetch.py": test, "web/fetch.js": ("A", "export const x = 1\n")}, issue_body=BEHAVIOR).status == FAIL
    assert _cov({"tests/test_fetch.py": test, "docs/RETRY.md": ("A", "retry cliente fetch\n")}, issue_body=BEHAVIOR).status == FAIL


def test_r7_a_helper_of_the_module_that_asserts_still_makes_a_validate_call_a_check():
    src = _src("""
        def validate_input(x):
            assert x > 0

        def validate_shape(x):
            return x

        def test_a():
            validate_input(5)

        def test_b():
            validate_shape(5)

        def test_c(self):
            self.assertEqual(1, 1)
            self.check_it()

        def test_d():
            raise_if_bad = 1
            validate_other(5)
        """)
    a, b, c, d = vacuity.analyze(src)
    assert a.usable and b.vacuous and c.usable and d.vacuous


def test_r7_a_helper_that_raises_is_a_check_and_one_that_only_calls_a_name_alike_is_not():
    src = _src("""
        def check_ready(x):
            if not x:
                raise ValueError(x)

        def ensure_chain(x):
            check_ready(x)

        def verify_nothing(x):
            return x

        def test_a():
            check_ready(1)

        def test_b():
            ensure_chain(1)

        def test_c():
            verify_nothing(1)
        """)
    a, b, c = vacuity.analyze(src)
    assert a.usable and b.usable and c.vacuous


@pytest.mark.parametrize("path", ["data/table.json", "poetry.lock", "package-lock.json", "data/rows.csv", "data/rows.tsv",
                                  "data/events.ndjson", "config/app.xml"])
@pytest.mark.parametrize("issue_body", [ISSUE, ""])
def test_r7_a_pr_of_generated_or_data_files_only_is_no_evidence_with_or_without_a_checklist(path, issue_body):
    result = _cov({path: ("A", "x\n")}, issue_body=issue_body)
    assert result.status == FAIL and result.reasons[0].startswith("no_evidence") and result.measured["other"] == [path]


def test_r7_a_data_file_next_to_a_real_test_and_production_is_still_covered():
    files = {"src/fetch_client.py": ("A", "class FetchClient:\n    def fetch_retry(self, retries):\n        return retries\n"),
             "tests/test_fetch.py": ("A", REAL_TEST), "tests/data/fixture.json": ("A", '{"url": "http://x"}\n')}
    assert _cov(files).status == PASS
    assert _cov({"tests/test_fetch.py": ("A", REAL_TEST), "src/other.py": PROD, "tests/data/fixture.json": ("A", "{}\n")}).status == PASS


def test_r7_a_deleted_data_file_is_not_added_production():
    assert _cov({"data/old.json": ("D", "")}, issue=None).status == SKIPPED


def test_r7_documentation_is_no_evidence_for_a_behavior_criterion_through_a_cited_token_either():
    docs = {"docs/retry_policy.md": ("A", "# retry_policy\n\nO cliente de fetch usa `retry_policy`.\n")}
    for issue in ("- [ ] o cliente de fetch usa `retry_policy`\n", "- [ ] o cliente de fetch usa retry_policy\n",
                  "- [ ] o cliente de fetch usa `retry_policy` e `fetch_client`\n"):
        result = _cov(docs, issue_body=issue)
        assert result.status == FAIL and result.measured["uncovered"], issue
    doc_ask = "- [ ] documentar `retry_policy` em `docs/retry_policy.md`\n"
    assert _cov(docs, issue_body=doc_ask).status == PASS


def test_r7_documentation_next_to_production_is_still_no_evidence_for_a_cited_symbol_only_the_docs_have():
    files = {"src/other.py": PROD, "docs/retry_policy.md": ("A", "O cliente usa `retry_policy`.\n")}
    assert _cov(files, issue_body="- [ ] o cliente de fetch usa `retry_policy`\n").status == FAIL


def test_r7_the_gate_hands_the_whole_text_of_the_test_files_to_coverage(tmp_path, monkeypatch):
    seen: dict = {}
    real = coverage.check_coverage

    def spy(*args, **kwargs):
        seen["sources"] = kwargs.get("sources", args[5] if len(args) > 5 else None)
        return real(*args, **kwargs)

    for module, name in ((redgreen, "check_redgreen"), (gate.mutation, "check_mutation"), (gate.usage, "check_usage"), (gate.docs, "check_docs")):
        monkeypatch.setattr(module, name, lambda *_a, _name=name, **_k: gate.CheckResult(_name, PASS))
    monkeypatch.setattr(coverage, "check_coverage", spy)
    text = "from mod import add\n\n\ndef test_a():\n    assert add(1, 2) == 3\n\n\ndef test_b():\n    assert add(2, 2) == 4\n"
    _gate(tmp_path, {"tests/test_add.py": text, "docs/NOTES.md": "# n\n"}, issue_body="")
    assert seen["sources"] == {"tests/test_add.py": text}


def test_r7_the_gate_rejects_weak_tests_alone_and_approves_production_with_a_data_fixture(tmp_path):
    weak = "import mod\n\n\ndef test_retry_do_cliente_de_fetch():\n    assert hasattr(mod, 'add')\n"
    report, _ = _gate(tmp_path / "weak", {"tests/test_fetch.py": weak}, issue_body=BEHAVIOR)
    by = {c.name: c for c in report.checks}
    assert not report.approved and by["coverage"].status == FAIL
    head = {**scenario.HEADS["good"], "tests/data/fixture.json": '{"low": 0, "high": 10}\n'}
    good, _ = _gate(tmp_path / "good", head, issue_body="- [ ] clamp limita o valor entre low e high\n")
    assert good.approved, [(c.name, c.reasons) for c in good.checks]


def test_a_docs_only_pr_without_a_checklist_stays_approved(tmp_path):
    report, _ = _gate(tmp_path, {"docs/NOTES.md": "# Notas\n\nTexto curto.\n"}, issue_body="")
    assert report.approved
