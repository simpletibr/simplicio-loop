from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1] / "fixtures" / "conformance" / "v1"


def load_corpus(root: Path = ROOT) -> dict:
    manifest = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "simplicio.fast.golden-corpus/v1":
        raise ValueError("golden corpus schema mismatch")
    for entry in manifest.get("files", []):
        path = root / entry["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"golden corpus digest mismatch: {entry['path']}")
    return manifest


class GoldenCorpusContractTest(unittest.TestCase):
    def test_manifest_covers_languages_scenarios_and_tombstone(self) -> None:
        corpus = load_corpus()
        self.assertEqual(
            {"csharp", "python", "rust", "typescript"}, set(corpus["languages"])
        )
        self.assertEqual(
            {"happy_path", "partial_capability", "abstention", "corruption"},
            {item["kind"] for item in corpus["scenarios"]},
        )
        self.assertEqual({"remove"}, {item["kind"] for item in corpus["events"]})

    def test_mutating_fixture_fails_closed_on_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "v1"
            shutil.copytree(ROOT, copy)
            target = copy / "python" / "service.py"
            target.write_text(
                target.read_text(encoding="utf-8") + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                load_corpus(copy)


if __name__ == "__main__":
    unittest.main()
