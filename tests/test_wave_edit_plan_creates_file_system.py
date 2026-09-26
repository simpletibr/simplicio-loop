"""issue #1331: a wave edit plan operation with ``find: ""`` against a path
that does not yet exist creates that file -- the same semantics the hot-path
``apply``/``ops.json`` flow already promised. This drives the real installed
``simplicio-mapper``/``simplicio-dev-cli`` binaries through the public CLI
(``orient`` -> ``prepare`` -> hand-written edit-plan-1.json -> ``wave``),
against a throwaway git repo, end to end -- a TDD delivery whose only change
is a brand-new test file can now go through the wave.
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
Feature: add a regression test file for calc.ops
Type: Creation
Target: tests/test_new_thing.py

AS a maintainer
I WANT a new test file tests/test_new_thing.py
SO THAT calc.ops.add has a dedicated regression test

1. Acceptance Criteria

Scenario 1: the new test file exists and passes
  Given the repository
  When tests/test_new_thing.py is created
  Then python3 -m pytest -q tests/test_new_thing.py passes [RN01]

2. Business Rules

RN01 - the file is created, not merged into an existing test module.

8. Additional Information

Independent verifier: `python3 -m pytest -q tests/test_new_thing.py`
"""


TASKS_MD_EXISTING_TARGET = """System: calc
Feature: touch an existing test file
Type: Feature
Target: tests/test_existing.py

AS a maintainer
I WANT tests/test_existing.py updated
SO THAT it stays current

1. Acceptance Criteria

Scenario 1: the file is updated
  Given tests/test_existing.py
  When it changes
  Then python3 -m pytest -q tests/test_existing.py passes [RN01]

2. Business Rules

RN01 - tests/test_existing.py already exists; this is an edit, not a creation.

8. Additional Information

Independent verifier: `python3 -m pytest -q tests/test_existing.py`
"""


def _init_repo(root: Path) -> None:
    (root / "calc").mkdir()
    (root / "tests").mkdir()
    (root / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (root / "calc" / "ops.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=root, check=True,
    )
    (root / "tasks.md").write_text(TASKS_MD, encoding="utf-8")


def _env() -> dict:
    env = dict(os.environ)
    # Force THIS worktree's simplicio_loop AND packages/dev-cli/packages/mapper
    # ahead of any globally pip-installed editable copy that may point at a
    # different worktree -- the bound operator binaries on PATH must run
    # against the code this issue actually changed.
    extra = os.pathsep.join([
        str(REPO_ROOT),
        str(REPO_ROOT / "packages" / "dev-cli"),
        str(REPO_ROOT / "packages" / "mapper"),
    ])
    env["PYTHONPATH"] = extra + os.pathsep + env.get("PYTHONPATH", "")
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


def test_wave_edit_plan_creates_a_new_test_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    oriented = _cli(["orient", "--repo", ".", "--task", "survey the repo", "--json"], repo)
    assert oriented.get("status") != "BLOCKED", oriented

    payload = _cli(["prepare", "--task", "tasks.md", "--repo", "."], repo)
    assert payload["status"] == "prepared", payload
    run_id = payload["run_id"]

    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    plan = {"operations": [{
        "path": "tests/test_new_thing.py",
        "find": "",
        "replace": (
            "from calc.ops import add\n\n\n"
            "def test_add_regression():\n    assert add(2, 3) == 5\n"
        ),
    }]}
    (run_dir / "edit-plan-1.json").write_text(json.dumps(plan), encoding="utf-8")

    wave = _cli(["wave", run_id, "--repo", "."], repo)
    workers = (wave.get("dispatch") or wave).get("workers") or []
    assert len(workers) == 1, wave
    assert workers[0]["status"] == "succeeded", wave

    created = repo / "tests" / "test_new_thing.py"
    assert created.is_file(), "wave did not create the new file"
    assert "def test_add_regression" in created.read_text(encoding="utf-8")

    verify_proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_new_thing.py"],
        cwd=str(repo), capture_output=True, text=True, timeout=60,
    )
    assert verify_proc.returncode == 0, verify_proc.stdout + verify_proc.stderr


def test_wave_edit_plan_create_blocks_when_target_already_exists_and_nonempty(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    (repo / "tests" / "test_existing.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (repo / "tasks.md").write_text(TASKS_MD_EXISTING_TARGET, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "existing test"],
        cwd=repo, check=True,
    )

    oriented = _cli(["orient", "--repo", ".", "--task", "survey the repo", "--json"], repo)
    assert oriented.get("status") != "BLOCKED", oriented
    payload = _cli(["prepare", "--task", "tasks.md", "--repo", "."], repo)
    assert payload["status"] == "prepared", payload
    run_id = payload["run_id"]

    run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
    plan = {"operations": [{"path": "tests/test_existing.py", "find": "", "replace": "overwritten\n"}]}
    (run_dir / "edit-plan-1.json").write_text(json.dumps(plan), encoding="utf-8")

    wave = _cli(["wave", run_id, "--repo", "."], repo)
    workers = (wave.get("dispatch") or wave).get("workers") or []
    assert len(workers) == 1, wave
    assert workers[0]["status"] != "succeeded", wave
    # the existing file must be untouched
    assert (repo / "tests" / "test_existing.py").read_text(encoding="utf-8") == "def test_x():\n    assert True\n"
