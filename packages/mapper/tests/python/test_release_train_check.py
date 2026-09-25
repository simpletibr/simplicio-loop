from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO

from scripts.release_manifest import release_train_check


class ReleaseTrainCheckTest(unittest.TestCase):
    def test_latest_loop_compatibility_entrypoint_passes_local_gates(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            status = release_train_check(".")
        self.assertEqual(status, 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["schema"], "simplicio.release-train-check/v1")
        self.assertEqual(receipt["status"], "passed")
        self.assertTrue(all(check["status"] == "passed" for check in receipt["checks"]))


if __name__ == "__main__":
    unittest.main()
