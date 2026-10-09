"""judge (verify, blocking): ACCEPT/REJECT on the applied diff; deterministic checks first."""
import asyncio
import json

import pytest

from simplicio_loop.watcher247 import points

from .blocking import point_contract  # noqa: F401  (the blocking variant of the fixture)
from .git_repo import init_repo, write

BASE = {
    "app.py": "def f():\n    return 1\n",
    "tests/test_app.py": "def test_f():\n    assert 1\n\n\ndef test_g():\n    assert 2\n",
}
# built from parts so this test file never carries a literal secret
SECRET = "AKIA" + "Q7R2T9W4B6N3K8M5"  # an AWS key id shape without the 'example' placeholder word


@pytest.fixture
def repo(tmp_path):
    return init_repo(tmp_path / "clone", BASE)


def ctx_for(make_ctx, repo, tmp_path, **fields):
    return make_ctx(clone=repo, run_dir=tmp_path / "run", **fields)


def verdict_file(tmp_path):
    return json.loads((tmp_path / "run" / "judge.json").read_text())


def test_registered_at_verify_and_blocking():
    [info] = [i for i in points.registered() if i.name == "judge"]
    assert (info.stage, info.blocking, info.conditional) == ("verify", True, False)


def test_without_a_clone_it_is_skipped(point_contract, make_ctx):
    result = point_contract("judge", make_ctx(), expect="skipped")
    assert result.reason_code == "no_clone"


def test_clean_diff_is_accepted(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"app.py": "def f():\n    return 2\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="ok")
    assert result.evidence["verdict"] == "ACCEPT"
    assert result.evidence["reasons"] == []
    assert result.evidence["files"] == ["app.py"]
    saved = verdict_file(tmp_path)
    assert saved["verdict"] == "ACCEPT" and saved["secret_files"] == []


def test_empty_diff_is_skipped_not_rejected(point_contract, make_ctx, repo, tmp_path):
    # an empty diff is a legitimate result (done_no_diff in the tick): nothing to judge, the stage goes on
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="skipped")
    assert result.reason_code == "no_diff"
    assert verdict_file(tmp_path)["verdict"] == "NO_DIFF"


def test_a_stale_accept_does_not_survive_an_empty_diff(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"app.py": "def f():\n    return 2\n"})
    point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="ok")
    (repo / "app.py").write_text(BASE["app.py"])
    point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="skipped")
    assert verdict_file(tmp_path)["verdict"] == "NO_DIFF"


def test_state_dirs_do_not_count_as_a_diff(point_contract, make_ctx, repo, tmp_path):
    write(repo, {".simplicio-loop/x.json": "{}", ".simplicio/y": "y"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="skipped")
    assert result.reason_code == "no_diff"


def test_file_outside_the_plan_rejects(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"app.py": "def f():\n    return 2\n", "other.py": "x = 1\n"})
    plan = {"operations": [{"path": "app.py", "find": "1", "replace": "2"}]}
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path, plan=plan), expect="blocked")
    assert result.reason_code == "outside_plan"
    assert result.evidence["outside_plan"] == ["other.py"]


def test_applied_list_of_turbo_is_the_plan_when_there_is_no_plan(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"app.py": "def f():\n    return 2\n", "other.py": "x = 1\n"})
    ctx = ctx_for(make_ctx, repo, tmp_path, turbo_json={"applied": ["app.py"]})
    result = point_contract("judge", ctx, expect="blocked")
    assert result.evidence["outside_plan"] == ["other.py"]


def test_in_plan_change_is_accepted(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"app.py": "def f():\n    return 2\n"})
    plan = {"operations": [{"path": "app.py"}]}
    point_contract("judge", ctx_for(make_ctx, repo, tmp_path, plan=plan), expect="ok")


def test_deleted_test_file_rejects(point_contract, make_ctx, repo, tmp_path):
    (repo / "tests" / "test_app.py").unlink()
    write(repo, {"app.py": "def f():\n    return 2\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="blocked")
    assert result.reason_code == "test_removed"
    assert "tests/test_app.py" in result.evidence["test_removed"]


def test_removed_test_function_rejects(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"tests/test_app.py": "def test_f():\n    assert 1\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="blocked")
    assert result.reason_code == "test_removed"
    assert any("test_g" in item for item in result.evidence["test_removed"])


def test_renamed_test_function_is_not_a_removal_when_it_is_still_defined(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"tests/test_app.py": "def test_f():\n    assert 10\n\n\ndef test_g():\n    assert 2\n"})
    point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="ok")


@pytest.mark.parametrize("marker", [
    "@pytest.mark.skip(reason='later')", "@pytest.mark.xfail", "pytest.skip('no')", "@unittest.skip('x')",
])
def test_added_skip_rejects(point_contract, make_ctx, repo, tmp_path, marker):
    write(repo, {"tests/test_app.py": f"{marker}\ndef test_f():\n    assert 1\n\n\ndef test_g():\n    assert 2\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="blocked")
    assert result.reason_code == "test_skipped"


def test_secret_in_a_new_untracked_file_rejects(point_contract, make_ctx, repo, tmp_path):
    write(repo, {"config.py": f"KEY = '{SECRET}'\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="blocked")
    assert result.reason_code == "secret_detected"
    assert result.evidence["secret_files"] == ["config.py"]
    assert SECRET not in json.dumps(result.evidence)
    assert verdict_file(tmp_path)["secret_files"] == ["config.py"]


def test_every_reason_is_listed_not_only_the_first(point_contract, make_ctx, repo, tmp_path):
    (repo / "tests" / "test_app.py").unlink()
    write(repo, {"config.py": f"KEY = '{SECRET}'\n"})
    result = point_contract("judge", ctx_for(make_ctx, repo, tmp_path), expect="blocked")
    assert set(result.evidence["reasons"]) == {"test_removed", "secret_detected"}


def test_a_git_failure_blocks_instead_of_accepting(make_ctx, tmp_path):
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(points.PointBlocked) as blocked:
        asyncio.run(points.run("verify", ctx_for(make_ctx, plain, tmp_path)))
    assert blocked.value.reason_code == "git_failed"
