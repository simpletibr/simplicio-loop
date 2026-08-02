from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from simplicio.changeset_transaction import (
    _hash,
    _state_path,
    existing_transaction_result,
    recover_changeset_transaction,
)
from simplicio.changeset_v2 import adapt_changeset
from simplicio.effect_transaction import EffectTransaction, EffectTransactionError
from tests.python.test_execution_contracts_363 import changeset_payload


def _changeset(*, content: str = "new\n") -> dict[str, object]:
    return {
        "schema": "simplicio.fast.changeset/v2",
        "changeset_id": "cs-498-kill-window",
        "correlation_id": "idem-498-kill-window",
        "generation": "gen-498-kill-window",
        "allowlist": ["a.txt"],
        "operations": [
            {"kind": "replace_range", "path": "a.txt", "start_line": 1, "end_line": 1, "text": content}
        ],
    }


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=10)


def _start_fault_window(tmp_path: Path, point: str) -> tuple[subprocess.Popen[str], Path, str, str, dict]:
    key = f"kill-498-{point}"
    digest = hashlib.sha256(f"digest-{point}".encode()).hexdigest()
    plan = adapt_changeset(_changeset(content="crashed\n"))
    worker = (
        "import json, sys; "
        "from simplicio.changeset_transaction import execute_changeset_transaction; "
        "execute_changeset_transaction(json.loads(sys.argv[2]), root=sys.argv[1], "
        "idempotency_key=sys.argv[3], changeset_digest_value=sys.argv[4])"
    )
    environment = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (repo_root, environment.get("PYTHONPATH", "")) if item
    )
    environment["SIMPLICIO_TRANSACTION_PAUSE_AT"] = point
    environment["SIMPLICIO_TRANSACTION_PAUSE_SECONDS"] = "30"
    process = subprocess.Popen(
        [sys.executable, "-c", worker, str(tmp_path), json.dumps(plan), key, digest],
        cwd=repo_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    state_path = _state_path(tmp_path, key)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.05)
                continue
            if (
                state.get("state")
                == {
                    "after_intent": "INTENT",
                    "after_staged": "STAGED",
                    "after_effect": "STAGED",
                    "after_receipt": "COMMITTED",
                }[point]
            ):
                if point != "after_effect":
                    return process, state_path, key, digest, state
                candidate = Path(str(state["candidate"]))
                if (candidate / "a.txt").read_text(encoding="utf-8") == "crashed\n":
                    return process, state_path, key, digest, state
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=10)
            pytest.fail(f"child exited before {point}: stdout={stdout!r} stderr={stderr!r}")
        time.sleep(0.05)
    _terminate(process)
    pytest.fail(f"child did not reach the {point} fault window")


@pytest.mark.parametrize("point", ["after_intent", "after_staged", "after_effect"])
def test_real_process_kill_before_commit_recovers_without_effect(tmp_path: Path, point: str) -> None:
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    process, state_path, key, digest, state = _start_fault_window(tmp_path, point)
    try:
        _terminate(process)
        recovered = recover_changeset_transaction(
            tmp_path, idempotency_key=key, changeset_digest_value=digest
        )
    finally:
        _terminate(process)

    assert recovered["status"] == "recovered"
    assert target.read_text(encoding="utf-8") == "old\n"
    assert recovered["transaction"]["restored_sha256"]["a.txt"] == _hash(target)
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == "ROLLED_BACK"
    assert not Path(str(state["candidate"])).exists()
    assert not Path(str(state["backup"])).exists()


def test_real_process_kill_after_receipt_replays_and_cleans_artifacts(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("old\n", encoding="utf-8")
    process, state_path, key, digest, state = _start_fault_window(tmp_path, "after_receipt")
    try:
        _terminate(process)
        replay = existing_transaction_result(tmp_path, idempotency_key=key, changeset_digest_value=digest)
    finally:
        _terminate(process)

    assert replay is not None
    assert replay["status"] == "ok"
    assert replay["replayed"] is True
    assert target.read_text(encoding="utf-8") == "crashed\n"
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == "COMMITTED"
    assert not Path(str(state["candidate"])).exists()
    assert not Path(str(state["backup"])).exists()


def _effect_change(key: str):
    payload = changeset_payload()
    payload["change_set_id"] = f"change-498-{key}"
    payload["idempotency_key"] = key
    from simplicio.plan_compiler import ChangeSet

    return ChangeSet.from_dict(payload)


def test_effect_transaction_keyboard_interrupt_after_effect_rolls_back(tmp_path: Path) -> None:
    transaction = EffectTransaction(tmp_path)
    calls: list[str] = []

    def checkpoint(_change):
        calls.append("checkpoint")
        return {"checkpoint_hash": "c" * 64}

    def apply(_change):
        calls.append("apply")
        raise KeyboardInterrupt()

    def rollback(_change, _checkpoint):
        calls.append("rollback")
        return {"status": "restored"}

    with pytest.raises(EffectTransactionError, match="EFFECT_FAILED_ROLLED_BACK"):
        transaction.execute(
            _effect_change("interrupt-effect"),
            checkpoint=checkpoint,
            apply=apply,
            verify=lambda *_args: pytest.fail("verify must not run"),
            rollback=rollback,
        )

    assert calls == ["checkpoint", "apply", "rollback"]
    assert transaction.transitions("interrupt-effect")[-1] == "ROLLED_BACK"


def test_effect_transaction_receipt_is_replayable_after_return_interrupt(tmp_path: Path, monkeypatch) -> None:
    transaction = EffectTransaction(tmp_path)
    change = _effect_change("interrupt-receipt")
    calls: list[str] = []

    def checkpoint(_change):
        calls.append("checkpoint")
        return {"checkpoint_hash": "c" * 64}

    def apply(_change):
        calls.append("apply")
        return {"status": "applied", "before_hash": "a" * 64, "after_hash": "b" * 64}

    def verify(_change, _effect):
        calls.append("verify")
        return {"status": "passed"}

    original_transition = transaction._transition

    def interrupt_after_commit(key, state, receipt=None):
        original_transition(key, state, receipt)
        if state == "COMMITTED":
            raise KeyboardInterrupt()

    monkeypatch.setattr(transaction, "_transition", interrupt_after_commit)
    with pytest.raises(KeyboardInterrupt):
        transaction.execute(
            change,
            checkpoint=checkpoint,
            apply=apply,
            verify=verify,
            rollback=lambda *_args: {"status": "restored"},
        )

    monkeypatch.setattr(transaction, "_transition", original_transition)
    replay = transaction.execute(
        change,
        checkpoint=checkpoint,
        apply=apply,
        verify=verify,
        rollback=lambda *_args: {"status": "restored"},
    )

    assert replay["status"] == "committed"
    assert replay["receipt_hash"]
    assert calls == ["checkpoint", "apply", "verify"]
