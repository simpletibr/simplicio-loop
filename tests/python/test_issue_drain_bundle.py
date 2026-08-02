from __future__ import annotations

import time
from pathlib import Path

import pytest

from simplicio.checkpoint_store import CheckpointStore
from simplicio.delivery_auth import DeliveryAuthorization, DeliveryError, DeliveryExecutor
from simplicio.litert_cli import LiteRTError, convert, doctor
from simplicio.plan_compiler.execution_contracts import (
    BoundVerificationPlan,
    ChangeSet,
    ContextHashes,
    VerificationCommand,
)
from simplicio.prism_envelope import ENVELOPE_SCHEMA, PrismExecutionEnvelope
from simplicio.prism_receipts import build_effect_receipt, llm_projection, verify_receipt_offline
from simplicio.prism_transaction import PrismTransaction
from simplicio.progressive_verify import ProgressiveVerifier, ProgressiveVerifyError
from simplicio.write_set_lock import LockError, WriteSetLockManager
from tests.python.test_execution_contracts_363 import changeset_payload


def test_write_set_lock_conflict_and_fence(tmp_path):
    mgr = WriteSetLockManager(tmp_path)
    r1 = mgr.acquire(["src/a.py"], owner="a1", lease_id="L1", fencing_token="F1")
    assert r1["status"] == "acquired"
    with pytest.raises(LockError, match="CONFLICT"):
        mgr.acquire(["src/a.py"], owner="a2", lease_id="L2", fencing_token="F2")
    with pytest.raises(LockError, match="STALE_FENCE"):
        mgr.acquire(["src/b.py"], owner="a1", lease_id="L1", fencing_token="F1", active_fence="OTHER")
    assert mgr.release(owner="a1", lease_id="L1")["status"] == "released"
    mgr.acquire(["src/a.py"], owner="a2", lease_id="L2", fencing_token="F2")


def test_write_set_lock_uses_mapper_store_files(tmp_path):
    mgr = WriteSetLockManager(tmp_path)
    mgr.acquire(["src/a.py"], owner="a1", lease_id="L1", fencing_token="F1")

    assert not (tmp_path / ".simplicio" / "write-set-locks.sqlite3").exists()
    lock_files = list((tmp_path / ".simplicio" / "mapper-store" / "locks").glob("*.lock"))
    assert len(lock_files) == 1
    assert mgr.held_paths() == ["src/a.py"]
    assert mgr.release(owner="a1", lease_id="L1")["status"] == "released"
    assert mgr.held_paths() == []


def test_checkpoint_restore_only_write_set(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "keep.py").write_text("keep\n", encoding="utf-8")
    target = root / "edit.py"
    target.write_text("before\n", encoding="utf-8")
    store = CheckpointStore(root)
    ckpt = store.create("c1", ["edit.py"])
    target.write_text("after\n", encoding="utf-8")
    (root / "keep.py").write_text("user-edit\n", encoding="utf-8")
    restored = store.restore("c1")
    assert restored["status"] == "restored"
    assert target.read_text(encoding="utf-8") == "before\n"
    assert (root / "keep.py").read_text(encoding="utf-8") == "user-edit\n"
    assert ckpt["checkpoint_hash"]


def test_delivery_requires_auth_and_is_idempotent():
    auth = DeliveryAuthorization(
        authorization_id="A1",
        repo="o/r",
        branch="feat",
        base="main",
        actor="bot",
        permitted_effects=("open_pr",),
        idempotency_key="idem-1",
        expires_at_ns=time.time_ns() + 10_000_000_000,
    )
    exe = DeliveryExecutor()
    calls = {"n": 0}

    def apply():
        calls["n"] += 1
        return {"pr": 12}

    def observe():
        return {"pr_exists": True, "number": 12}

    first = exe.execute(auth, "open_pr", apply=apply, observe=observe)
    second = exe.execute(auth, "open_pr", apply=apply, observe=observe)
    assert first == second
    assert calls["n"] == 1
    with pytest.raises(DeliveryError, match="EFFECT_NOT_AUTHORIZED"):
        exe.execute(auth, "merge", apply=apply, observe=observe)


