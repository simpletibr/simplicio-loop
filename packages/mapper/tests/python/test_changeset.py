"""Tests for changeset validation, byte-exact newline normalization, and CLI (Issue #655).

Covers:
- Changeset validation (schema simplicio.fast.changeset/v2):
  - success on valid substitution
  - fail-closed rejection when expected_sha256 differs from disk (stale source hash)
  - rejection of overlapping substitutions or out-of-file-bounds lines
  - rejection of paths escaping repository root
- Byte-exact normalization of newlines (\n and \r\n)
- CLI: simplicio-mapper changeset validate <file> and changeset prepare
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from simplicio_mapper.changeset import (
    apply_changeset,
    prepare_changes,
    validate_changeset,
)
from simplicio_mapper.cli import main


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ChangesetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name).resolve()

        # Create a file with LF newlines
        self.lf_file = self.root / "module_lf.py"
        self.lf_content = "def add(a, b):\n    # compute sum\n    return a + b\n"
        self.lf_file.write_bytes(self.lf_content.encode("utf-8"))

        # Create a file with CRLF newlines
        self.crlf_file = self.root / "module_crlf.py"
        self.crlf_content = b"def subtract(a, b):\r\n    # compute diff\r\n    return a - b\r\n"
        self.crlf_file.write_bytes(self.crlf_content)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_valid_changeset_substitution(self) -> None:
        expected = _sha256(self.lf_file.read_bytes())
        changeset = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [
                        {
                            "start_line": 2,
                            "end_line": 2,
                            "content": "    # sum computation updated",
                        }
                    ],
                }
            ],
        }

        # Validate
        res = validate_changeset(changeset, root=self.root)
        self.assertEqual("valid", res["status"])
        self.assertEqual(1, len(res["files"]))
        self.assertEqual("module_lf.py", res["files"][0]["path"])

        # Apply dry-run
        dry_run = apply_changeset(changeset, root=self.root, write=False)
        self.assertEqual("dry-run", dry_run["mode"])
        self.assertFalse(dry_run["applied"])
        self.assertEqual(self.lf_content, self.lf_file.read_text(encoding="utf-8"))

        # Apply write
        written = apply_changeset(changeset, root=self.root, write=True)
        self.assertEqual("write", written["mode"])
        self.assertTrue(written["applied"])
        updated_text = self.lf_file.read_text(encoding="utf-8")
        self.assertIn("# sum computation updated", updated_text)
        self.assertNotIn("# compute sum", updated_text)
        self.assertTrue(updated_text.startswith("def add(a, b):\n"))
        self.assertTrue(updated_text.endswith("    return a + b\n"))

    def test_stale_source_hash_rejection(self) -> None:
        # Provide mismatched expected_sha256
        bad_hash = "0" * 64
        changeset = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": bad_hash,
                    "replacements": [
                        {
                            "start_line": 1,
                            "end_line": 1,
                            "content": "# new header",
                        }
                    ],
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "stale source hash"):
            prepare_changes(changeset["changes"], root=self.root)

        with self.assertRaisesRegex(ValueError, "stale source hash"):
            apply_changeset(changeset, root=self.root, write=True)

    def test_out_of_bounds_lines_rejection(self) -> None:
        expected = _sha256(self.lf_file.read_bytes())

        # Line 0 (start_line < 1)
        cs_zero = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [{"start_line": 0, "end_line": 1, "content": "x"}],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "invalid line replacement"):
            prepare_changes(cs_zero["changes"], root=self.root)

        # end_line > total lines
        cs_beyond = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [{"start_line": 1, "end_line": 100, "content": "x"}],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "invalid line replacement"):
            prepare_changes(cs_beyond["changes"], root=self.root)

        # start_line > end_line
        cs_inverted = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [{"start_line": 3, "end_line": 2, "content": "x"}],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "invalid line replacement"):
            prepare_changes(cs_inverted["changes"], root=self.root)

    def test_overlapping_replacements_rejection(self) -> None:
        expected = _sha256(self.lf_file.read_bytes())
        # Overlapping ranges: 1..2 and 2..3
        changeset = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [
                        {"start_line": 1, "end_line": 2, "content": "# first"},
                        {"start_line": 2, "end_line": 3, "content": "# second"},
                    ],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "overlapping replacements"):
            prepare_changes(changeset["changes"], root=self.root)

    def test_path_escapes_root_rejection(self) -> None:
        changeset = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "../outside.py",
                    "expected_sha256": "0" * 64,
                    "replacements": [{"start_line": 1, "end_line": 1, "content": "x"}],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "change path escapes root"):
            prepare_changes(changeset["changes"], root=self.root)

    def test_newline_normalization_lf_and_crlf(self) -> None:
        # Case 1: LF file with replacement content having CRLF -> normalized to LF
        expected_lf = _sha256(self.lf_file.read_bytes())
        changeset_lf = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected_lf,
                    "replacements": [
                        {
                            "start_line": 2,
                            "end_line": 2,
                            "content": "    # replaced with CRLF input\r\n",
                        }
                    ],
                }
            ],
        }
        receipt_lf = apply_changeset(changeset_lf, root=self.root, write=True)
        raw_lf = self.lf_file.read_bytes()
        self.assertNotIn(b"\r\n", raw_lf)
        self.assertIn(b"\n", raw_lf)
        self.assertEqual("lf", receipt_lf["files"][0]["newline"])

        # Case 2: CRLF file with replacement content having LF -> normalized to CRLF
        expected_crlf = _sha256(self.crlf_file.read_bytes())
        changeset_crlf = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_crlf.py",
                    "expected_sha256": expected_crlf,
                    "replacements": [
                        {
                            "start_line": 2,
                            "end_line": 2,
                            "content": "    # replaced with LF input\n",
                        }
                    ],
                }
            ],
        }
        receipt_crlf = apply_changeset(changeset_crlf, root=self.root, write=True)
        raw_crlf = self.crlf_file.read_bytes()
        self.assertIn(b"\r\n", raw_crlf)
        # Verify no solitary LF
        self.assertEqual(len(raw_crlf.split(b"\r\n")), len(raw_crlf.split(b"\n")))
        self.assertEqual("crlf", receipt_crlf["files"][0]["newline"])

    def test_cli_changeset_validate(self) -> None:
        expected = _sha256(self.lf_file.read_bytes())
        changeset_data = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [
                        {"start_line": 1, "end_line": 1, "content": "# comment"}
                    ],
                }
            ],
        }
        cs_path = self.root / "changeset.json"
        cs_path.write_text(json.dumps(changeset_data), encoding="utf-8")

        # Run CLI validate on valid file
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["changeset", "validate", str(cs_path), "--root", str(self.root)])
        self.assertEqual(0, exit_code, stderr.getvalue())
        val_res = json.loads(stdout.getvalue())
        self.assertEqual("valid", val_res["status"])

        # Make file hash stale
        self.lf_file.write_text("modified content\n", encoding="utf-8")
        stdout_stale = StringIO()
        stderr_stale = StringIO()
        with redirect_stdout(stdout_stale), redirect_stderr(stderr_stale):
            exit_code_stale = main(["changeset", "validate", str(cs_path), "--root", str(self.root)])
        self.assertNotEqual(0, exit_code_stale)

    def test_cli_changeset_prepare(self) -> None:
        expected = _sha256(self.lf_file.read_bytes())
        changeset_data = {
            "schema": "simplicio.fast.changeset/v2",
            "changes": [
                {
                    "path": "module_lf.py",
                    "expected_sha256": expected,
                    "replacements": [
                        {"start_line": 1, "end_line": 1, "content": "# comment"}
                    ],
                }
            ],
        }
        input_json = self.root / "input.json"
        input_json.write_text(json.dumps(changeset_data), encoding="utf-8")
        output_binary = self.root / "output.sfc"

        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main([
                "changeset",
                "prepare",
                str(input_json),
                "--root",
                str(self.root),
                "--output",
                str(output_binary),
            ])
        self.assertEqual(0, exit_code, stderr.getvalue())
        prep_res = json.loads(stdout.getvalue())
        self.assertEqual("sealed", prep_res["status"])
        self.assertTrue(output_binary.is_file())


if __name__ == "__main__":
    unittest.main()
