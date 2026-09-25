from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from simplicio_mapper.cli import main
from simplicio_mapper.fast_certification import certify_fast, compare_shadow

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "simplicio_mapper" / "contracts" / "fast-certification" / "v1" / "fixtures"


class FastCertificationTest(unittest.TestCase):
    def test_golden_corpus_passes_precision_recall_gates_per_edge_and_language(self) -> None:
        mapper = json.loads((FIXTURES / "golden-corpus.json").read_text(encoding="utf-8"))
        fast = json.loads((FIXTURES / "golden-fast.json").read_text(encoding="utf-8"))
        result = compare_shadow(mapper, fast)
        self.assertTrue(result["canary"]["eligible"])
        self.assertEqual(result["decision_backend"], "mapper")
        self.assertEqual(
            set(result["metrics"]),
            {"calls:csharp", "calls:typescript", "imports:python", "references:rust"},
        )
        self.assertTrue(all(item["precision"] == 1 for item in result["metrics"].values()))
        self.assertTrue(all(item["recall"] == 1 for item in result["metrics"].values()))

    def test_every_shadow_divergence_contains_reproducer_and_classification(self) -> None:
        mapper = {"schema": "mapper/v1", "edges": [{"kind": "calls", "source": "a", "target": "b"}]}
        fast = {"schema": "simplicio.fast-context/v1", "projections": {"edges": []}}
        result = compare_shadow(mapper, fast)
        self.assertFalse(result["canary"]["eligible"])
        self.assertEqual(result["divergences"][0]["classification"], "known_limitation")
        self.assertEqual(result["divergences"][0]["reproducer"]["edge"], ["calls", "a", "b"])

    def test_receipt_observability_and_configuration_only_rollback(self) -> None:
        with patch.dict(os.environ, {"SIMPLICIO_MAPPER_CONTEXT_BACKEND": "fast"}):
            result = certify_fast(
                str(FIXTURES / "golden-corpus.json"),
                str(FIXTURES / "golden-fast.json"),
            )
        self.assertEqual(result["selected_backend"], "fast")
        self.assertEqual(result["receipt"], {"parsed": 1, "reused": 0, "fallback": 0, "degraded": 0})
        self.assertIsNone(result["observability"]["bytes_read"]["value"])
        self.assertTrue(result["observability"]["bytes_read"]["reason"])
        self.assertIn("SIMPLICIO_MAPPER_CONTEXT_BACKEND=mapper", result["compatibility"]["downgrade"])

        with patch.dict(os.environ, {"SIMPLICIO_MAPPER_CONTEXT_BACKEND": "mapper"}):
            rolled_back = certify_fast(
                str(FIXTURES / "golden-corpus.json"),
                str(FIXTURES / "golden-fast.json"),
            )
        self.assertEqual(rolled_back["selected_backend"], "mapper")

    def test_incompatible_schema_and_missing_input_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            incompatible = Path(temporary) / "fast.json"
            incompatible.write_text('{"schema":"simplicio.fast-context/v999"}', encoding="utf-8")
            result = certify_fast(str(FIXTURES / "golden-corpus.json"), str(incompatible))
            self.assertEqual(result["status"], "fallback")
            self.assertEqual(result["receipt"]["fallback"], 1)
            missing = certify_fast("missing.json", str(incompatible))
            self.assertEqual(missing["status"], "degraded")
            self.assertEqual(missing["receipt"]["degraded"], 1)

    def test_cli_is_json_only_and_writes_auditable_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "certification.json"
            output = StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "fast-certify",
                        "--mapper",
                        str(FIXTURES / "golden-corpus.json"),
                        "--fast",
                        str(FIXTURES / "golden-fast.json"),
                        "--out",
                        str(destination),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "ok")
            self.assertEqual(json.loads(destination.read_text(encoding="utf-8"))["status"], "ok")


if __name__ == "__main__":
    unittest.main()
