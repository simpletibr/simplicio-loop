"""run_gate on a real throwaway git repo: trees cleaned, report written, one verdict per check (Parte de #1649)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from simplicio_loop.review_gate import diffs, gate, identity
from simplicio_loop.review_gate.model import ERROR, FAIL, PASS, CheckResult, Level
from tests.review_gate import scenario

WORKER = identity.Agent("worker-1", "worker", "haiku-5.5", "local")
INDEPENDENT = identity.Agent("rev-2", "independent-reviewer", "opus-5.5", "other-host")
ISSUE_BODY = "Limitar valores.\n\n- [ ] `clamp` existe em `mod.py` e `app.total` usa\n"
PR_BODY = "Entrega `clamp` em `mod.py`.\n\nParte de #7\n"
ORDER = ["redgreen", "mutation", "usage", "coverage", "docs", "identity"]


class Run(NamedTuple):
    repo: Path
    base: str
    head: str
    report: object


def _run(root: Path, name: str, **overrides) -> Run:
    root.mkdir(parents=True, exist_ok=True)
    repo, base, head = scenario.make_repo(root, name)
    params = dict(repo=repo, pr=11, issue=7, issue_body=ISSUE_BODY, pr_body=PR_BODY, base=base, head=head, author=WORKER,
                  wrap_for=scenario.UNSANDBOXED)  # these tests exercise the checks; the jail has its own tests (test_isolation.py)
    params.update(overrides)
    return Run(repo, base, head, gate.run_gate(gate.GateInput(**params)))


def _check(run: Run, name: str) -> CheckResult:
    return next(c for c in run.report.checks if c.name == name)


@pytest.fixture(scope="module")
def good(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("good"), "good")


@pytest.fixture(scope="module")
def vacuous(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("vacuous"), "vacuous")


@pytest.fixture(scope="module")
def dead(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("dead"), "dead")


def test_no_worktree_is_left_and_the_report_json_matches_the_checks(good):
    listing = scenario.git(good.repo, "worktree", "list", "--porcelain")
    assert [ln for ln in listing.splitlines() if ln.startswith("worktree ")] == [f"worktree {good.repo}"]
    out = good.repo / ".simplicio-loop" / "review-gate"
    assert sorted(p.name for p in out.iterdir()) == [f"pr-11-{good.head[:7]}.json"]  # the two trees and their folder are gone
    saved = json.loads((out / f"pr-11-{good.head[:7]}.json").read_text(encoding="utf-8"))
    assert saved["head"] == good.head and saved["pr"] == 11 and saved["issue"] == 7 and saved["level"] == "T1"
    assert [c["name"] for c in saved["checks"]] == ORDER == [c.name for c in good.report.checks]
    assert saved == good.report.to_dict()


def test_every_check_has_its_elapsed_time(good):
    assert all(isinstance(c.measured["elapsed_s"], float) and c.measured["elapsed_s"] >= 0 for c in good.report.checks)
    assert good.report.elapsed_s >= sum(c.measured["elapsed_s"] for c in good.report.checks) - 0.01


def test_vacuous_tests_fail_redgreen_with_the_test_id(vacuous):
    check = _check(vacuous, "redgreen")
    assert check.status == FAIL
    assert check.measured["vacuous"] == ["tests/test_add.py::test_add_again"]
    assert any("tests/test_add.py::test_add_again" in r and "passam em main" in r for r in check.reasons)
    assert not vacuous.report.approved


def test_a_new_module_with_good_tests_is_red_on_main_and_green_on_head(dead):
    check = _check(dead, "redgreen")
    assert check.status == PASS, check.reasons
    assert check.measured["red"] == ["tests/test_dead.py::test_double"] and check.measured["head_failed"] == []


# depende de usage/coverage corrigidos
def test_a_new_module_nobody_imports_fails_usage_with_its_path(dead):
    check = _check(dead, "usage")
    assert check.status == FAIL
    assert any("dead.py" in r for r in check.reasons)
    assert not dead.report.approved


def test_good_head_is_red_on_main_and_its_mutants_die(good):
    redgreen = _check(good, "redgreen")
    assert redgreen.status == PASS, redgreen.reasons
    assert redgreen.measured["tests"] == 4 and len(redgreen.measured["red"]) == 4
    mutation = _check(good, "mutation")
    assert mutation.status == PASS, mutation.reasons
    m = mutation.measured
    assert m["total"] == min(gate.DEFAULT_MUTANTS, m["candidates"]) and m["total"] >= 6
    assert m["killed"] == m["total"] and m["survived"] == [] and m["ratio"] == 1.0
    assert _check(good, "identity").status == PASS and good.report.level is Level.T1


# depende de usage/coverage corrigidos
def test_good_head_is_approved_at_level_t1(good):
    assert good.report.approved, [(c.name, c.reasons) for c in good.report.blockers]
    assert good.report.level is Level.T1 and not good.report.partial


def test_code_without_any_test_fails_mutation_and_never_runs_the_suite(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    real = subprocess.run

    def spy(argv, *args, **kwargs):
        calls.append([str(a) for a in argv])
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    run = _run(tmp_path, "notest")  # app.py changes and no test imports app: no new test, no neighbor
    mutation = _check(run, "mutation")
    assert mutation.status == FAIL and mutation.reasons == ("sem teste novo nem vizinho para rodar contra os mutantes",)
    redgreen = _check(run, "redgreen")
    assert redgreen.status == FAIL and "sem teste novo" in redgreen.reasons[0] and "app.py" in redgreen.reasons[0]
    assert any(c[0] == "git" for c in calls)  # the spy sees the gate's own commands...
    assert not any("pytest" in c for c in calls)  # ...and not one pytest run, so no suite
    assert not run.report.approved


def test_author_equal_to_the_automatic_reviewer_is_a_self_approval(tmp_path):
    run = _run(tmp_path, "notest", author=identity.AUTO_REVIEWER)
    check = _check(run, "identity")
    assert check.status == FAIL and "auto-aprovacao" in check.reasons[0] and identity.AUTO_REVIEWER.agent_id in check.reasons[0]
    assert not run.report.approved


def test_security_paths_are_t2_and_need_the_independent_reviewer_marker(tmp_path):
    alone = _run(tmp_path / "a", "secure")
    assert alone.report.level is Level.T2
    assert _check(alone, "identity").status == FAIL and "T2" in _check(alone, "identity").reasons[0]
    marked = _run(tmp_path / "b", "secure", independent=INDEPENDENT)
    assert marked.report.level is Level.T2
    assert _check(marked, "identity").status == PASS
    assert _check(marked, "identity").measured["independent"] == "rev-2"


def test_extra_checks_come_last_and_a_partial_coverage_marks_the_report(tmp_path):
    extra = (CheckResult("endpoint_compare", PASS), CheckResult("coverage", PASS, measured={"partial": True}))
    run = _run(tmp_path, "notest", extra=extra)
    assert [c.name for c in run.report.checks][-2:] == ["endpoint_compare", "coverage"]
    assert run.report.partial is True
    assert _run(tmp_path / "again", "notest").report.partial is False


def _wrapped_runs(tmp_path, name, **overrides):
    seen: list[tuple[Path, list]] = []

    def wrap_for(root: Path):
        def wrap(argv):
            seen.append((root, list(argv)))
            return argv
        return wrap

    return _run(tmp_path, name, wrap_for=wrap_for, **overrides), seen


def test_the_sandbox_wrapper_is_built_for_the_head_tree_and_wraps_every_pytest_run(tmp_path):
    run, seen = _wrapped_runs(tmp_path, "dead", n_mutants=2)
    assert [root.name for root, _ in seen] == ["head", "base", "head", "head", "head"]  # each run wrapped for the tree it runs in (the sandbox chdirs there)
    assert all(root.parent.name == f"pr-11-{run.head[:7]}" for root, _ in seen)
    assert all(argv[1] == "-c" and "pytest.main" in argv[2] for _, argv in seen)
    assert len(seen) == 2 + 1 + 2  # redgreen on head and on main, the unmutated tree, two mutants


def test_the_mutants_run_the_changed_tests_then_the_neighbors_and_never_a_conftest(tmp_path):
    run, seen = _wrapped_runs(tmp_path, "good", n_mutants=1)
    mutation_argv = seen[-1][1]  # the last run is a mutant
    assert mutation_argv[3:] == ["-q", "--tb=no", "-p", "no:cacheprovider", "-o", "addopts=", "--confcutdir", ".", "-c", "/dev/null", "--rootdir", ".", "tests/test_clamp.py", "tests/test_add.py", "-rfE"]
    run, seen = _wrapped_runs(tmp_path / "conf", "withconf", n_mutants=1)
    assert seen[-1][1][-2:] == ["tests/test_dead.py", "-rfE"] and not any("conftest.py" in a for a in seen[-1][1])


def test_the_limits_of_the_input_reach_the_checks(tmp_path):
    strict = _run(tmp_path / "a", "dead", n_mutants=6, min_kill=1.5)  # 6 live mutants: the ratio judges, so min_kill is reached
    mutation = _check(strict, "mutation")
    assert mutation.status == FAIL and "<150%" in mutation.reasons[0]
    assert mutation.measured["n"] == 6 and mutation.measured["total"] == 6 and mutation.measured["judged"] is True and mutation.measured["seed"] == strict.head
    default = _check(_run(tmp_path / "b", "dead"), "mutation")
    assert default.measured["n"] == 12 and default.measured["seed"] != ""
    slow = _run(tmp_path / "c", "dead", test_timeout_s=0.001, mutant_timeout_s=0.001)
    assert _check(slow, "redgreen").status == ERROR and "timeout of 0.001s" in _check(slow, "redgreen").reasons[0]
    assert _check(slow, "mutation").status == ERROR and "saida None" in _check(slow, "mutation").reasons[0]


def test_the_mutation_check_gets_the_new_red_tests_for_the_attribution_rule(tmp_path, monkeypatch):
    """The attribution rule (test_kills_no_mutant) reads the new red tests of the red/green check: a gate that drops them skips the rule."""
    got = {}
    real = gate.mutation.check_mutation

    def wrapper(*args, **kw):
        got["red"] = kw.get("red", "not passed")
        return real(*args, **kw)

    monkeypatch.setattr(gate.mutation, "check_mutation", wrapper)
    _run(tmp_path, "dead")
    assert got["red"] == ["tests/test_dead.py::test_double"]


def test_each_check_gets_the_inputs_it_needs(tmp_path, monkeypatch):
    got = {}

    def spy(name, module, fn):
        real = getattr(module, fn)

        def wrapper(*args, **kw):
            got[name] = (args, kw)
            return real(*args, **kw)

        monkeypatch.setattr(module, fn, wrapper)

    spy("usage", gate.usage, "check_usage")
    spy("coverage", gate.coverage, "check_coverage")
    spy("docs", gate.docs, "check_docs")
    spy("identity", gate.identity, "check_identity")
    spy("redgreen", gate.redgreen, "check_redgreen")
    spy("mutation", gate.mutation, "check_mutation")
    run = _run(tmp_path, "notest", independent=INDEPENDENT)
    expected_env = {"PYTHONPATH": ".", "PYTHONDONTWRITEBYTECODE": "1"}  # the tests find the modules of the tree
    assert got["redgreen"][1]["env"] == expected_env and got["mutation"][1]["env"] == expected_env
    assert got["redgreen"][0][1].name == "head" and got["mutation"][0][0].name == "head"
    usage_root, usage_changes, base_public = got["usage"][0]
    assert usage_root.name == "head" and [c.path for c in usage_changes] == ["app.py"] and base_public == {"app.py": frozenset({"total"})}  # `bonus` is new
    issue, issue_body, changes, added, pr_body = got["coverage"][0]
    assert (issue, issue_body, pr_body) == (7, ISSUE_BODY, PR_BODY) and [c.path for c in changes] == ["app.py"]
    assert added == {"app.py": "    return add(a, b) + 1\n\n\ndef bonus(x):\n    return add(x, 1)"}
    base_root, head_root, _ = got["docs"][0]
    assert (base_root.name, head_root.name) == ("base", "head")
    assert got["identity"][0] == (WORKER, identity.AUTO_REVIEWER, Level.T1, INDEPENDENT)
    assert (run.report.pr, run.report.issue, run.report.head) == (11, 7, run.head)


def test_a_gate_that_cannot_prepare_its_trees_reports_a_setup_error_and_still_writes_the_report(tmp_path):
    repo, base, head = scenario.make_repo(tmp_path, "notest")
    (repo / ".simplicio-loop" / "review-gate" / f"pr-11-{head[:7]}").mkdir(parents=True)  # a leftover of a crashed run
    report = gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=7, issue_body="", pr_body="", base=base, head=head, author=WORKER,
                                          wrap_for=scenario.UNSANDBOXED))
    assert [c.name for c in report.checks] == ["setup"] and report.checks[0].status == ERROR
    assert "gate could not prepare its trees" in report.checks[0].reasons[0] and not report.approved
    assert json.loads((repo / ".simplicio-loop" / "review-gate" / f"pr-11-{head[:7]}.json").read_text())["approved"] is False


def test_a_git_failure_while_adding_the_trees_is_a_setup_error_and_the_tree_already_added_is_removed(tmp_path, monkeypatch):
    repo, base, head = scenario.make_repo(tmp_path, "notest")
    real, calls = gate._git, []

    def flaky(where, *args, **kw):
        calls.append(args)
        if len(calls) == 2:  # the second `worktree add`
            raise RuntimeError("git worktree add failed: disk full")
        return real(where, *args, **kw)

    monkeypatch.setattr(gate, "_git", flaky)
    report = gate.run_gate(gate.GateInput(repo=repo, pr=11, issue=7, issue_body="", pr_body="", base=base, head=head, author=WORKER,
                                          wrap_for=scenario.UNSANDBOXED))
    assert [c.name for c in report.checks] == ["setup"] and not report.approved
    assert report.checks[0].reasons == ("gate could not prepare its trees: git worktree add failed: disk full",)
    assert [c[:2] for c in calls] == [("worktree", "add")] * 2
    listing = scenario.git(repo, "worktree", "list", "--porcelain")
    assert [ln for ln in listing.splitlines() if ln.startswith("worktree ")] == [f"worktree {repo}"]
    assert not (repo / ".simplicio-loop" / "review-gate" / f"pr-11-{head[:7]}").exists()


def test_git_helper_returns_stdout_and_names_the_failing_command_with_the_last_200_chars(tmp_path):
    repo, _, _ = scenario.make_repo(tmp_path, "notest")
    assert gate._git(repo, "rev-parse", "--is-inside-work-tree") == "true\n"
    with pytest.raises(RuntimeError) as caught:
        gate._git(repo, "rev-parse", "--verify", "refs/heads/nope", "--quiet", "extra" * 80)
    message = str(caught.value)
    assert message.startswith("git rev-parse --verify refs/heads/nope failed: ")
    assert len(message) <= len("git rev-parse --verify refs/heads/nope failed: ") + 200
    with pytest.raises(RuntimeError) as long:
        gate._git(repo, "rev-parse", "nope-" + "x" * 200)
    tail = long.value.args[0].split(" failed: ", 1)[1]
    assert len(tail) == 200 and tail.endswith("-- [<file>...]'") and "fatal:" not in tail  # the LAST 200 characters of git's complaint


@pytest.mark.parametrize("exc", [ValueError("kaput"), KeyError("kaput"), OSError("kaput"), RuntimeError("kaput")])
def test_a_check_that_raises_is_an_error_with_its_cause_never_a_pass(exc):
    def boom():
        raise exc

    result = gate._timed("usage", boom)
    assert result.status == ERROR and result.name == "usage"
    assert result.reasons == (f"usage could not run: {type(exc).__name__}: {exc}",) and result.measured["elapsed_s"] >= 0


def test_a_passing_check_keeps_its_measured_numbers_and_gets_the_elapsed_time():
    kept = gate._timed("x", lambda: CheckResult("x", PASS, measured={"a": 1}))
    assert kept.status == PASS and kept.measured["a"] == 1 and isinstance(kept.measured["elapsed_s"], float)


def test_neighbors_finds_the_existing_test_that_imports_the_changed_module(tmp_path):
    repo, base, head = scenario.make_repo(tmp_path, "good")
    changes = diffs.changed_files(repo, base, head)
    assert gate.neighbors(repo, changes) == ["tests/test_add.py"]  # on main: imports mod; test_clamp.py (changed) is not there


def test_neighbors_matches_module_imports_only_skips_changed_tests_and_caps(tmp_path):
    (tmp_path / "tests" / "sub").mkdir(parents=True)
    texts = {"tests/test_a.py": "from mod import add\n", "tests/test_b.py": "import mod\n", "tests/sub/test_c.py": "from pkg.mod import x\n",
             "tests/test_d.py": "import model\n", "tests/test_e.py": "from other import mod_helper\n", "tests/test_f.py": "import mod\n",
             "tests/helper.py": "import mod\n", "tests/test_g.py": "import util\n"}
    for name, text in texts.items():
        (tmp_path / name).write_text(text)
    (tmp_path / "tests" / "test_binary.py").write_bytes(b"\xff\xfe import mod \xff")  # not utf-8: skipped, not a crash
    changes = [diffs.FileChange("mod.py", "M", (1,)), diffs.FileChange("tests/test_f.py", "M", (1,)),
               diffs.FileChange("gone.py", "D", ()), diffs.FileChange("README.md", "M", (1,))]
    assert gate.neighbors(tmp_path, changes) == ["tests/sub/test_c.py", "tests/test_a.py", "tests/test_b.py"]
    both = [*changes, diffs.FileChange("util.py", "A", (1,))]
    assert gate.neighbors(tmp_path, both) == ["tests/sub/test_c.py", "tests/test_a.py", "tests/test_b.py", "tests/test_g.py"]
    assert gate.neighbors(tmp_path, [diffs.FileChange("gone.py", "D", ())]) == []
    for i in range(12):
        (tmp_path / "tests" / f"test_n{i:02d}.py").write_text("import mod\n")
    assert len(gate.neighbors(tmp_path, changes)) == gate.NEIGHBOR_CAP == 8
    assert gate.neighbors(tmp_path / "nowhere", changes) == []


def test_neighbors_of_a_changed_test_helper_are_the_tests_that_import_it(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "helpers.py").write_text("def make():\n    return 1\n")
    (tmp_path / "tests" / "test_uses.py").write_text("from tests.helpers import make\n")
    (tmp_path / "tests" / "test_other.py").write_text("import mod\n")
    assert gate.neighbors(tmp_path, [diffs.FileChange("tests/helpers.py", "M", (1,))]) == ["tests/test_uses.py"]


@pytest.mark.parametrize("path, helper", [
    ("tests/helpers.py", True), ("tests/review_gate/scenario.py", True), ("tests/test_a.py", False), ("tests/conftest.py", False),
    ("tests/plugins/extra.py", False), ("tests/fixtures/data.json", False), ("mod.py", False),
])
def test_a_changed_test_helper_is_a_non_test_module_under_tests_and_not_pytest_infrastructure(path, helper):
    assert diffs.is_test_helper(path) is helper


def test_default_env_adds_the_package_dirs_that_exist(tmp_path):
    assert gate.default_env(tmp_path) == {"PYTHONPATH": ".", "PYTHONDONTWRITEBYTECODE": "1"}
    (tmp_path / "packages" / "mapper").mkdir(parents=True)
    assert gate.default_env(tmp_path)["PYTHONPATH"] == os.pathsep.join([".", "packages/mapper"])
    (tmp_path / "packages" / "dev-cli").mkdir()
    assert gate.default_env(tmp_path)["PYTHONPATH"] == os.pathsep.join([".", "packages/dev-cli", "packages/mapper"])


def test_added_text_and_base_public_read_only_what_the_diff_says(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\nthree\n")
    (tmp_path / "b.py").write_text("def pub():\n    pass\n\n\ndef _priv():\n    pass\n")
    (tmp_path / "t.txt").write_text("x\n")
    (tmp_path / "new.py").write_text("n1\nn2\n")
    changes = [diffs.FileChange("a.py", "M", (2, 3, 9)), diffs.FileChange("b.py", "M", (1,)), diffs.FileChange("c.py", "D", (1,)),
               diffs.FileChange("new.py", "A", (1,)), diffs.FileChange("t.txt", "M", (1,))]
    (tmp_path / "bin.py").write_bytes(b"\xff\xfe")
    changes.append(diffs.FileChange("bin.py", "M", (1,)))
    assert gate._added_text(tmp_path, changes) == {"a.py": "two\nthree", "b.py": "def pub():", "t.txt": "x", "new.py": "n1"}
    assert gate._base_public(tmp_path, changes[:5]) == {"a.py": frozenset(), "b.py": frozenset({"pub"})}  # only code that was modified and exists


def test_the_forged_conftest_pr_is_rejected_by_the_real_gate_at_level_t2(tmp_path):
    """Review round: a never-fixed bug + tests/sub/conftest.py rewriting the report + a genuine fix elsewhere gave `T1 approved`."""
    run = _run(tmp_path, "forged")
    redgreen = _check(run, "redgreen")
    assert run.report.level is Level.T2 and not run.report.approved
    assert redgreen.status == FAIL and redgreen.measured["head_failed"] == ["tests/sub/test_bug.py::test_add_is_fixed"]
    assert redgreen.measured["pytest_infra_ignored"] == ["tests/sub/conftest.py"]
    assert _check(run, "mutation").blocking  # no check runs under the forged conftest: the unmutated tree fails the honest test too
    assert _check(run, "identity").status == FAIL  # and T2 wants an independent reviewer
    marked = _run(tmp_path / "again", "forged", independent=INDEPENDENT)
    assert _check(marked, "identity").status == PASS and not marked.report.approved  # a marker does not fix redgreen


def test_no_check_sees_the_conftest_of_the_pr_even_when_redgreen_ends_early(tmp_path, monkeypatch):
    """Defence in depth: the head tree is neutralized by the gate itself, not only by redgreen (which may skip or fail first)."""
    seen = {}
    real = gate.mutation.check_mutation

    def spy(root, *args, **kw):
        seen["conftest"] = (root / "tests" / "sub" / "conftest.py").exists()
        return real(root, *args, **kw)

    monkeypatch.setattr(gate.mutation, "check_mutation", spy)
    monkeypatch.setattr(gate.redgreen, "check_redgreen", lambda *a, **kw: CheckResult("redgreen", PASS))
    run = _run(tmp_path, "forged", n_mutants=1)
    assert seen == {"conftest": False}
    assert [c.name for c in run.report.checks] == ORDER
