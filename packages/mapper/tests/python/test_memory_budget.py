from __future__ import annotations

import unittest

from simplicio_mapper.mapper.memory_budget import MemoryBudget, MemoryBudgetExceeded


class MemoryBudgetTest(unittest.TestCase):
    def test_reserve_release_and_receipt_are_deterministic(self) -> None:
        budget = MemoryBudget(soft_limit_bytes=10, hard_limit_bytes=20)
        self.assertTrue(budget.reserve(8))
        self.assertFalse(budget.reserve(4))
        budget.record_spill()
        budget.release(4)
        self.assertEqual(budget.receipt()["peak_bytes"], 12)
        self.assertEqual(budget.receipt()["spills"], 1)

    def test_hard_limit_fails_closed(self) -> None:
        budget = MemoryBudget(soft_limit_bytes=10, hard_limit_bytes=12)
        with self.assertRaises(MemoryBudgetExceeded):
            budget.reserve(13)


if __name__ == "__main__":
    unittest.main()
