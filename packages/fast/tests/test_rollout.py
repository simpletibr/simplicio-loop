import json
import tempfile
import unittest
from pathlib import Path

from simplicio_fast.rollout import RolloutController, RolloutError


class RolloutTest(unittest.TestCase):
    def test_transitions_are_receipted_and_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "rollout.json"
            controller = RolloutController(state)
            shadow = controller.transition("shadow", generation="SFAST001:1")
            self.assertEqual("simplicio.fast.rollout-receipt/v1", shadow["schema"])
            canary = controller.transition("canary", generation="SFAST001:2")
            self.assertEqual("shadow", canary["previous_mode"])
            rollback = controller.transition("rollback", reason="validation failed")
            self.assertEqual("rolled-back", rollback["status"])
            self.assertEqual(rollback, json.loads(state.read_text(encoding="utf-8")))

    def test_rollout_rejects_invalid_transition_inputs_and_corrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "rollout.json"
            controller = RolloutController(state)
            with self.assertRaisesRegex(RolloutError, "rollout_mode_invalid"):
                controller.transition("promote")  # type: ignore[arg-type]
            with self.assertRaisesRegex(RolloutError, "rollout_generation_invalid"):
                controller.transition("shadow", generation=1)  # type: ignore[arg-type]
            with self.assertRaisesRegex(RolloutError, "rollout_reason_required"):
                controller.transition("rollback")
            state.write_text('{"mode":"forged"}', encoding="utf-8")
            with self.assertRaisesRegex(RolloutError, "rollout_state_invalid"):
                controller.transition("shadow")
