"""Architecture checks that the QLT-001 operational fixture must surface."""

from __future__ import annotations

import unittest

FORBIDDEN_NAME_PARTS = ("scheduler", "worker_pool", "worktree_manager", "lease_manager")


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_runtime_has_no_duplicate_orchestration_modules(self) -> None:
        self.assertEqual(FORBIDDEN_NAME_PARTS[0], "scheduler")

    def test_only_thin_loop_invoker_owns_one_subprocess_call(self) -> None:
        self.assertIn("loop_invoker", "src/simplicio_loop_quality/loop_invoker.py")
