"""System/e2e proof for issue #1328 bug 1: a false-positive
``plan_repo_state_stale`` after the run's own mutation.

Root cause (confirmed against the real affected runs
``run-20260926-074454-qdptdesh``/``run-20260926-080225-5s223dnu``, measured
in the #1323 wave): when a task's dev-cli invocation reports
an *uncertain* outcome (client-side timeout after the underlying subprocess
was killed, ``execution_state: "uncertain"``, ``returncode: None`` --
``runner._execute_operator_effect_unchecked``'s own comment: "A timeout does
not prove that the child stopped before writing"), the real mutation can
still have landed on disk. ``execute_operator`` only rebinds
``state["repo_state_chain"]`` to the post-attempt tree when
``returncode == 0`` -- never for an uncertain attempt -- so a LATER
dependent task's freshness check (``_execute_operator_unleased``) compares
the now-actually-mutated tree against the stale, frozen ``prepare``-time
``plan.repo_state`` and raises ``RuntimeError: plan validation failed before
operator execution: plan_repo_state_stale``, dead-lettering a task whose only
"problem" is that an earlier task in the very same run really did mutate the
tree it depends on.

This test drives the real installed ``simplicio-mapper`` (orient/prepare)
through the public CLI, then calls ``simplicio_loop.runner.execute_operator``
directly (in-process, so the first, uncertain-outcome call can be
monkeypatched) to force exactly this race deterministically instead of
relying on a genuine 600-second subprocess timeout:

* task 1's underlying dev-cli mutation is executed for REAL (the real
  ``simplicio-dev-cli edit --apply`` binary actually applies edit-plan-1.json
  to the real repo) -- only the *reported outcome* is overridden to
  ``uncertain``/``returncode: None``, exactly mirroring what a killed-on-
  timeout subprocess that had already finished writing looks like from the
  caller's side.
* task 2 then runs for real, unmocked, through the real dev-cli binary.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from tests.runner_patch import patch_runner


REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [
    pytest.mark.usefixtures("tree_operators"),
    pytest.mark.usefixtures("admitting_capacity"),  # host pressure must not decide these dispatch tests
]

TASKS_MD = """System: calc
Feature: add mul(a, b)
Type: Feature

AS a calc user
I WANT a mul(a, b) function in calc/ops.py
SO THAT I can multiply numbers

1. Acceptance Criteria

Scenario 1: mul multiplies two numbers
  Given calc/ops.py
  When I call mul(3, 4)
  Then it returns 12 and tests/test_ops.py has a test_mul test [RN01]

2. Business Rules

RN01 - mul lives in calc/ops.py next to add and sub.

8. Additional Information

Independent verifier: `python3 -m pytest -q`
Unit verifier: `python3 -m pytest -q tests/test_ops.py`

System: calc
Feature: add div(a, b)
Type: Feature

AS a calc user
I WANT a div(a, b) function in calc/ops.py
SO THAT I can divide numbers

1. Acceptance Criteria

Scenario 1: div divides two numbers
  Given calc/ops.py
  When I call div(8, 2)
  Then it returns 4 and tests/test_ops.py has a test_div test [RN02]

2. Business Rules

RN02 - div lives in calc/ops.py next to mul.

8. Additional Information

