"""sibling_search (plan): other call sites of the planned files and functions, as 'check these too'."""
import pytest

from simplicio_loop.watcher247 import points
from simplicio_loop.watcher247.points import sibling_search

from .git_repo import init_repo

BASE = {
    "app.py": "def compute(x):\n    return x + 1\n",
    "tests/test_app.py": "from app import compute\n\n\ndef test_compute():\n    assert compute(1) == 2\n",
    "billing.py": "from app import compute\n\n\ndef total(v):\n    return compute(v) * 2\n",
    "unrelated.py": "def other():\n    return 0\n",
}


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "clone", BASE)


def test_registered_at_plan_and_not_blocking():
    [info] = [i for i in points.registered() if i.name == "sibling_search"]
    assert (info.stage, info.blocking) == ("plan", False)


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    assert point_contract("sibling_search", make_ctx(), expect="skipped").reason_code == "no_clone"


def test_nothing_to_search_is_skipped(point_contract, make_ctx, repo):
    result = point_contract("sibling_search", make_ctx(clone=repo, task_text="melhore a documentacao"),
                            expect="skipped")
    assert result.reason_code == "no_targets"


def test_plan_operations_give_the_files_and_functions(point_contract, make_ctx, repo):
    plan = {"operations": [{"path": "app.py", "find": "def compute(x):", "replace": "def compute(x, y=0):"}]}
    result = point_contract("sibling_search", make_ctx(clone=repo, plan=plan), expect="ok")
    assert result.evidence["files"] == ["app.py"]
    assert result.evidence["symbols"] == ["compute"]
    sites = {(s["path"], s["symbol"]) for s in result.evidence["check_these_too"]}
    assert ("billing.py", "compute") in sites and ("tests/test_app.py", "compute") in sites
    assert not any(s["path"] == "app.py" for s in result.evidence["check_these_too"])
    assert all(s["path"] != "unrelated.py" for s in result.evidence["check_these_too"])
    billing = next(s for s in result.evidence["check_these_too"] if "compute(v)" in s["text"])
    assert billing["line"] == 5 and "compute(v)" in billing["text"]


def test_before_the_planner_the_task_text_names_files_and_symbols(point_contract, make_ctx, repo):
    ctx = make_ctx(clone=repo, task_text="Corrigir `compute` em app.py para aceitar offset")
    result = point_contract("sibling_search", ctx, expect="ok")
    assert result.evidence["files"] == ["app.py"]
    assert result.evidence["symbols"] == ["compute"]
    assert {s["path"] for s in result.evidence["check_these_too"]} == {"billing.py", "tests/test_app.py"}


def test_sibling_tests_of_the_planned_files_come_from_the_orient_helper(point_contract, make_ctx, repo):
    result = point_contract("sibling_search", make_ctx(clone=repo, task_text="mexer em app.py"), expect="ok")
    assert result.evidence["sibling_tests"] == {"app.py": ["tests/test_app.py"]}


def test_a_file_outside_the_clone_is_ignored(point_contract, make_ctx, repo):
    plan = {"operations": [{"path": "../escape.py"}, {"path": "/etc/passwd"}]}
    point_contract("sibling_search", make_ctx(clone=repo, plan=plan), expect="skipped")


def test_hits_are_capped(point_contract, make_ctx, tmp_path):
    files = {"app.py": "def compute(x):\n    return x\n"}
    files |= {f"user{i}.py": "compute(1)\n" for i in range(sibling_search.MAX_SITES + 5)}
    repo = init_repo(tmp_path / "big", files)
    result = point_contract("sibling_search", make_ctx(clone=repo, task_text="`compute` em app.py"), expect="ok")
    assert len(result.evidence["check_these_too"]) == sibling_search.MAX_SITES
    assert result.evidence["truncated"] is True


def test_a_directory_that_is_not_a_repo_finds_nothing_and_does_not_fail(point_contract, make_ctx, tmp_path):
    (tmp_path / "app.py").write_text(BASE["app.py"])
    result = point_contract("sibling_search", make_ctx(clone=tmp_path, task_text="`compute` em app.py"),
                            expect="ok")
    assert result.evidence["check_these_too"] == []
