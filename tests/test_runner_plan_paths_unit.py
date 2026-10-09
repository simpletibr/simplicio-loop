"""The runner's host-plan route refuses the same paths the turbo and apply routes do (issue #1565, audit of #1571, D2).

``runner._validate_minimal_host_plan_paths`` returned None for any plan with a ``schema`` and checked authorization only when
the task named targets, and ``_compile_minimal_host_plan`` handed the plan to dev-cli as it was, so ``.git/hooks/pre-commit``
went through with empty targets and a ``simplicio.mechanical-edit/v1`` plan (``create_file``, ``move_file``, ``delete_file``)
relied on dev-cli alone. A dev-cli that predates the ``.git`` check (0.18.16) applies all of them. Both functions now go
through ``plan_paths`` (text and symlinks). Only fake data lives here.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio_loop import runner
from tests.runner_patch import patch_runner

MECHANICAL = "simplicio.mechanical-edit/v1"
EDIT_PLAN = "simplicio.dev-cli.edit-plan/v1"


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "app.py").write_text("old\n", encoding="utf-8")
    for args in (["init", "-q"], ["config", "user.email", "a@b.c"], ["config", "user.name", "a"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    os.symlink(".git", root / "link")
    os.symlink(".git/hooks", root / "hk")
    os.symlink("src", root / "srcln")
    return root


def _minimal(path: str, find: str = "") -> dict:
    return {"operations": [{"path": path, "find": find, "replace": "planted\n"}]}


def _full(schema: str, *operations: dict) -> dict:
    return {"schema": schema, "operations": list(operations)}


UNSAFE_PLANS = [
    pytest.param(_minimal(".git/hooks/pre-commit"), id="minimal-git-hook"),
    pytest.param(_minimal(".GIT/config"), id="minimal-upcase-git"),
    pytest.param(_minimal("link/hooks/pre-commit"), id="minimal-symlink-to-git"),
    pytest.param(_minimal("hk/post-commit"), id="minimal-symlink-to-hooks"),
    pytest.param(_minimal("/etc/passwd", "root"), id="minimal-absolute"),
    pytest.param(_minimal("../outside.txt"), id="minimal-dotdot"),
    pytest.param({"ops": [{"path": ".git/config", "find": "", "replace": "x"}]}, id="ops-key"),
    pytest.param({"edits": [{"path": "link/config", "find": "", "replace": "x"}]}, id="edits-key"),
    pytest.param(_full(MECHANICAL, {"op": "create_file", "path": ".git/hooks/pre-commit", "text": "x"}), id="mech-create"),
    pytest.param(_full(MECHANICAL, {"op": "move_file", "path": "app.py", "dest": ".git/hooks/pre-commit"}), id="mech-move-dest"),
    pytest.param(_full(MECHANICAL, {"op": "move_file", "path": ".git/HEAD", "dest": "head.txt"}), id="mech-move-source"),
    pytest.param(_full(MECHANICAL, {"op": "delete_file", "path": ".git/HEAD"}), id="mech-delete"),
    pytest.param(_full(MECHANICAL, {"op": "delete_file", "path": ".GIT/HEAD"}), id="mech-delete-upcase"),
    pytest.param(_full(MECHANICAL, {"op": "delete_file", "path": "link/HEAD"}), id="mech-delete-symlink"),
    pytest.param(_full(MECHANICAL, {"op": "move_file", "path": "app.py", "dest": "hk/pre-commit"}), id="mech-move-symlink"),
    pytest.param(_full(EDIT_PLAN, {"op": "replace_anchor", "path": ".git/config", "anchor": "a", "replacement": "b"}), id="edit-plan"),
]
ORDINARY_PLANS = [
    pytest.param(_minimal("app.py", "old"), id="minimal"),
    pytest.param(_minimal("srcln/new.py"), id="minimal-through-an-ordinary-symlink"),
    pytest.param(_minimal(".gitignore"), id="minimal-gitignore"),
    pytest.param(_minimal(".github/workflows/x.yml"), id="minimal-github"),
    pytest.param(_full(MECHANICAL, {"op": "create_file", "path": "src/new.py", "text": "x"}), id="mech-create"),
    pytest.param(_full(MECHANICAL, {"op": "move_file", "path": "app.py", "dest": "src/app.py"}), id="mech-move"),
    pytest.param(_full(EDIT_PLAN), id="edit-plan-without-operations"),
]


@pytest.mark.parametrize("plan", UNSAFE_PLANS)
def test_the_preflight_refuses_an_unsafe_plan_even_with_no_authorized_targets(repo, plan):
    issue = runner._validate_minimal_host_plan_paths(plan, repo, [])
    assert issue is not None and issue["reason_code"] == "plan_path_unsafe"
    assert issue["message"]


@pytest.mark.parametrize("plan", UNSAFE_PLANS[:2])
def test_the_preflight_refuses_an_unsafe_plan_whatever_the_targets_are(repo, plan):
    path = plan["operations"][0]["path"]
    assert runner._validate_minimal_host_plan_paths(plan, repo, [path])["reason_code"] == "plan_path_unsafe"
    assert runner._validate_minimal_host_plan_paths(plan, repo, ["app.py"])["reason_code"] == "plan_path_unsafe"


@pytest.mark.parametrize("plan", ORDINARY_PLANS)
def test_the_preflight_leaves_an_ordinary_plan_alone(repo, plan):
    issue = runner._validate_minimal_host_plan_paths(plan, repo, [])
    assert issue is None or issue["reason_code"] != "plan_path_unsafe"


def test_the_unsafe_reason_is_a_deterministic_operator_failure():
    assert "plan_path_unsafe" in runner.DETERMINISTIC_OPERATOR_REASON_CODES


@pytest.fixture
def no_dev_cli(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("dev-cli was called for a plan that names an unsafe path")

    patch_runner(monkeypatch, "_run_cmd", boom)


@pytest.mark.parametrize("plan", UNSAFE_PLANS)
def test_compile_refuses_an_unsafe_plan_before_it_calls_dev_cli(repo, tmp_path, no_dev_cli, plan):
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    compiled, reason_code, message = runner._compile_minimal_host_plan(repo, plan_path)
    assert compiled is None and reason_code == "plan_path_unsafe" and message
    assert json.loads(plan_path.read_text(encoding="utf-8")) == plan


def test_compile_refuses_what_a_stale_dev_cli_compiled_into_git(repo, tmp_path, monkeypatch):
    """The compiled plan is what gets applied, so it is read again whatever the dev-cli that compiled it."""
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps(_minimal("app.py", "old")), encoding="utf-8")
    compiled_path = plan_path.with_name(plan_path.stem + ".compiled.json")

    def stale_compile(argv, cwd, **kwargs):
        compiled_path.write_text(json.dumps(_full(EDIT_PLAN, {"op": "create_file", "path": ".git/hooks/pre-commit", "text": "x"})),
                                 encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    patch_runner(monkeypatch, "_run_cmd", stale_compile)
    compiled, reason_code, message = runner._compile_minimal_host_plan(repo, plan_path)
    assert compiled is None and reason_code == "plan_path_unsafe" and ".git" in message
    assert json.loads(plan_path.read_text(encoding="utf-8")) == _minimal("app.py", "old"), "the unsafe plan must not replace the host plan"


@pytest.mark.parametrize("plan", [_full(EDIT_PLAN), _full(MECHANICAL, {"op": "create_file", "path": "src/new.py", "text": "x"})])
def test_compile_still_passes_an_ordinary_full_plan_through(repo, tmp_path, no_dev_cli, plan):
    plan_path = tmp_path / "edit-plan-1.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    compiled, reason_code, message = runner._compile_minimal_host_plan(repo, plan_path)
    assert (compiled, reason_code, message) == (plan, "", "")
