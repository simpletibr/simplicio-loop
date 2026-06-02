"""Tests for the simplicio.mechanical-edit/v1 helpers (issue #110).

Covers:

- stable range hashing across repeated runs;
- snapshot hash changes when the file content changes;
- anchor drift detection (re-hashing a stale range produces a different
  hash than the captured `before_hash`);
- missing file raises `FileNotFoundError`;
- binary file refusal raises `ValueError`;
- large-file compact mode (no `must_contain` snippets above the threshold);
- multi-language fixtures (TypeScript, Python, JSON, Markdown).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "mech-edit-host"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mechanical_edit import (  # noqa: E402
    COMPACT_LINE_THRESHOLD,
    MECHANICAL_EDIT_SCHEMA,
    build_context,
    extract_file_entry,
    is_binary,
    range_hash,
    snapshot_hash,
)


class StableRangeHashingTest(unittest.TestCase):
    def test_same_text_same_range_yields_same_hash(self) -> None:
        text = "alpha\nbeta\ngamma\ndelta\n"
        a = range_hash(text, 2, 3)
        b = range_hash(text, 2, 3)
        self.assertEqual(a, b)

    def test_different_ranges_yield_different_hashes(self) -> None:
        text = "alpha\nbeta\ngamma\ndelta\n"
        self.assertNotEqual(range_hash(text, 1, 2), range_hash(text, 3, 4))

    def test_range_out_of_bounds_raises(self) -> None:
        text = "one\ntwo\n"
        with self.assertRaises(ValueError):
            range_hash(text, 1, 5)
        with self.assertRaises(ValueError):
            range_hash(text, 0, 1)
        with self.assertRaises(ValueError):
            range_hash(text, 2, 1)


class SnapshotHashTest(unittest.TestCase):
    def test_snapshot_hash_changes_when_content_changes(self) -> None:
        before = snapshot_hash("alpha\nbeta\n")
        after = snapshot_hash("alpha\nbeta CHANGED\n")
        self.assertNotEqual(before, after)


class AnchorDriftDetectionTest(unittest.TestCase):
    def test_drift_changes_before_hash(self) -> None:
        original = "line a\nline b\nline c\n"
        captured = range_hash(original, 2, 2)
        mutated = "line a\nline B different\nline c\n"
        re_hashed = range_hash(mutated, 2, 2)
        self.assertNotEqual(captured, re_hashed)


class MissingFileAndBinaryRefusalTest(unittest.TestCase):
    def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                extract_file_entry(tmp, "does-not-exist.py", [(1, 1)])

    def test_binary_file_refused(self) -> None:
        self.assertTrue(is_binary(str(FIXTURE / "binary.bin")))
        with self.assertRaises(ValueError):
            extract_file_entry(str(FIXTURE), "binary.bin", [(1, 1)])


class LargeFileCompactModeTest(unittest.TestCase):
    def test_must_contain_omitted_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            big = root / "huge.py"
            big.write_text("\n".join(f"line_{i}" for i in range(COMPACT_LINE_THRESHOLD + 50)))
            entry = extract_file_entry(str(root), "huge.py", [(10, 12)])
            self.assertEqual(entry["selected_ranges"][0]["must_contain"], [])

    def test_must_contain_emitted_below_threshold(self) -> None:
        entry = extract_file_entry(str(FIXTURE), "sample.py", [(4, 5)])
        self.assertTrue(entry["selected_ranges"][0]["must_contain"])


class MultiLanguageFixtureTest(unittest.TestCase):
    def test_typescript_python_json_markdown_languages(self) -> None:
        context = build_context(
            str(FIXTURE),
            [
                ("sample.ts", 1, 4),
                ("sample.py", 4, 5),
                ("sample.json", 1, 9),
                ("sample.md", 1, 1),
            ],
        )
        self.assertEqual(context["schema"], MECHANICAL_EDIT_SCHEMA)
        by_path = {f["path"]: f for f in context["context"]["files"]}
        self.assertEqual(by_path["sample.ts"]["language"], "typescript")
        self.assertEqual(by_path["sample.py"]["language"], "python")
        self.assertEqual(by_path["sample.json"]["language"], "json")
        self.assertEqual(by_path["sample.md"]["language"], "markdown")
        for entry in by_path.values():
            self.assertEqual(len(entry["snapshot_hash"]), 64)
            self.assertEqual(len(entry["selected_ranges"][0]["before_hash"]), 64)


class DeterministicContextHashTest(unittest.TestCase):
    def test_same_selections_yield_same_context_hash(self) -> None:
        first = build_context(str(FIXTURE), [("sample.py", 4, 5), ("sample.ts", 1, 4)])
        second = build_context(str(FIXTURE), [("sample.ts", 1, 4), ("sample.py", 4, 5)])
        self.assertEqual(
            first["context"]["context_hash"],
            second["context"]["context_hash"],
        )
        self.assertEqual(first, second)

    def test_changed_selection_changes_context_hash(self) -> None:
        base = build_context(str(FIXTURE), [("sample.py", 4, 5)])
        wider = build_context(str(FIXTURE), [("sample.py", 4, 7)])
        self.assertNotEqual(
            base["context"]["context_hash"],
            wider["context"]["context_hash"],
        )


if __name__ == "__main__":
    unittest.main()
