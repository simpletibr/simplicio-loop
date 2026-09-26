"""System/e2e proof for two regressions found by an LLM benchmark on released
simplicio-loop 3.43.16:

BUG 1 -- a read-only Mapper re-survey after ``prepare`` (e.g. the host running
``simplicio-loop orient`` again to refresh context before a retry) rewrites
``.simplicio/index-state.json`` -- including its ``updated_at`` timestamp --
even though nothing in the tracked tree changed. The armed run's preflight
compared that ever-changing timestamp as part of the pinned Mapper
"generation" identity, so the re-survey looked like drift and blocked the
next ``wave``/``tick`` with ``active attempt mapper generation changed``.

BUG 2 -- the public flow (SKILL.md: ``simplicio-loop tick <run_id> --repo .
--task-index <N>``, and ``wave``/``batch``/``prism --task-indices``) supports
dispatching one run's tasks from separate processes, one at a time. Once an
earlier task in the same run had already mutated the tree, a later task's own
process re-derived the live repository fingerprint and found it did not match
the frozen `prepare`-time snapshot -- even though the only thing that changed
was the run's OWN already-applied progress -- and blocked with
``stale mapper context: repository changed after planning`` /
``plan_repo_state_stale``. A single ``wave`` process covering every task
never hit this because it validates the batch once, upfront, before any task
in it has run.

This drives the real installed ``simplicio-mapper``/``simplicio-dev-cli``
binaries (no mocks) through the public CLI, against a throwaway git repo,
end to end -- exactly the SKILL.md-documented per-task flow.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("simplicio-dev-cli") is None or shutil.which("simplicio-mapper") is None,
    reason="simplicio-dev-cli/simplicio-mapper (bound operators) not installed",
)

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
Integration verifier: `python3 -c "import calc.ops as m; print(len([n for n in dir(m) if not n.startswith('_')]))"`
System verifier: `python3 -m pytest -q`
Regression verifier: `python3 -m pytest -q`
Benchmark verifier: `python3 -c "pass"`
Coverage verifier: `python3 -m pytest -q --cov=calc --cov-report=term`

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
Integration verifier: `python3 -c "import calc.ops as m; print(len([n for n in dir(m) if not n.startswith('_')]))"`
System verifier: `python3 -m pytest -q`
Regression verifier: `python3 -m pytest -q`
Benchmark verifier: `python3 -c "pass"`
Coverage verifier: `python3 -m pytest -q --cov=calc --cov-report=term`

System: calc
Feature: add pow2(a, b)
Type: Feature

AS a calc user
I WANT a pow2(a, b) function in calc/ops.py
SO THAT I can raise numbers to a power

1. Acceptance Criteria

Scenario 1: pow2 raises to a power
  Given calc/ops.py
  When I call pow2(2, 3)
  Then it returns 8 and tests/test_ops.py has a test_pow test [RN03]

2. Business Rules

RN03 - pow2 lives in calc/ops.py next to div.

8. Additional Information

Independent verifier: `python3 -m pytest -q`
Unit verifier: `python3 -m pytest -q tests/test_ops.py`
Integration verifier: `python3 -c "import calc.ops as m; print(len([n for n in dir(m) if not n.startswith('_')]))"`
System verifier: `python3 -m pytest -q`
Regression verifier: `python3 -m pytest -q`
Benchmark verifier: `python3 -c "pass"`
Coverage verifier: `python3 -m pytest -q --cov=calc --cov-report=term`
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
    # Force this worktree's simplicio_loop package ahead of any globally
    # pip-installed one (the bound operators simplicio-mapper/simplicio-dev-cli
    # remain the real, separately installed binaries on PATH).
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
    payload = _cli(["prepare", "--task", "tasks.md", "--repo", "."], repo)
    assert payload["status"] == "prepared", payload
    return payload["run_id"]


def _chained_plan(ops_find: str, ops_replace: str, import_find: str, import_replace: str,
                  test_find: str, test_replace: str) -> dict:
    return {"operations": [
        {"path": "calc/ops.py", "find": ops_find, "replace": ops_replace},
        {"path": "tests/test_ops.py", "find": import_find, "replace": import_replace},
        {"path": "tests/test_ops.py", "find": test_find, "replace": test_replace},
    ]}


def _write_good_chain(repo: Path, run_id: str) -> None:
    run_dir = repo / ".simplicio" / "loop-runs" / run_id
    plans = [
        _chained_plan(
            "def sub(a, b):\n    return a - b\n",
            "def sub(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
            "from calc.ops import add, sub\n", "from calc.ops import add, sub, mul\n",
            "def test_sub():\n    assert sub(3, 1) == 2\n",
            "def test_sub():\n    assert sub(3, 1) == 2\n\n\ndef test_mul():\n    assert mul(3, 4) == 12\n",
        ),
        _chained_plan(
            "def mul(a, b):\n    return a * b\n",
            "def mul(a, b):\n    return a * b\n\n\ndef div(a, b):\n    return a / b\n",
            "from calc.ops import add, sub, mul\n", "from calc.ops import add, sub, mul, div\n",
            "def test_mul():\n    assert mul(3, 4) == 12\n",
            "def test_mul():\n    assert mul(3, 4) == 12\n\n\ndef test_div():\n    assert div(8, 2) == 4\n",
        ),
        _chained_plan(
            "def div(a, b):\n    return a / b\n",
            "def div(a, b):\n    return a / b\n\n\ndef pow2(a, b):\n    return a ** b\n",
            "from calc.ops import add, sub, mul, div\n", "from calc.ops import add, sub, mul, div, pow2\n",
            "def test_div():\n    assert div(8, 2) == 4\n",
            "def test_div():\n    assert div(8, 2) == 4\n\n\ndef test_pow():\n    assert pow2(2, 3) == 8\n",
        ),
    ]
    for index, plan in enumerate(plans, start=1):
        (run_dir / f"edit-plan-{index}.json").write_text(json.dumps(plan), encoding="utf-8")


def test_tick_from_three_separate_processes_chains_and_verify_reports_verified(tmp_path):
    """BUG 2 regression: dispatch each of 3 dependent tasks through its own,
    separate ``tick`` subprocess (never ``wave``) -- exactly the per-task flow
    SKILL.md documents -- and confirm every task applies onto the tree the
    run's own previous task left, and ``verify`` reaches VERIFIED/MEASURED.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_good_chain(repo, run_id)

    run_dir = repo / ".simplicio" / "loop-runs" / run_id
    for task_index in (1, 2, 3):
        # `tick`'s own public-flow shape varies with how far the run got that
        # call (a raw dispatch/state envelope while other tasks are still
        # pending, a VERIFIED `loop-execution` envelope once the last task
        # completes the whole run) -- the durable per-task operator receipt is
        # the one thing every shape leaves behind, so assert on that instead.
        _cli(["tick", run_id, "--repo", ".", "--task-index", str(task_index)], repo)
        receipt = json.loads((run_dir / f"operator-receipt-{task_index}.json").read_text(encoding="utf-8"))
        assert receipt.get("execution_state") == "applied", (task_index, receipt)
        assert receipt.get("run_id") == run_id, (task_index, receipt)

    ops_py = (repo / "calc" / "ops.py").read_text(encoding="utf-8")
    for name in ("def mul(", "def div(", "def pow2("):
        assert name in ops_py, ops_py

    verify = _cli(["verify", run_id, "--repo", "."], repo)
    state = verify["state"]
    assert state["phase"] == "done", state
    completion = state["completion"]
    assert completion["ready"] is True, completion
    assert completion["verdict"] == "VERIFIED", completion
    assert completion["tag"] == "MEASURED", completion


