from __future__ import annotations

import hashlib
import unittest
from unittest import mock

from simplicio_mapper.mapper import async_inventory


class AsyncInventoryNativeBatchTest(unittest.TestCase):
    def test_native_batch_handles_negotiated_language_and_keeps_python_exports(self) -> None:
        records = [("src/main.py", "import os\n\ndef run():\n    return 1\n")]
        digest = hashlib.sha256(records[0][1].encode()).hexdigest()
        with mock.patch.object(async_inventory._native, "HAS_NATIVE", True), \
                mock.patch.object(async_inventory._native, "parse_batch", return_value=[("src/main.py", digest, ["os"])]), \
                mock.patch.object(async_inventory._native, "CAPABILITIES", {"languages": ["python"], "features": ["batch"]}):
            parsed = async_inventory._parse_from_text_batch(records)

        self.assertEqual(parsed["src/main.py"]["file_hash"], digest)
        self.assertEqual(parsed["src/main.py"]["imports"], ["os"])
        self.assertEqual(parsed["src/main.py"]["exports"], ["run"])

    def test_native_batch_failure_falls_back_to_python(self) -> None:
        records = [("src/main.py", "import os\n\ndef run():\n    return 1\n")]
        with mock.patch.object(async_inventory._native, "HAS_NATIVE", True), \
                mock.patch.object(async_inventory._native, "parse_batch", side_effect=RuntimeError("ABI")), \
                mock.patch.object(async_inventory._native, "CAPABILITIES", {"languages": ["python"], "features": ["batch"]}):
            parsed = async_inventory._parse_from_text_batch(records)

        self.assertEqual(parsed["src/main.py"]["imports"], ["os"])
        self.assertEqual(parsed["src/main.py"]["exports"], ["run"])


if __name__ == "__main__":
    unittest.main()
