from __future__ import annotations

import json
import unittest
from pathlib import Path


class FastestPathQualityCommandTest(unittest.TestCase):
    def test_release_aggregator_is_declared(self) -> None:
        package = json.loads((Path(__file__).parents[2] / "package.json").read_text(encoding="utf-8"))
        command = package["scripts"]["quality:fastest-path"]
        self.assertIn("quality:release", command)
        self.assertIn("mapper_release_manifest.py", command)


if __name__ == "__main__":
    unittest.main()
