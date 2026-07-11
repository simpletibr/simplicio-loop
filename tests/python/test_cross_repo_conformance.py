from __future__ import annotations

import unittest

from scripts.cross_repo_conformance import _validate_handoff


class CrossRepoConformanceTest(unittest.TestCase):
    def test_negative_schema_mutation_is_rejected(self) -> None:
        self.assertEqual(_validate_handoff({"schema": "simplicio.map-handoff/v999"}), [
            'schema must be "simplicio.map-handoff/v1"',
            "context_pack must be an object",
            "ready must be boolean",
        ])

    def test_real_shape_requires_context_and_ready(self) -> None:
        self.assertEqual(_validate_handoff({"schema": "simplicio.map-handoff/v1", "context_pack": {}, "ready": False}), [])
