import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "fixtures" / "evaluation_corpus" / "manifest.json"


class EvaluationCorpusTest(unittest.TestCase):
    def test_manifest_points_to_real_files(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "simplicio.evaluation-corpus/v1")
        for case in payload["cases"]:
            case_root = MANIFEST.parent / case["id"]
            self.assertTrue((case_root / case["task_file"]).is_file())
            self.assertTrue((case_root / case["task_json"]).is_file())
            for relpath in case["expected_targets"] + case["expected_tests"]:
                self.assertTrue((case_root / "source" / relpath).is_file(), relpath)
            for span in case["required_spans"]:
                self.assertTrue((case_root / "source" / span["path"]).is_file(), span["path"])
