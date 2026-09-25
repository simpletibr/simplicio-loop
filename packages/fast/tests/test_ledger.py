from __future__ import annotations

import dataclasses
import unittest

from simplicio_fast.ledger import DeliveryLedger, LedgerError, ZERO_HASH


class DeliveryLedgerTest(unittest.TestCase):
    def test_chain_idempotency_winner_and_seal(self) -> None:
        ledger = DeliveryLedger("repo")
        first = ledger.append_event(
            "TASK_ACCEPTED", task_id="task", attempt_id="a1", producer="loop"
        )
        same = ledger.append_event(
            "TASK_ACCEPTED", task_id="task", attempt_id="a1", producer="loop"
        )
        self.assertEqual(first.event_hash, same.event_hash)
        ledger.append_event(
            "TEST_EVIDENCE",
            task_id="task",
            attempt_id="a1",
            candidate_id="c1",
            producer="pytest",
            metadata={"passed": True},
        )
        ledger.promote_winner("task", "a1", "c1", producer="loop")
        sealed = ledger.seal_delivery("task", "a1", producer="loop")
        self.assertEqual("DELIVERY_SEALED", sealed.event_type)
        self.assertEqual("valid", ledger.verify_all()["status"])
        self.assertEqual(ZERO_HASH, first.prev_event_hash)
        self.assertEqual(4, len(ledger.lookup_attempt("task", "a1")))

    def test_tamper_and_fencing_fail_closed(self) -> None:
        ledger = DeliveryLedger("repo")
        ledger.append_event(
            "TASK_ACCEPTED", task_id="task", attempt_id="a1", producer="loop"
        )
        ledger.promote_winner("task", "a1", "c1", producer="loop")
        with self.assertRaises(LedgerError) as error:
            ledger.promote_winner("task", "a1", "c2", producer="loop")
        self.assertEqual("winner_fence", error.exception.reason_code)
        ledger._events[0] = dataclasses.replace(
            ledger._events[0], metadata={"tampered": True}
        )
        self.assertEqual("invalid", ledger.verify_all()["status"])

    def test_seal_requires_winner_and_redacts_secrets(self) -> None:
        ledger = DeliveryLedger("repo")
        with self.assertRaises(LedgerError) as error:
            ledger.seal_delivery("task", "a1", producer="loop")
        self.assertEqual("winner_required", error.exception.reason_code)
        with self.assertRaises(LedgerError) as error:
            ledger.append_event(
                "TASK_ACCEPTED",
                task_id="task",
                attempt_id="a1",
                producer="loop",
                metadata={"api_key": "hidden"},
            )
        self.assertEqual("secret_redaction", error.exception.reason_code)