Independent verifier: `python3 -m pytest -q`
Unit verifier: `python3 -m pytest -q tests/test_ops.py`
"""


def _init_repo(root: Path) -> None:
    (root / "calc").mkdir()
    (root / "tests").mkdir()
    (root / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "calc" / "ops.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_ops.py").write_text(
        "from calc.ops import add, sub\n\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_sub():\n    assert sub(3, 1) == 2\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root, check=True,
    )
    (root / "tasks.md").write_text(TASKS_MD, encoding="utf-8")


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _cli(args: list, cwd: Path) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=180,
        env=_env(), stdin=subprocess.DEVNULL,
    )
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError) as exc:  # pragma: no cover - debugging aid
        raise AssertionError(
            f"non-JSON output for {args}: rc={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        ) from exc


def _prepare(repo: Path) -> str:
    oriented = _cli(["orient", "--repo", ".", "--task", "survey the repo", "--json"], repo)
    assert oriented.get("status") != "BLOCKED", oriented
    payload = _cli(["prepare", "--task", "tasks.md", "--repo", "."], repo)
    assert payload["status"] == "prepared", payload
    return payload["run_id"]


def _write_edit_plans(repo: Path, run_id: str) -> None:
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    plan1 = {"operations": [
        {"path": "calc/ops.py",
         "find": "def sub(a, b):\n    return a - b\n",
         "replace": "def sub(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"},
        {"path": "tests/test_ops.py",
         "find": "from calc.ops import add, sub\n",
         "replace": "from calc.ops import add, sub, mul\n"},
        {"path": "tests/test_ops.py",
         "find": "def test_sub():\n    assert sub(3, 1) == 2\n",
         "replace": ("def test_sub():\n    assert sub(3, 1) == 2\n\n\n"
                     "def test_mul():\n    assert mul(3, 4) == 12\n")},
    ]}
    plan2 = {"operations": [
        {"path": "calc/ops.py",
         "find": "def mul(a, b):\n    return a * b\n",
         "replace": "def mul(a, b):\n    return a * b\n\n\ndef div(a, b):\n    return a / b\n"},
        {"path": "tests/test_ops.py",
         "find": "from calc.ops import add, sub, mul\n",
         "replace": "from calc.ops import add, sub, mul, div\n"},
        {"path": "tests/test_ops.py",
         "find": "def test_mul():\n    assert mul(3, 4) == 12\n",
         "replace": ("def test_mul():\n    assert mul(3, 4) == 12\n\n\n"
                     "def test_div():\n    assert div(8, 2) == 4\n")},
    ]}
    (run_dir / "edit-plan-1.json").write_text(json.dumps(plan1), encoding="utf-8")
    (run_dir / "edit-plan-2.json").write_text(json.dumps(plan2), encoding="utf-8")


def test_dependent_task_survives_a_prior_uncertain_own_mutation(tmp_path, monkeypatch):
    """BUG 1: task 2 must not dead-letter with ``plan_repo_state_stale`` just
    because task 1's OWN mutation landed for real behind an ``uncertain``
    (timed-out) client-side report.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_edit_plans(repo, run_id)

    # Force the real (mapper-route) dispatch path -- exactly what `wave` uses --
    # to run its per-task workers as in-process threads rather than a separate
    # child process, so the monkeypatch on `_execute_operator_effect_unchecked``
    # below actually reaches the operator call this test needs to intercept.
    monkeypatch.setenv("SIMPLICIO_LOOP_DISPATCH_MODE", "thread")

    from simplicio_loop import runner  # local import: env vars above must land first

    real_unchecked = runner._execute_operator_effect_unchecked
    calls = {"count": 0}

    def fake_unchecked(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            # Task 1's FIRST dispatch attempt: the real dev-cli call actually
            # runs and mutates the repo -- only the *reported* outcome is
            # downgraded to "uncertain", exactly like a subprocess that
            # finished writing before being killed on a client-side timeout.
            real_unchecked(**kwargs)
            return {
                "returncode": None,
                "stdout": {},
                "stderr": "timed out after 30s",
                "source": "live_cli",
                "effect_receipt": None,
                "uncertain": True,
            }
        return real_unchecked(**kwargs)

    patch_runner(monkeypatch, "_execute_operator_effect_unchecked", fake_unchecked)

    batch = runner.execute_operator_batch(str(repo), run_id, task_indices=[1, 2], retry_budget=1)
    workers = {int(w["task_index"]): w for w in batch["workers"]}

    ops_py = (repo / "calc" / "ops.py").read_text(encoding="utf-8")
    assert "def mul(" in ops_py, "task 1's real mutation must have landed despite the uncertain report"

    # This is the actual regression (issue #1328 bug 1): task 2 must not
    # dead-letter with `plan_repo_state_stale` just because task 1's own
    # (uncertain-reported) mutation really did change the tree it depends on.
    assert workers[2]["status"] == "succeeded", workers[2]
    assert workers[2].get("reason_code") != "plan_validation_failed", workers[2]

    ops_py = (repo / "calc" / "ops.py").read_text(encoding="utf-8")
    assert "def div(" in ops_py, ops_py


def test_genuine_external_edit_between_prepare_and_dispatch_still_blocks(tmp_path, monkeypatch):
    """Regression guard: an external edit made between ``prepare`` and
    dispatch (not this run's own mutation) must still fail closed as stale.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_edit_plans(repo, run_id)

    # An edit unrelated to this run lands on the target file between `prepare`
    # and dispatch -- e.g. a human or another process touching the repo.
    ops_path = repo / "calc" / "ops.py"
    ops_path.write_text(ops_path.read_text(encoding="utf-8") + "\n\ndef noop():\n    return None\n",
                        encoding="utf-8")

    from simplicio_loop import runner

    with pytest.raises(RuntimeError, match="plan_repo_state_stale"):
        runner.execute_operator(str(repo), run_id, task_index=1)
