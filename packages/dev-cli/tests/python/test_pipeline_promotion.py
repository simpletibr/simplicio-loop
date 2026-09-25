from __future__ import annotations

from types import SimpleNamespace

import simplicio.pipeline as pipeline


def test_promote_transaction_handles_missing_transaction() -> None:
    assert pipeline._promote_transaction(SimpleNamespace(tx=None, receipt=None)) == (True, None)


def test_promote_transaction_returns_success_and_calls_transaction() -> None:
    calls = []

    class Transaction:
        def promote(self, receipt):
            calls.append(receipt)

    receipt = {"status": "verified"}
    assert pipeline._promote_transaction(SimpleNamespace(tx=Transaction(), receipt=receipt)) == (True, None)
    assert calls == [receipt]


def test_promote_transaction_normalizes_promotion_error() -> None:
    class Transaction:
        def promote(self, _receipt):
            raise RuntimeError("promotion conflict")

    assert pipeline._promote_transaction(SimpleNamespace(tx=Transaction(), receipt={})) == (
        False,
        "promotion conflict",
    )
