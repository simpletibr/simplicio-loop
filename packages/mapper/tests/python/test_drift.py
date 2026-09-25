"""Unit tests for simplicio_mapper.drift (F7 spec-drift + traceability).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli import main  # noqa: E402
from simplicio_mapper.drift import SPEC_DRIFT_SCHEMA, build_spec_drift, render_drift_markdown  # noqa: E402
from simplicio_mapper.mapper import write_architecture_docs  # noqa: E402


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class DriftTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_placeholder_detected_in_real_spec(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, ".specs/product/VISION.md", "# VISION\n\nBuilt for <PRODUCT_NAME> in <DOMAIN>.\n")
        payload = build_spec_drift(str(app_dir))
        self.assertEqual(payload["schema"], SPEC_DRIFT_SCHEMA)
        placeholder_findings = [f for f in payload["findings"] if f["check"] == "placeholder"]
        self.assertEqual(len(placeholder_findings), 2)
        self.assertEqual(placeholder_findings[0]["target"], ".specs/product/VISION.md")

    def test_generic_placeholder_paths_from_manifest_are_exempt(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, ".specs/architecture/ADR-template.md", "# ADR-XXX: <título>\n\nFor <PRODUCT_NAME>.\n")
        _write(app_dir, "template-manifest.json", json.dumps({
            "generic_placeholder_paths": [".specs/architecture/ADR-template.md"],
        }))
        write_architecture_docs(str(app_dir))
        payload = build_spec_drift(str(app_dir))
        self.assertEqual(payload["findings"], [])

    def test_denylisted_tokens_are_not_flagged_as_placeholders(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, "docs/api.md", "Send the token as `<REDACTED>` or a `<JWT>` header.\n")
        payload = build_spec_drift(str(app_dir))
        self.assertEqual([f for f in payload["findings"] if f["check"] == "placeholder"], [])

    def test_orphan_spec_reference_flagged(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, ".specs/product/VISION.md", "See `src/deleted.py` for the entry point.\n")
        payload = build_spec_drift(str(app_dir))
        orphan_findings = [f for f in payload["findings"] if f["check"] == "orphan-spec"]
        self.assertEqual(len(orphan_findings), 1)
        self.assertIn("deleted.py", orphan_findings[0]["evidence"])

    def test_existing_path_reference_is_not_flagged(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, "src/real.py", "def real():\n    return 1\n")
        _write(app_dir, ".specs/product/VISION.md", "See `src/real.py` for the entry point.\n")
        payload = build_spec_drift(str(app_dir))
        orphan_findings = [f for f in payload["findings"] if f["check"] == "orphan-spec"]
        self.assertEqual(orphan_findings, [])
        self.assertIn("src/real.py", payload["traceability"][".specs/product/VISION.md"])

    def test_clean_repo_passes_threshold(self) -> None:
        app_dir = self.dir / "clean"
        _write(app_dir, "package.json", json.dumps({"name": "clean-app"}))
        _write(app_dir, "src/main.py", "def main():\n    return 1\n")
        write_architecture_docs(str(app_dir))
        payload = build_spec_drift(str(app_dir))
        self.assertTrue(payload["score"]["pass"])
        self.assertEqual(payload["score"]["drift_findings"], 0)

    def test_markdown_render_reports_pass_fail(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        payload = build_spec_drift(str(app_dir))
        markdown = render_drift_markdown(payload)
        self.assertIn("PASS", markdown)

    def test_drift_check_command_exit_code(self) -> None:
        app_dir = self.dir / "app"
        _write(app_dir, "package.json", json.dumps({"name": "drift-app"}))
        _write(app_dir, ".specs/product/VISION.md", "Built for <PRODUCT_NAME>.\n")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["drift", str(app_dir), "--check", "--threshold", "0", "--json"])
        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["score"]["pass"])

    def test_product_scope_is_separate_from_template_scope(self) -> None:
        app_dir = self.dir / "scoped"
        _write(app_dir, "package.json", json.dumps({"name": "scoped-app"}))
        _write(app_dir, ".specs/product/VISION.md", "A filled product vision.\n")
        _write(app_dir, "docs/template.md", "Use <PRODUCT_NAME> here.\n")
        _write(app_dir, "template-manifest.json", json.dumps({
            "product_paths": [".specs/product/VISION.md"],
            "template_paths": ["docs/template.md"],
        }))
        product = build_spec_drift(str(app_dir), scope="product", threshold=0)
        template = build_spec_drift(str(app_dir), scope="template", threshold=0)
        self.assertTrue(product["score"]["pass"])
        self.assertEqual(product["scope"], "product")
        self.assertEqual(len(template["findings"]), 1)
        self.assertEqual(template["findings"][0]["target"], "docs/template.md")


if __name__ == "__main__":
    unittest.main()
