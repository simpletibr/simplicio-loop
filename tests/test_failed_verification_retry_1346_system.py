"""System proof for issue #1346 part 1: a task whose dev-cli verification
failed must be retryable.

``simplicio-dev-cli edit --apply`` exits 0 with ``execution_state: applied``
even when its nested ``mutation_receipt.verification.status`` is ``failed``.
The loop used to record that task as ``completed`` so a corrected
``edit-plan-<N>.json`` could never be re-applied through ``tick``. Real
installed operators, no mocks.
"""
from __future__ import annotations

import json
import os
import subprocess
import shutil
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




def _plan(repo: Path, run_id: str, mul_body: str) -> None:
    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    plan = {"operations": [
        {"path": "calc/ops.py",
         "find": "def sub(a, b):\n    return a - b\n",
         "replace": "def sub(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return " + mul_body + "\n"},
        {"path": "tests/test_ops.py",
         "find": "from calc.ops import add, sub\n",
         "replace": "from calc.ops import add, sub, mul\n"},
        {"path": "tests/test_ops.py",
         "find": "def test_sub():\n    assert sub(3, 1) == 2\n",
         "replace": ("def test_sub():\n    assert sub(3, 1) == 2\n\n\n"
                     "def test_mul():\n    assert mul(3, 4) == 12\n")},
    ]}
    (run_dir / "edit-plan-1.json").write_text(json.dumps(plan), encoding="utf-8")


def _tick(repo: Path, run_id: str) -> dict:
    return _cli(["tick", run_id, "--repo", ".", "--task-index", "1"], repo)


def _operator_receipt(repo: Path, run_id: str) -> dict:
    path = repo / ".simplicio-loop" / "loop-runs" / run_id / "operator-receipt-1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_failed_verification_is_retryable_and_corrected_plan_reapplies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    run_id = _prepare(repo)

    _plan(repo, run_id, "a + b")  # wrong: test_mul fails verification
    _tick(repo, run_id)
    first = _operator_receipt(repo, run_id)
    assert first["execution_state"] != "applied", first["execution_state"]
    assert first["reason_code"] == "verification_failed"
    assert first["rollback"]["restored"] is True, first["rollback"]
    assert "def mul" not in (repo / "calc" / "ops.py").read_text(encoding="utf-8")
    completion = json.loads((repo / ".simplicio-loop" / "loop-runs" / run_id
                             / "mapper-operation-completion-1.json").read_text(encoding="utf-8"))
    assert completion["status"] == "failed"

    _plan(repo, run_id, "a * b")  # corrected plan
    _tick(repo, run_id)
    second = _operator_receipt(repo, run_id)
    assert second["execution_state"] == "applied", second
    assert second["receipt_hash"] != first["receipt_hash"]
    assert "return a * b" in (repo / "calc" / "ops.py").read_text(encoding="utf-8")
