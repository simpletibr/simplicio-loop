"""System/e2e proof for two regressions found by a 10-task wave benchmark on
released 3.43.14:

BUG A -- ``wave`` applied only task 1; tasks 2..10 dead-lettered with
``RuntimeError: plan validation failed before operator execution:
plan_repo_state_stale``. Each task's edit-plan is compiled at dispatch against
the tree the *previous* task in the run left behind (SKILL.md's "tasks must
chain"), but the frozen `prepare`-time plan fingerprint was compared against
the post-task-1 tree with no allowance for the run's own prior mutations.

BUG B -- ``simplicio-loop verify`` reported ``VERIFIED``/``MEASURED`` even
though 9/10 tasks never applied (dead-lettered, no operator receipt at all):
the quality-matrix "implementation" gate only checked receipts that happened
to exist on disk, not one per task the run actually scheduled.

This drives the real installed ``simplicio-mapper``/``simplicio-dev-cli``
binaries (no mocks) through the public CLI (``prepare`` -> hand-write
minimal edit-plan-<N>.json files, exactly as a host would -> ``wave`` ->
``verify``), against a throwaway git repo, end to end.
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


def test_wave_chains_three_dependent_tasks_and_verify_reports_verified(tmp_path):
    """BUG A + BUG B regression: 3 tasks editing the same two files in sequence
    (task N's anchor text only exists after task N-1 applied) must all apply,
    and `verify` must then reach `VERIFIED`/`done` -- not dead-letter tasks
    2/3 with plan_repo_state_stale, and not report VERIFIED with anything less
    than every task applied.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    _write_good_chain(repo, run_id)

    wave = _cli(["wave", run_id, "--repo", "."], repo)
    workers = (wave.get("dispatch") or wave).get("workers") or []
    assert len(workers) == 3, wave
    statuses = {w["task_index"]: w["status"] for w in workers}
    assert statuses == {1: "succeeded", 2: "succeeded", 3: "succeeded"}, (
        f"expected all 3 dependent tasks to chain and apply, got {statuses}: {wave}"
    )

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

    quality_matrix = json.loads(
        (repo / ".simplicio" / "loop-runs" / run_id / "quality-matrix.json").read_text(encoding="utf-8")
    )
    assert quality_matrix["requirements"]["implementation"]["status"] == "pass"
    assert quality_matrix["requirements"]["implementation"]["missing_task_indices"] == []


def test_verify_never_reports_verified_when_a_task_plan_is_invalid(tmp_path):
    """A genuinely broken plan (an anchor that does not exist in the tree) must
    dead-letter that one task and keep `verify` fail-closed -- never VERIFIED
    while any scheduled task never produced a receipt.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)
    run_dir = repo / ".simplicio" / "loop-runs" / run_id

    good_task1 = _chained_plan(
        "def sub(a, b):\n    return a - b\n",
        "def sub(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
        "from calc.ops import add, sub\n", "from calc.ops import add, sub, mul\n",
        "def test_sub():\n    assert sub(3, 1) == 2\n",
        "def test_sub():\n    assert sub(3, 1) == 2\n\n\ndef test_mul():\n    assert mul(3, 4) == 12\n",
    )
    broken_task2 = {"operations": [{
        "path": "calc/ops.py",
        "find": "def THIS_ANCHOR_DOES_NOT_EXIST_ANYWHERE(a, b):\n    return a * b\n",
        "replace": "def div(a, b):\n    return a / b\n",
    }]}
    task3_depends_on_task1 = {"operations": [{
        "path": "calc/ops.py",
        "find": "def mul(a, b):\n    return a * b\n",
        "replace": "def mul(a, b):\n    return a * b\n\n\ndef pow2(a, b):\n    return a ** b\n",
    }]}
    (run_dir / "edit-plan-1.json").write_text(json.dumps(good_task1), encoding="utf-8")
    (run_dir / "edit-plan-2.json").write_text(json.dumps(broken_task2), encoding="utf-8")
    (run_dir / "edit-plan-3.json").write_text(json.dumps(task3_depends_on_task1), encoding="utf-8")

    wave = _cli(["wave", run_id, "--repo", "."], repo)
    workers = (wave.get("dispatch") or wave).get("workers") or []
    statuses = {w["task_index"]: w["status"] for w in workers}
    assert statuses[1] == "succeeded", statuses
    assert statuses[2] == "failed", statuses

    verify = _cli(["verify", run_id, "--repo", "."], repo)
    state = verify["state"]
    assert state["phase"] != "done", state
    completion = state["completion"]
    assert completion["ready"] is False, completion
    assert completion["verdict"] != "VERIFIED", completion
