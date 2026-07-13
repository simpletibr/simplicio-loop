"""Effect-freedom tests for the plan compiler (issue #166 slice 3).

`compile_task_spec_to_plan()` and `PlanDAG.validate()` are documented as
"effect-free until the Runtime authorizes" (see `docs/plan-compiler.md`,
"Scope of this slice": nothing calls this compiler from the CLI/pipeline
yet, and no execution/commit happens against the compiled `EffectPlan`s).
This module turns that documentation claim into an executable guarantee for
the unchecked issue #166 acceptance criterion "Dry-run não altera worktree,
ledger, rede externa ou estado persistente": compiling a plan must never
touch the filesystem, open a socket, or spawn a subprocess.
"""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from simplicio.plan_compiler import PlanDAG, compile_task_spec_to_plan
from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.task_spec import TaskSpec

COMPILE_KWARGS = {
    "goal_id": "goal-1",
    "context_snapshot_id": "snap-1",
    "revision": "1",
}


def _task_spec(**overrides: object) -> TaskSpec:
    defaults: dict[str, object] = {
        "task_id": "T1",
        "source": {"kind": "argument"},
        "source_hash": "deadbeef",
        "language": "pt-BR",
        "acceptance_criteria": [{"id": "AC1"}, {"id": "AC2"}],
        "verification_commands": [{"command": "pytest tests/python/test_foo.py -q"}],
    }
    defaults.update(overrides)
    return TaskSpec(**defaults)  # type: ignore[arg-type]


def _snapshot_tree(root: Path) -> dict[str, tuple[int, float]]:
    """Return {relative path: (size, mtime_ns)} for every file under root."""
    snapshot: dict[str, tuple[int, float]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            snapshot[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


@pytest.fixture
def forbid_network_and_subprocess(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail the test immediately if compiling opens a socket or a subprocess."""

    def _forbidden_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan compiler must not open network sockets during dry-run compile")

    def _forbidden_subprocess(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("plan compiler must not spawn subprocesses during dry-run compile")

    monkeypatch.setattr(socket, "socket", _forbidden_socket)
    monkeypatch.setattr(subprocess, "Popen", _forbidden_subprocess)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    monkeypatch.setattr(os, "system", _forbidden_subprocess)
    yield


def test_compile_task_spec_does_not_touch_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbid_network_and_subprocess: None
) -> None:
    """Compiling a plan in an arbitrary cwd must not create or modify any file."""
    (tmp_path / "existing.txt").write_text("untouched", encoding="utf-8")
    before = _snapshot_tree(tmp_path)
    monkeypatch.chdir(tmp_path)

    plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)
    plan.validate(effects=effects, verifications=verifications)
    plan.canonical_hash()

    after = _snapshot_tree(tmp_path)
    assert after == before, "compile_task_spec_to_plan must not write to the worktree"


def test_compile_task_spec_makes_no_network_or_subprocess_calls(
    forbid_network_and_subprocess: None,
) -> None:
    """A compile-only invocation must never reach the network or shell out."""
    plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)
    plan.validate(effects=effects, verifications=verifications)


def test_plan_dag_validate_and_round_trip_do_not_touch_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbid_network_and_subprocess: None
) -> None:
    """Re-validating/serializing an already-compiled plan is equally effect-free."""
    monkeypatch.chdir(tmp_path)
    before = _snapshot_tree(tmp_path)

    plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)
    payload = plan.to_dict()
    restored = PlanDAG.from_dict(payload)
    restored.validate(effects=effects, verifications=verifications)
    canonical_hash(payload)

    after = _snapshot_tree(tmp_path)
    assert after == before, "PlanDAG round-trip/validate must not write to the worktree"


def test_compile_task_spec_does_not_write_designated_ledger_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbid_network_and_subprocess: None
) -> None:
    """No `.simplicio/events.jsonl`-style ledger appears from a bare compile call."""
    monkeypatch.chdir(tmp_path)

    compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)

    assert not (tmp_path / ".simplicio").exists()
    assert list(tmp_path.iterdir()) == []
