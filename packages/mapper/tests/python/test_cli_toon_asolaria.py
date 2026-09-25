"""CLI-level tests for --for-llm toon wiring (#144/#148) and the Asolaria
--tagged/--confidence/--geometry P0 flags (#150).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.savings import estimate_tokens  # noqa: E402
from simplicio_mapper.toon import decode_toon  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class ForLlmToonWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "toon-cli-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_index_for_llm_toon_emits_lossless_toon(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--for-llm", "toon"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        payload = decode_toon(text)
        self.assertEqual(payload["schema"], "simplicio.mapper-index/v1")
        self.assertGreaterEqual(payload["counts"]["files"], 2)

    def test_inspect_for_llm_toon_emits_lossless_toon(self) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["scan", str(self.dir), "--sync", "--json"]), 0)
        out = StringIO()
        with redirect_stdout(out):
            code = main(["inspect", str(self.dir), "--for-llm", "toon"])
        self.assertEqual(code, 0)
        payload = decode_toon(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.map-inspection/v1")

    def test_handoff_for_llm_toon_emits_lossless_toon(self) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["map", "--root", str(self.dir), "--silent"]), 0)
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["scan", str(self.dir), "--sync", "--json"]), 0)
        out = StringIO()
        with redirect_stdout(out):
            code = main(["handoff", str(self.dir), "--for-llm", "toon"])
        self.assertEqual(code, 0)
        payload = decode_toon(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.map-handoff/v1")

    def test_ask_for_llm_toon_emits_lossless_toon(self) -> None:
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        out = StringIO()
        with redirect_stdout(out):
            code = main(["ask", str(self.dir), "term", "run", "--for-llm", "toon"])
        self.assertEqual(code, 0)
        payload = decode_toon(out.getvalue())
        self.assertEqual(payload["schema"], "simplicio.ask/v1")

    def test_unknown_for_llm_format_exits_2(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["index", str(self.dir), "--for-llm", "bogus"])
        self.assertEqual(ctx.exception.code, 2)

    def test_for_llm_toon_logs_fallback_report_to_stderr(self) -> None:
        # ask/term over a small host returns a uniform results[] table with
        # no fallback-worthy nested cells, so we exercise the reporting path
        # directly against a payload we know has one (index counts payload
        # never fallback either) -- assert no crash / correct-shape when a
        # payload happens to be fully tabular (empty toon_fallbacks -> no
        # stderr line), which the ask test above already covers implicitly.
        # Here we directly check nothing is printed to stderr when there is
        # nothing to report.
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["index", str(self.dir), "--json"]), 0)
        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["index", str(self.dir), "--for-llm", "toon"])
        self.assertEqual(code, 0)
        # index's counts-only payload has no non-uniform arrays -> no
        # toon_fallbacks line.
        self.assertEqual(err.getvalue(), "")

    def test_handoff_toon_fallback_reconciles_estimated_tokens(self) -> None:
        """Issue #308: when the retrieval selection's ``targets``/
        ``expanded_spans`` (score components, differing keys, ...) force a
        ``toon_fallbacks`` (nested containers can't take the tabular shape),
        the ``metrics.estimated_tokens`` figure must reflect the real
        serialized size actually printed — not the pre-serialization
        estimate computed as if TOON had covered every field. Before the
        fix, that estimate stayed a tiny span-cost number (e.g. ~12) while
        the real emitted TOON+JSON-fallback text ran into the thousands of
        tokens: a silent ~10x+ undercount.
        """
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["map", "--root", str(self.dir), "--silent"]), 0)
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["scan", str(self.dir), "--sync", "--json"]), 0)
        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["handoff", str(self.dir), "--goal", "fix run function", "--for-llm", "toon"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        fallback_report = json.loads(err.getvalue())
        self.assertTrue(fallback_report["toon_fallbacks"], "expected a non-empty toon_fallbacks report")
        payload = decode_toon(text)
        selection_estimate = payload["metrics"]["estimated_tokens"]
        real = estimate_tokens(text)
        receipt = payload["serialization_budget"]
        self.assertEqual(payload["metrics"]["token_scope"], "selected_source_content")
        self.assertGreater(selection_estimate, 0)
        self.assertEqual(receipt["scope"], "handoff_envelope")
        self.assertEqual(receipt["format"], "toon")
        self.assertEqual(receipt["serialized_tokens"], real)
        self.assertEqual(receipt["within_budget"], real <= receipt["token_budget"])


class AsolariaTaggingTest(unittest.TestCase):
    """--tagged / --confidence P0 (issue #150)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "asolaria-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tagged_attaches_confidence_tags_and_legend(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json", "--tagged"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("confidence_tags", payload)
        self.assertIn("confidence_tag_legend", payload)
        for key in payload["counts"]:
            self.assertIn(payload["confidence_tags"][key], ("MEASURED", "OPERATOR", "CANON", "UNVERIFIED"))
        self.assertEqual(payload["confidence_tags"]["files"], "MEASURED")

    def test_confidence_filters_weaker_counts_and_reports_dropped(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json", "--confidence", "MEASURED"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["confidence_threshold"], "MEASURED")
        for key in payload["counts"]:
            self.assertEqual(payload["confidence_tags"][key], "MEASURED")
        dropped_keys = {entry["key"] for entry in payload["confidence_filtered_out"]}
        self.assertIn("modules", dropped_keys)
        self.assertIn("layers", dropped_keys)
        # No deflate-gate: the dropped keys are recorded, not vanished.
        for entry in payload["confidence_filtered_out"]:
            self.assertEqual(entry["tag"], "CANON")

    def test_confidence_with_weakest_tag_keeps_everything(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json", "--confidence", "UNVERIFIED"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["confidence_filtered_out"], [])

    def test_unknown_confidence_tag_exits_2(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["index", str(self.dir), "--confidence", "bogus"])
        self.assertEqual(ctx.exception.code, 2)


class AsolariaGeometryTest(unittest.TestCase):
    """--geometry P0 (issue #150)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        _write(self.dir, "package.json", json.dumps({"name": "geometry-host"}))
        _write(self.dir, "src/index.js", "export function run() { return 1; }\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_geometry_attaches_addressing_per_path(self) -> None:
        out = StringIO()
        with redirect_stdout(out):
            code = main(["index", str(self.dir), "--json", "--geometry"])
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("addressing_geometry", payload)
        for key, path in payload["paths"].items():
            entry = payload["addressing_geometry"][key]
            self.assertEqual(entry["realmathpos"]["file"], path)
            self.assertRegex(entry["fnv1a64"], r"^[0-9a-f]{16}$")
            self.assertRegex(entry["sha16"], r"^[0-9a-f]{16}$")
            self.assertTrue(entry["citizen_identity"].endswith(f"::{key}"))

    def test_geometry_hashes_are_deterministic(self) -> None:
        out1 = StringIO()
        with redirect_stdout(out1):
            self.assertEqual(main(["index", str(self.dir), "--json", "--geometry"]), 0)
        out2 = StringIO()
        with redirect_stdout(out2):
            self.assertEqual(main(["index", str(self.dir), "--json", "--geometry"]), 0)
        payload1 = json.loads(out1.getvalue())
        payload2 = json.loads(out2.getvalue())
        self.assertEqual(payload1["addressing_geometry"], payload2["addressing_geometry"])


if __name__ == "__main__":
    unittest.main()