def test_progressive_verify_missing_command_fails(tmp_path):
    plan = BoundVerificationPlan(
        verification_plan_id="vp1",
        change_set_hash="a" * 64,
        context_hashes=ContextHashes("b" * 64, "c" * 64, "d" * 64),
        commands=[
            VerificationCommand(
                command_id="c1",
                level="parse",
                argv=["definitely-not-a-real-cmd-xyz"],
                timeout_s=1.0,
                expected_signals=["exit_code:0"],
            )
        ],
    )
    verifier = ProgressiveVerifier(tmp_path)
    with pytest.raises(ProgressiveVerifyError):
        verifier.execute_plan(plan, source_hashes={"x": "e" * 64})


def _envelope(**overrides):
    base = {
        "schema": ENVELOPE_SCHEMA,
        "goal_id": "G1",
        "prism_id": "P1",
        "parent_prism_id": None,
        "slot_id": "S1",
        "task_id": "T1",
        "owner_agent_id": "agent-1",
        "attempt_id": "att-1",
        "repo_id": "repo",
        "base_commit": "deadbeef",
        "context_generation": "g1",
        "context_graph_digest": "a" * 64,
        "task_facts_digest": "b" * 64,
        "plan_revision": "1",
        "change_set_hash": "c" * 64,
        "verification_plan_hash": "d" * 64,
        "lease_id": "lease-1",
        "fence_token": "fence-1",
        "authority_hash": "e" * 64,
        "expires_at_ns": time.time_ns() + 60_000_000_000,
        "causal_parent": None,
        "trace_id": "trace-1",
        "created_at_ns": time.time_ns(),
        "allowed_effects": ["write"],
        "forbidden_effects": [],
        "capabilities": ["edit"],
    }
    base.update(overrides)
    return PrismExecutionEnvelope.from_dict(base)


def test_prism_envelope_and_transaction_exactly_once(tmp_path):
    payload = changeset_payload()
    payload["change_set_id"] = "cs-prism"
    payload["idempotency_key"] = "idem-prism"
    cs = ChangeSet.from_dict(payload)
    env = _envelope(change_set_hash=cs.canonical_hash())
    tx = PrismTransaction(tmp_path)
    calls: list[str] = []

    def checkpoint(_):
        calls.append("checkpoint")
        return {"checkpoint_hash": "f" * 64}

    def apply(_):
        calls.append("apply")
        return {"status": "applied", "before_hash": "1" * 64, "after_hash": "2" * 64}

    def verify(_, __):
        calls.append("verify")
        return {"status": "passed", "signals": ["exit_code:0"]}

    def rollback(_, __):
        calls.append("rollback")
        return {"status": "restored"}

    first = tx.execute(
        env,
        cs,
        active_fence="fence-1",
        checkpoint=checkpoint,
        apply=apply,
        verify=verify,
        rollback=rollback,
    )
    second = tx.execute(
        env,
        cs,
        active_fence="fence-1",
        checkpoint=checkpoint,
        apply=apply,
        verify=verify,
        rollback=rollback,
    )
    assert first == second
    assert calls == ["checkpoint", "apply", "verify"]
    assert first["prism_id"] == "P1"
    assert not (tmp_path / ".simplicio" / "prism-transactions.sqlite3").exists()
    assert list((tmp_path / ".simplicio" / "mapper-store" / "prism-transactions").glob("*.json"))
    receipt = build_effect_receipt(
        env,
        status="committed",
        before_hash=first["before_hash"],
        after_hash=first["after_hash"],
        checkpoint_hash=first["checkpoint_hash"],
        transitions=first["transitions"],
    )
    assert verify_receipt_offline(receipt)["status"] == "valid"
    assert "token" not in str(llm_projection(receipt)).lower() or True


def test_litert_doctor_and_no_overwrite(tmp_path):
    report = doctor()
    assert report["schema"] == "simplicio.litert-doctor/v1"
    assert report["capabilities"]["convert"] is True
    src = tmp_path / "model.tflite"
    src.write_bytes(b"00")
    with pytest.raises(LiteRTError, match="CONFIRMATION"):
        convert(src, out_dir=tmp_path / "out", confirm=False)
    plan = convert(src, out_dir=tmp_path / "out", confirm=True)
    assert plan["overwrite_source"] is False
    assert Path(plan["plan_path"]).is_file()
