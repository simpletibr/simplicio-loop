import os
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.contract import find_contract_root, validate_payload
from simplicio_mapper.mapper import build_artifacts
from simplicio_mapper.visualization import build_visualization_bundle, preview_source


class VisualizationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def greet():\n    return 'safe'\n", encoding="utf-8")
        (self.root / "src" / "app.ts").write_text("export function run() { return 1; }\n", encoding="utf-8")
        (self.root / ".env").write_text("TOKEN=do-not-preview\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_bundle_has_normalized_language_diagnostics_and_stable_ids(self) -> None:
        artifacts = build_artifacts(str(self.root), output_dir=".simplicio")
        first = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        second = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        self.assertEqual(first, second)
        self.assertEqual(validate_payload(first, find_contract_root(str(self.root)))[1], [])
        languages = {item["path"]: item["language"] for item in first["language_diagnostics"]}
        self.assertEqual(languages["src/app.py"], "python")
        self.assertEqual(languages["src/app.ts"], "typescript")
        self.assertIn("language-diagnostics", first["capabilities"])

    def test_preview_is_bounded_and_reports_fingerprint(self) -> None:
        payload = preview_source(str(self.root), path="src/app.py", max_bytes=8, max_lines=1)
        self.assertEqual(validate_payload(payload, find_contract_root(str(self.root)))[1], [])
        self.assertTrue(payload["truncated"])
        self.assertEqual(payload["language"], "python")
        self.assertTrue(payload["read_only"])
        self.assertEqual(len(payload["revision_fingerprint"]), 64)

    def test_preview_denies_traversal_symlinks_secrets_and_binary(self) -> None:
        cases = ["../outside.py", ".env"]
        for path in cases:
            with self.subTest(path=path), self.assertRaises(ValueError):
                preview_source(str(self.root), path=path)
        (self.root / "image.bin").write_bytes(b"\x00\x01")
        with self.assertRaises(ValueError):
            preview_source(str(self.root), path="image.bin")
        link = self.root / "src" / "link.py"
        outside = self.root.parent / "outside-preview.py"
        outside.write_text("nope", encoding="utf-8")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable on this Windows environment")
        with self.assertRaises(ValueError):
            preview_source(str(self.root), path="src/link.py")

    def test_symbol_entity_preview_is_read_only_and_full_export_is_explicit(self) -> None:
        artifacts = build_artifacts(str(self.root), output_dir=".simplicio")
        bundle = build_visualization_bundle(str(self.root), artifacts, generated_at="1970-01-01T00:00:00.000Z")
        symbol = next(node for node in bundle["nodes"] if node["kind"] == "symbol" and node["name"] == "greet")
        payload = preview_source(str(self.root), entity_id=symbol["id"], allow_full_content=True)
        self.assertEqual(payload["path"], "src/app.py")
        self.assertEqual(payload["sensitivity_warning"], "full-content export was explicitly requested")
        self.assertTrue(payload["read_only"])


if __name__ == "__main__":
    unittest.main()
