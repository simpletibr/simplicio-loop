from __future__ import annotations

import unittest

from scripts.conformance import normalize_spans


class RustContextContractTest(unittest.TestCase):
    def test_span_normalization_is_public_field_exact(self) -> None:
        span = {
            "symbol": "Service.run",
            "kind": "function",
            "file": "service.py",
            "start_line": 1,
            "end_line": 2,
            "source_sha256": "a",
            "content": "x",
            "symbol_id": "b",
            "tokens": 1,
        }
        self.assertEqual([span], normalize_spans([span]))
