import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from simplicio_mapper.scoped_context import (
    REASON_CACHE_INCOMPATIBLE,
    REASON_CORRIDOR_INCOMPLETE,
    REASON_ROOT_MISMATCH,
    REASON_SCOPED_ARTIFACT_STALE,
    REASON_TARGET_OUTSIDE_SCOPE,
    ScopedContextError,
    ScopedRequest,
    build_scoped_context,
    run_scoped_context_cli,
)


class ScopedContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src/target.py").write_text("def run():\n    return 1\n", encoding="utf-8")
        (self.root / "src/helper.py").write_text("def help_run():\n    return 1\n", encoding="utf-8")
        (self.root / "src/caller.py").write_text("from src.target import run\n", encoding="utf-8")
        (self.root / "tests/test_target.py").write_text("from src.target import run\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
        self.cache = self.root / "cache"

    def tearDown(self):
        self.tmp.cleanup()

    def test_foreground_handoff_is_ready_and_pinned(self):
        payload = build_scoped_context(str(self.root), target_hints=["src/target.py"],
                                      task_fingerprint="task", attempt_id="attempt-1",
                                      cache_root=str(self.cache))
        self.assertTrue(payload["ready"])
        self.assertEqual("BACKGROUND_PENDING", payload["reason_code"])
        self.assertEqual("attempt-1", payload["attempt"]["id"])
        self.assertTrue(payload["attempt"]["pinned"])
        self.assertEqual("pending", payload["background"]["state"])
        selected = {row["path"] for row in payload["selected_paths"]}
        self.assertEqual({"src/target.py"}, selected)
        span = payload["spans"][0]
        self.assertEqual(hashlib.sha256((self.root / "src/target.py").read_bytes()).hexdigest(),
                         span["source_sha256"])

    def test_warm_cache_and_incremental_receipts(self):
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"],
                                     task_fingerprint="task", cache_root=str(self.cache))
        warm = build_scoped_context(str(self.root), target_hints=["src/target.py"],
                                    task_fingerprint="task", cache_root=str(self.cache))
        self.assertEqual(first["generation"]["id"], warm["generation"]["id"])
        self.assertEqual("hit", warm["metrics"]["cache"])
        self.assertGreaterEqual(warm["metrics"]["files_reused"], 0)
        incremental = build_scoped_context(
            str(self.root), target_hints=["src/target.py"], task_fingerprint="task",
            changed_paths=["src/target.py"], cache_root=str(self.cache))
        self.assertNotEqual(first["generation"]["id"], incremental["generation"]["id"])
        self.assertEqual(["src/target.py"], incremental["metrics"]["changed_paths"])

    def test_normalization_rejects_traversal_and_root_mismatch(self):
        with self.assertRaises(ScopedContextError) as target_error:
            ScopedRequest.normalize(str(self.root), target_hints=["../outside.py"])
        self.assertEqual(REASON_TARGET_OUTSIDE_SCOPE, target_error.exception.reason_code)
        with self.assertRaises(ScopedContextError) as root_error:
            ScopedRequest.normalize(str(self.root), scope_root=str(self.root.parent))
        self.assertEqual(REASON_ROOT_MISMATCH, root_error.exception.reason_code)

    def test_invalid_canonical_artifact_fails_closed(self):
        artifact_dir = self.root / ".simplicio"
        artifact_dir.mkdir()
        (artifact_dir / "project-map.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaises(ScopedContextError) as error:
            build_scoped_context(str(self.root), target_hints=["src/target.py"],
                                 cache_root=str(self.cache))
        self.assertEqual(REASON_SCOPED_ARTIFACT_STALE, error.exception.reason_code)

    def test_artifacts_expand_corridor_and_report_reuse(self):
        artifact_dir = self.root / ".simplicio"
        artifact_dir.mkdir()
        files = [
            {"path": "src/target.py"},
            {"path": "src/helper.py"},
            {"path": "src/caller.py"},
            {"path": "tests/test_target.py"},
            {"path": "pyproject.toml"},
        ]
        (artifact_dir / "project-map.json").write_text(
            json.dumps({"product": {"name": "fixture"}, "files": files}), encoding="utf-8")
        (artifact_dir / "symbol-index.json").write_text(
            json.dumps({"symbols": [{"name": "run", "defined_in": "src/target.py"}]}),
            encoding="utf-8")
        (artifact_dir / "call-graph.json").write_text(
            json.dumps({"edges": [
                {"source_file": "src/target.py", "target_file": "src/helper.py"},
                {"source_file": "src/caller.py", "target_file": "src/target.py"},
            ]}), encoding="utf-8")
        (artifact_dir / "architecture-inventory.json").write_text(
            json.dumps({"schema": "fixture"}), encoding="utf-8")
        payload = build_scoped_context(
            str(self.root), target_hints=["run"], cache_root=str(self.cache))
        selected = {row["path"] for row in payload["selected_paths"]}
        self.assertTrue(payload["ready"])
        self.assertTrue({"src/target.py", "src/helper.py", "src/caller.py"} <= selected)
        self.assertIn("tests/test_target.py", selected)
        self.assertIn("pyproject.toml", selected)
        self.assertEqual(4, payload["metrics"]["files_parsed"])

    def test_corrupt_cache_and_invalid_budget_fail_closed(self):
        first = build_scoped_context(
            str(self.root), target_hints=["src/target.py"], cache_root=str(self.cache))
        next(self.cache.glob("*.json")).write_text("{bad-cache", encoding="utf-8")
        corrupt = build_scoped_context(
            str(self.root), target_hints=["src/target.py"], cache_root=str(self.cache))
        self.assertFalse(corrupt["ready"])
        self.assertEqual(REASON_CACHE_INCOMPATIBLE, corrupt["reason_code"])
        with self.assertRaises(ScopedContextError) as budget_error:
            ScopedRequest.normalize(str(self.root), context_budget=0)
        self.assertEqual(REASON_CORRIDOR_INCOMPLETE, budget_error.exception.reason_code)
        self.assertTrue(first["generation"]["id"])

    def test_cli_emits_machine_reason_for_rejected_target(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = run_scoped_context_cli(
                [str(self.root), "--target", "../outside.py"])
        self.assertEqual(1, status)
        self.assertIn(REASON_TARGET_OUTSIDE_SCOPE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
