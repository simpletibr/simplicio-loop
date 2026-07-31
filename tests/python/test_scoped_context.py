import concurrent.futures
import contextlib
import hashlib
import io
import json
import os
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
    _generation_digest,
    _run_background_worker,
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

    def _artifacts(self):
        artifact_dir = self.root / ".simplicio"
        artifact_dir.mkdir(exist_ok=True)
        files = [
            {"path": "src/target.py"},
            {"path": "src/helper.py"},
            {"path": "src/caller.py"},
            {"path": "tests/test_target.py"},
            {"path": "pyproject.toml"},
        ]
        (artifact_dir / "project-map.json").write_text(json.dumps({"product": {"name": "fixture"}, "files": files}), encoding="utf-8")
        (artifact_dir / "symbol-index.json").write_text(json.dumps({"symbols": [{"name": "run", "defined_in": "src/target.py"}]}), encoding="utf-8")
        (artifact_dir / "call-graph.json").write_text(json.dumps({"edges": [
            {"source_file": "src/target.py", "target_file": "src/helper.py"},
            {"source_file": "src/caller.py", "target_file": "src/target.py"},
        ]}), encoding="utf-8")
        (artifact_dir / "architecture-inventory.json").write_text(json.dumps({"schema": "fixture"}), encoding="utf-8")

    def test_foreground_handoff_is_ready_with_hash_and_started_boundary(self):
        payload = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="task", attempt_id="attempt-1", cache_root=str(self.cache), start_background=False)
        self.assertTrue(payload["ready"])
        self.assertEqual("BACKGROUND_PENDING", payload["reason_code"])
        self.assertTrue(payload["attempt"]["pinned"])
        self.assertEqual("queued", payload["background"]["state"])
        span = payload["spans"][0]
        self.assertEqual(hashlib.sha256((self.root / "src/target.py").read_bytes()).hexdigest(), span["source_sha256"])
        self.assertIn("source_sha256", payload["selected_paths"][0])

    def test_non_root_scope_accepts_scope_relative_and_repo_relative_target(self):
        scoped = ScopedRequest.normalize(str(self.root), scope_root=str(self.root / "src"), target_hints=["target.py", "src/target.py"])
        self.assertEqual(("src/target.py",), scoped.target_hints)
        payload = build_scoped_context(str(self.root), scope_root=str(self.root / "src"), target_hints=["target.py"], cache_root=str(self.cache), start_background=False)
        self.assertEqual(["src/target.py"], [row["path"] for row in payload["selected_paths"]])

    def test_budget_is_visible_and_deterministic(self):
        self._artifacts()
        first = build_scoped_context(str(self.root), target_hints=["run"], context_budget=1, cache_root=str(self.cache), start_background=False)
        second = build_scoped_context(str(self.root), target_hints=["run"], context_budget=1, cache_root=str(self.cache), start_background=False)
        self.assertTrue(first["budget"]["expanded"])
        self.assertGreaterEqual(first["budget"]["effective_bytes"], first["budget"]["requested_bytes"])
        self.assertEqual([row["path"] for row in first["selected_paths"]], [row["path"] for row in second["selected_paths"]])

    def test_budget_preserves_multiple_explicit_symbol_and_corridor_targets(self):
        self._artifacts()
        payload = build_scoped_context(
            str(self.root),
            target_hints=["src/target.py", "run"],
            context_budget=1,
            cache_root=str(self.cache),
            start_background=False,
        )
        paths = {row["path"] for row in payload["selected_paths"]}
        self.assertTrue({"src/target.py", "src/helper.py", "src/caller.py", "tests/test_target.py"} <= paths)
        self.assertTrue(payload["budget"]["expanded"])
        self.assertEqual(paths, set(payload["budget"]["required_paths"]))

    def test_warm_reuses_source_rows_and_mutation_invalidates_dependency_closure(self):
        self._artifacts()
        first = build_scoped_context(str(self.root), target_hints=["run"], task_fingerprint="task", cache_root=str(self.cache), start_background=False)
        warm = build_scoped_context(str(self.root), target_hints=["run"], task_fingerprint="task", cache_root=str(self.cache), start_background=False)
        self.assertEqual(first["generation"]["id"], warm["generation"]["id"])
        self.assertEqual("hit", warm["metrics"]["cache"])
        self.assertEqual(0, warm["metrics"]["source_files_parsed"])
        (self.root / "src/helper.py").write_text("def help_run():\n    return 2\n", encoding="utf-8")
        incremental = build_scoped_context(str(self.root), target_hints=["run"], task_fingerprint="task", changed_paths=["src/helper.py"], cache_root=str(self.cache), start_background=False)
        self.assertNotEqual(first["generation"]["id"], incremental["generation"]["id"])
        self.assertEqual(["src/helper.py"], incremental["metrics"]["actual_changed_paths"])
        self.assertIn("src/target.py", incremental["metrics"]["dependency_invalidations"])
        self.assertGreater(incremental["metrics"]["source_files_reused"], 0)

    def test_same_size_mutation_with_restored_mtime_invalidates(self):
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="mtime", cache_root=str(self.cache), start_background=False)
        path = self.root / "src/target.py"
        before = path.stat()
        path.write_text("def run():\n    return 2\n", encoding="utf-8")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        second = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="mtime", cache_root=str(self.cache), start_background=False)
        self.assertNotEqual(first["generation"]["id"], second["generation"]["id"])
        self.assertEqual(["src/target.py"], second["metrics"]["actual_changed_paths"])
        self.assertEqual(["src/target.py"], second["metrics"]["parsed_paths"])

    def test_same_size_artifact_mutation_invalidates_artifact_cache(self):
        self._artifacts()
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="artifact", cache_root=str(self.cache), start_background=False)
        project_map = self.root / ".simplicio/project-map.json"
        before = project_map.stat()
        project_map.write_text(project_map.read_text(encoding="utf-8").replace("fixture", "otherxx"), encoding="utf-8")
        os.utime(project_map, ns=(before.st_atime_ns, before.st_mtime_ns))
        second = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="artifact", cache_root=str(self.cache), start_background=False)
        self.assertNotEqual(first["generation"]["id"], second["generation"]["id"])
        self.assertEqual(4, second["metrics"]["artifact_files_parsed"])

    def test_metrics_do_not_count_changed_paths_outside_selection(self):
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="metrics", cache_root=str(self.cache), start_background=False)
        second = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="metrics", changed_paths=["unrelated.py"], cache_root=str(self.cache), start_background=False)
        self.assertEqual(["unrelated.py"], second["metrics"]["actual_changed_paths"])
        self.assertEqual([], second["metrics"]["parsed_paths"])
        self.assertEqual(["src/target.py"], second["metrics"]["reused_paths"])
        self.assertEqual([], second["metrics"]["dependency_invalidations"])
        self.assertEqual(first["generation"]["id"], second["generation"]["id"])

    def test_pinned_attempt_survives_promotion(self):
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"], attempt_id="attempt", cache_root=str(self.cache), start_background=False)
        old_hash = first["spans"][0]["source_sha256"]
        (self.root / "src/target.py").write_text("def run():\n    return 2\n", encoding="utf-8")
        newer = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="new", cache_root=str(self.cache), start_background=False)
        pinned = build_scoped_context(str(self.root), target_hints=["src/target.py"], attempt_id="attempt", cache_root=str(self.cache), start_background=False)
        self.assertNotEqual(first["generation"]["id"], newer["generation"]["id"])
        self.assertEqual(old_hash, pinned["spans"][0]["source_sha256"])
        self.assertEqual("pinned", pinned["metrics"]["cache"])

    def test_tampered_generation_is_rejected_by_content_digest(self):
        build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="tamper", cache_root=str(self.cache), start_background=False)
        generation_path = next(self.cache.rglob("generations/*.json"))
        value = json.loads(generation_path.read_text(encoding="utf-8"))
        value["spans"][0]["source_sha256"] = "0" * 64
        generation_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ScopedContextError) as error:
            build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="tamper", cache_root=str(self.cache), start_background=False)
        self.assertEqual(REASON_CACHE_INCOMPATIBLE, error.exception.reason_code)

    def test_tampered_selected_span_stat_is_rejected(self):
        build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="stat-tamper", cache_root=str(self.cache), start_background=False)
        generation_path = next(self.cache.rglob("generations/*.json"))
        value = json.loads(generation_path.read_text(encoding="utf-8"))
        value["selected_paths"][0]["source_stat"] = {"size": 0, "mtime_ns": 0}
        value["content_digest"] = _generation_digest(value)
        generation_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ScopedContextError) as error:
            build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="stat-tamper", cache_root=str(self.cache), start_background=False)
        self.assertEqual(REASON_CACHE_INCOMPATIBLE, error.exception.reason_code)

    def test_concurrent_readers_publish_valid_same_generation(self):
        def read_once(_):
            return build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="same", cache_root=str(self.cache), start_background=False)

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(read_once, range(10)))
        self.assertEqual({result["generation"]["id"] for result in results}, {results[0]["generation"]["id"]})
        self.assertTrue(all(result["ready"] for result in results))
        for path in self.cache.rglob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))

    def test_traversal_symlink_stale_and_root_safety(self):
        with self.assertRaises(ScopedContextError) as traversal:
            ScopedRequest.normalize(str(self.root), target_hints=["../outside.py"])
        self.assertEqual(REASON_TARGET_OUTSIDE_SCOPE, traversal.exception.reason_code)
        with self.assertRaises(ScopedContextError) as mismatch:
            ScopedRequest.normalize(str(self.root), scope_root=str(self.root.parent))
        self.assertEqual(REASON_ROOT_MISMATCH, mismatch.exception.reason_code)
        outside = Path(tempfile.mkdtemp()) / "outside.py"
        outside.write_text("x=1\n", encoding="utf-8")
        link = self.root / "src/link.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(ScopedContextError) as symlink:
            ScopedRequest.normalize(str(self.root), scope_root=str(self.root / "src"), target_hints=["link.py"])
        self.assertEqual(REASON_TARGET_OUTSIDE_SCOPE, symlink.exception.reason_code)

    def test_corrupt_cache_fails_closed(self):
        first = build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="corrupt", cache_root=str(self.cache), start_background=False)
        self.assertTrue(first["ready"])
        promotion = next(self.cache.rglob("promotions/*.json"))
        promotion.write_text("{bad-cache", encoding="utf-8")
        with self.assertRaises(ScopedContextError) as error:
            build_scoped_context(str(self.root), target_hints=["src/target.py"], task_fingerprint="corrupt", cache_root=str(self.cache), start_background=False)
        self.assertEqual(REASON_CACHE_INCOMPATIBLE, error.exception.reason_code)

    def test_stale_artifact_fails_closed(self):
        artifact_dir = self.root / ".simplicio"
        artifact_dir.mkdir()
        (artifact_dir / "project-map.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaises(ScopedContextError) as error:
            build_scoped_context(str(self.root), target_hints=["src/target.py"], cache_root=str(self.cache), start_background=False)
        self.assertEqual(REASON_SCOPED_ARTIFACT_STALE, error.exception.reason_code)

    def test_background_worker_is_queued_without_fake_completion(self):
        payload = build_scoped_context(str(self.root), target_hints=["src/target.py"], cache_root=str(self.cache), start_background=True)
        self.assertEqual(3, _run_background_worker(payload["background"]["work_id"], self.cache))
        state_path = next(self.cache.rglob(f"{payload['background']['work_id']}.json"))
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual("queued", state["state"])
        with self.assertRaises(ScopedContextError):
            _run_background_worker("*", self.cache)

    def test_missing_root_and_unknown_symbol_fail_closed(self):
        with self.assertRaises(ScopedContextError) as missing:
            ScopedRequest.normalize(str(self.root / "missing"))
        self.assertEqual(REASON_ROOT_MISMATCH, missing.exception.reason_code)
        self._artifacts()
        with self.assertRaises(ScopedContextError) as unknown:
            build_scoped_context(str(self.root), target_hints=["unknown"], cache_root=str(self.cache), start_background=False)
        self.assertEqual(REASON_CORRIDOR_INCOMPLETE, unknown.exception.reason_code)

    def test_cli_json_flag_and_rejected_target(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = run_scoped_context_cli([str(self.root), "--target", "src/target.py", "--no-background", "--json", "--cache-root", str(self.cache)])
        self.assertEqual(0, status)
        self.assertTrue(json.loads(output.getvalue())["ready"])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = run_scoped_context_cli([str(self.root), "--target", "../outside.py", "--no-background", "--json", "--cache-root", str(self.cache)])
        self.assertEqual(1, status)
        self.assertIn(REASON_TARGET_OUTSIDE_SCOPE, output.getvalue())


if __name__ == "__main__":
    unittest.main()