def test_orient_between_prepare_and_wave_does_not_block_the_wave(tmp_path):
    """BUG 1 regression: re-orienting (a read-only Mapper re-survey) between
    ``prepare`` and ``wave`` -- e.g. the host refreshing context before a
    retry -- must not invalidate the armed run.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_good_chain(repo, run_id)

    orient = subprocess.run(
        [sys.executable, "-m", "simplicio_loop.cli", "orient",
         "--task", "add mul/div/pow2 to calc/ops.py", "--repo", ".", "--json"],
        cwd=str(repo), capture_output=True, text=True, timeout=180,
        env=_env(), stdin=subprocess.DEVNULL,
    )
    assert orient.returncode == 0, orient.stderr

    wave = _cli(["wave", run_id, "--repo", "."], repo)
    workers = (wave.get("dispatch") or wave).get("workers") or []
    assert len(workers) == 3, wave
    statuses = {w["task_index"]: w["status"] for w in workers}
    assert statuses == {1: "succeeded", 2: "succeeded", 3: "succeeded"}, (
        f"expected wave to succeed after an intervening orient, got {statuses}: {wave}"
    )


def test_external_edit_between_ticks_still_blocks(tmp_path):
    """An edit this run did NOT itself produce (a genuine external mutation
    between two ticks of the same run) must still fail closed -- the
    multiprocess chain fix must not weaken drift detection for real drift.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_good_chain(repo, run_id)

    first = _cli(["tick", run_id, "--repo", ".", "--task-index", "1"], repo)
    state = first.get("state") or {}
    operator = state.get("operator") or {}
    assert operator.get("execution_state") == "applied", first

    # An edit this run never produced -- not one of its own applied tasks.
    (repo / "calc" / "ops.py").write_text(
        (repo / "calc" / "ops.py").read_text(encoding="utf-8") + "\n\ndef rogue(x):\n    return x\n",
        encoding="utf-8",
    )

    second = _cli(["tick", run_id, "--repo", ".", "--task-index", "2"], repo)
    dispatch = second.get("dispatch") or {}
    assert dispatch.get("error_type") == "RuntimeError", second
    assert "stale" in str(dispatch.get("error") or "").lower() or "changed" in str(dispatch.get("error") or "").lower(), second
