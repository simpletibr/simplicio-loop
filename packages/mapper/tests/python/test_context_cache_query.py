from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT))

from simplicio_mapper.context_cache import (  # noqa: E402
    LAYER_CONTEXT_SUMMARY,
    LAYER_RUNTIME_PROVIDER,
    ContextCache,
    ContextCacheKey,
)


def _write(base: Path, rel: str, content: str) -> None:
    target = base / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class ContextCacheQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cache_path = self.root / ".simplicio-loop" / "context-cache.json"
        _write(self.root, "src/app.py", "print('v1')\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_content_address_changes_when_file_changes(self) -> None:
        first = ContextCacheKey.for_files(
            str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q"
        )
        _write(self.root, "src/app.py", "print('v2')\n")
        second = ContextCacheKey.for_files(
            str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q"
        )
        self.assertNotEqual(first.content_hash(), second.content_hash())

    def test_corrupt_entry_is_quarantined_on_reload(self) -> None:
        cache = ContextCache(self.cache_path)
        key = ContextCacheKey.for_files(
            str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q"
        )
        key_hash = cache.put(LAYER_CONTEXT_SUMMARY, key, {"results": ["ok"], "total": 1})
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        payload["structured"]["entries"][key_hash]["checksum"] = "bad"
        self.cache_path.write_text(json.dumps(payload), encoding="utf-8")

        reloaded = ContextCache(self.cache_path)
        value, receipt = reloaded.get_entry(LAYER_CONTEXT_SUMMARY, key)
        self.assertIsNone(value)
        self.assertEqual(receipt.outcome, "corrupt")
        explain = reloaded.explain(key_hash)
        self.assertTrue(explain["quarantined"])
        self.assertEqual(explain["reason"], "checksum_mismatch")

    def test_concurrent_writers_merge_without_losing_entries(self) -> None:
        first_key = ContextCacheKey.for_files(
            str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q1"
        )
        second_key = ContextCacheKey.for_files(
            str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q2"
        )
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def writer(key: ContextCacheKey, payload: dict) -> None:
            try:
                barrier.wait(timeout=2)
                ContextCache(self.cache_path).put(LAYER_CONTEXT_SUMMARY, key, payload)
            except Exception as exc:  # pragma: no cover - surfaced below
                errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(first_key, {"value": 1})),
            threading.Thread(target=writer, args=(second_key, {"value": 2})),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

        persisted = ContextCache(self.cache_path)
        self.assertTrue(persisted.has(LAYER_CONTEXT_SUMMARY, first_key))
        self.assertTrue(persisted.has(LAYER_CONTEXT_SUMMARY, second_key))

    def test_bypass_receipt_keeps_baseline_and_method(self) -> None:
        cache = ContextCache(self.cache_path)
        receipt = cache.record_bypass(
            LAYER_RUNTIME_PROVIDER,
            "key",
            reason="native-first-satisfied",
            baseline="local fallback",
            method="runtime-native",
        )
        payload = receipt.to_dict()
        self.assertEqual(payload["baseline"], "local fallback")
        self.assertEqual(payload["method"], "runtime-native")

    def test_generation_mismatch_is_not_served_and_local_boundary_is_explicit(self) -> None:
        cache = ContextCache(self.cache_path)
        key = ContextCacheKey.for_files(str(self.root), ["src/app.py"], repo_identity="repo", query_task_hash="q")
        cache.put(LAYER_CONTEXT_SUMMARY, key, {"selected": ["src/app.py"]}, generation="gen-1")
        value, receipt = cache.get_entry(LAYER_CONTEXT_SUMMARY, key, expected_generation="gen-2")
        self.assertIsNone(value)
        self.assertEqual(receipt.outcome, "corrupt")
        self.assertEqual(receipt.reason, "generation_or_digest_mismatch")
        self.assertEqual(receipt.cache_scope, "local_mapper")
        self.assertEqual(receipt.provider_cache, "unclaimed")


if __name__ == "__main__":
    unittest.main()
