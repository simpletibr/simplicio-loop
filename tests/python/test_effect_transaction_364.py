from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from simplicio.effect_transaction import EffectTransaction, EffectTransactionError
from simplicio.plan_compiler import ChangeSet
from tests.python.test_execution_contracts_363 import changeset_payload


def change_set(key: str = "idem-364") -> ChangeSet:
    payload = changeset_payload()
    payload["change_set_id"] = "change-364"
    payload["idempotency_key"] = key
    return ChangeSet.from_dict(payload)


def callbacks(calls: list[str]):
    def checkpoint(_):
        calls.append("checkpoint")
        return {"checkpoint_hash": "c" * 64}

    def apply(_):
        calls.append("apply")
        return {"status": "applied", "before_hash": "a" * 64, "after_hash": "b" * 64}

    def verify(_, __):
        calls.append("verify")
        return {"status": "passed", "signals": ["exit_code:0"]}

    def rollback(_, __):
        calls.append("rollback")
        return {"status": "restored"}

    return checkpoint, apply, verify, rollback


def execute(transaction: EffectTransaction, contract: ChangeSet, calls: list[str]):
    checkpoint, apply, verify, rollback = callbacks(calls)
    return transaction.execute(
        contract,
        checkpoint=checkpoint,
        apply=apply,
        verify=verify,
        rollback=rollback,
    )


def test_success_receipt_contains_every_transition_and_replays(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    calls: list[str] = []
    receipt = execute(transaction, change_set(), calls)
    replay = execute(transaction, change_set(), calls)
    assert replay == receipt
    assert calls == ["checkpoint", "apply", "verify"]
    assert receipt["transitions"] == [
        "GATED",
        "CHECKPOINTED",
        "EFFECT_OBSERVED",
        "VALIDATED",
        "COMMITTED",
    ]
    assert receipt["receipt_hash"]


def test_failure_before_checkpoint_never_applies(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    calls: list[str] = []

    def checkpoint(_):
        calls.append("checkpoint")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        transaction.execute(
            change_set(),
            checkpoint=checkpoint,
            apply=lambda _: calls.append("apply"),
            verify=lambda *_: {},
            rollback=lambda *_: {},
        )
    assert calls == ["checkpoint"]
    assert transaction.transitions("idem-364") == ["GATED", "FAILED_BEFORE_WRITE"]


@pytest.mark.parametrize("failure", ["apply", "verify", "effect_unknown"])
def test_failure_after_checkpoint_rolls_back(failure: str, tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    calls: list[str] = []
    checkpoint, apply, verify, rollback = callbacks(calls)

    if failure == "apply":

        def apply(_):
            raise RuntimeError("edit crash")
    elif failure == "verify":

        def verify(_, __):
            return {"status": "failed"}
    else:

        def apply(_):
            return {"status": "unknown"}

    with pytest.raises(EffectTransactionError, match="EFFECT_FAILED_ROLLED_BACK"):
        transaction.execute(
            change_set(f"idem-{failure}"),
            checkpoint=checkpoint,
            apply=apply,
            verify=verify,
            rollback=rollback,
        )
    assert calls[-1] == "rollback"
    assert transaction.transitions(f"idem-{failure}")[-1] == "ROLLED_BACK"


def test_unverified_rollback_requires_reconciliation(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    checkpoint, _, verify, _ = callbacks([])
    with pytest.raises(EffectTransactionError, match="ROLLBACK_UNVERIFIED"):
        transaction.execute(
            change_set(),
            checkpoint=checkpoint,
            apply=lambda _: {"status": "unknown"},
            verify=verify,
            rollback=lambda *_: {"status": "unknown"},
        )
    assert transaction.transitions("idem-364")[-1] == "RECOVERY_REQUIRED"


def test_concurrent_retry_applies_effect_once(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    calls: list[str] = []

    def run():
        try:
            return execute(transaction, change_set(), calls)
        except EffectTransactionError as error:
            assert error.reason_code == "RECOVERY_REQUIRED"
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: run(), range(20)))
    assert calls.count("apply") == 1
    committed = [result for result in results if result]
    assert committed and all(result == committed[0] for result in committed)


def test_same_key_with_different_changeset_is_rejected(tmp_path) -> None:
    transaction = EffectTransaction(tmp_path)
    execute(transaction, change_set(), [])
    payload = changeset_payload()
    payload["change_set_id"] = "different"
    payload["idempotency_key"] = "idem-364"
    with pytest.raises(EffectTransactionError, match="IDEMPOTENCY_LINEAGE_MISMATCH"):
        execute(transaction, ChangeSet.from_dict(payload), [])
