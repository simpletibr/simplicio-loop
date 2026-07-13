"""Tests for the simplicio.context-pack/v1 builder and the hash-keyed cache (#115).

Covers:

- the basic envelope (schema, repo metadata, pack_hash, files);
- selected-range extraction with per-range hashes;
- dependency/caller inclusion from a provided `call_graph`;
- `needs_broader_context` when the target file is missing or a range is
  unstable, and when upstream mapper artifacts are absent;
- determinism across repeated runs on the same tree;
- large-file compact mode (snippets omitted, snapshot_hash stable);
- the cache: hit, miss, invalidation by changing the key, and JSON-backed
  persistence between instances.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "ctx-pack-host"
sys.path.insert(0, str(ROOT))

from simplicio_mapper.context_cache import (  # noqa: E402
    CONTEXT_CACHE_SCHEMA,
    ContextCache,
)
from simplicio_mapper.context_pack import (  # noqa: E402
    COMPACT_LINE_THRESHOLD,
    CONTEXT_PACK_SCHEMA,
    build_context_pack,
)


def _pack(root, targets, **kwargs):
    defaults = {"project_map": {}, "symbol_index": {}, "call_graph": {}}
    defaults.update(kwargs)
    return build_context_pack(root, targets, **defaults)


class ContextPackBasicTest(unittest.TestCase):
    def test_envelope_shape_and_pack_hash(self) -> None:
        pack = _pack(str(FIXTURE), [{"path": "sample.py"}])
        self.assertEqual(pack["schema"], CONTEXT_PACK_SCHEMA)
        self.assertEqual(pack["repo"]["mapper_schema"], "simplicio.mapper-index/v1")
        self.assertEqual(len(pack["pack_hash"]), 64)
        self.assertEqual(len(pack["files"]), 1)
        self.assertEqual(pack["files"][0]["language"], "python")
        self.assertIn("freshness", pack)
        self.assertIn("fidelity", pack)
        self.assertIn("scales", pack)

    def test_multi_language_fixtures(self) -> None:
        pack = _pack(str(FIXTURE), [
            {"path": "sample.ts"},
            {"path": "sample.py"},
            {"path": "sample.json"},
            {"path": "sample.md"},
        ])
        by_path = {entry["path"]: entry for entry in pack["files"]}
        self.assertEqual(by_path["sample.ts"]["language"], "typescript")
        self.assertEqual(by_path["sample.py"]["language"], "python")
        self.assertEqual(by_path["sample.json"]["language"], "json")
        self.assertEqual(by_path["sample.md"]["language"], "markdown")
        for entry in by_path.values():
            self.assertEqual(len(entry["snapshot_hash"]), 64)


class RangeExtractionTest(unittest.TestCase):
    def test_range_hash_emitted_with_snippet(self) -> None:
        pack = _pack(str(FIXTURE), [{"path": "sample.py", "ranges": [(3, 4)]}])
        ranges = pack["files"][0]["ranges"]
        self.assertEqual(len(ranges), 1)
        self.assertEqual(len(ranges[0]["range_hash"]), 64)
        self.assertTrue(ranges[0]["snippet"])
        self.assertTrue(pack["files"][0]["drilldown"]["reversible"])

    def test_unstable_range_marks_needs_broader_context(self) -> None:
        pack = _pack(str(FIXTURE), [{"path": "sample.py", "ranges": [(1, 9999)]}])
        self.assertTrue(pack["needs_broader_context"])
        self.assertIn("unstable range", pack["needs_broader_context_reason"])


class CallGraphAndDependencyTest(unittest.TestCase):
    def test_callers_and_imports_resolved(self) -> None:
        call_graph = {"edges": [
            {"from": "sample.py", "to": "shared/util.py"},
            {"from": "caller.py", "to": "sample.py"},
        ]}
        pack = _pack(
            str(FIXTURE),
            [{"path": "sample.py"}],
            call_graph=call_graph,
        )
        entry = pack["files"][0]
        self.assertEqual(entry["imports"], ["shared/util.py"])
        self.assertEqual(entry["callers"], ["caller.py"])
        self.assertIn("micro", entry["scale_context"])
        self.assertIn("macro", entry["scale_context"])

    def test_tests_resolved_from_project_map(self) -> None:
        project_map = {"files": [
            {"path": "sample.py", "roles": ["domain"]},
            {"path": "tests/test_sample.py", "roles": ["test"]},
        ]}
        pack = _pack(
            str(FIXTURE),
            [{"path": "sample.py"}],
            project_map=project_map,
        )
        self.assertIn("tests/test_sample.py", pack["files"][0]["tests"])


class NeedsBroaderContextTest(unittest.TestCase):
    def test_missing_target_marked(self) -> None:
        pack = _pack(str(FIXTURE), [{"path": "does-not-exist.py"}])
        self.assertTrue(pack["needs_broader_context"])
        self.assertIn("target missing", pack["needs_broader_context_reason"])

    def test_missing_upstream_artifacts_loaded_implicitly(self) -> None:
        # No `.simplicio/` under the fixture dir, so build_context_pack
        # falls into "absent" branches when no overrides are passed.
        pack = build_context_pack(str(FIXTURE), [{"path": "sample.py"}])
        self.assertTrue(pack["needs_broader_context"])
        self.assertIn("project-map.json absent", pack["needs_broader_context_reason"])


class DeterminismTest(unittest.TestCase):
    def test_same_inputs_same_pack(self) -> None:
        targets = [
            {"path": "sample.py", "ranges": [(3, 4)]},
            {"path": "sample.ts", "ranges": [(1, 4)]},
        ]
        first = _pack(str(FIXTURE), targets)
        second = _pack(str(FIXTURE), targets)
        self.assertEqual(first["pack_hash"], second["pack_hash"])
        self.assertEqual(first, second)

    def test_fidelity_marks_partial_when_broader_context_needed(self) -> None:
        pack = _pack(str(FIXTURE), [{"path": "does-not-exist.py"}])
        self.assertEqual(pack["fidelity"]["status"], "partial")
        self.assertTrue(pack["fidelity"]["reasons"])


class LargeFileCompactModeTest(unittest.TestCase):
    def test_compact_mode_omits_snippets_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "huge.py"
            big.write_text("\n".join(f"line_{i}" for i in range(COMPACT_LINE_THRESHOLD + 100)))
            pack = _pack(str(tmp), [{"path": "huge.py", "ranges": [(5, 10)]}])
            entry = pack["files"][0]
            self.assertTrue(entry["compact"])
            self.assertEqual(entry["ranges"][0]["snippet"], [])


class ContextCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self._tmp.name) / "ctx-cache.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_hit_returns_stored_summary(self) -> None:
        cache = ContextCache(self.cache_path)
        cache.set("abc123", {"summary": "small file"})
        self.assertEqual(cache.get("abc123"), {"summary": "small file"})
        self.assertIn("abc123", cache)
        self.assertEqual(len(cache), 1)

    def test_miss_returns_none(self) -> None:
        cache = ContextCache(self.cache_path)
        self.assertIsNone(cache.get("never-stored"))

    def test_invalidation_when_key_changes(self) -> None:
        cache = ContextCache(self.cache_path)
        cache.set("hash-v1", {"summary": "old"})
        self.assertIsNone(cache.get("hash-v2"))

    def test_persistence_across_instances(self) -> None:
        first = ContextCache(self.cache_path)
        first.set("abc", {"summary": "persisted"})
        second = ContextCache(self.cache_path)
        self.assertEqual(second.get("abc"), {"summary": "persisted"})

    def test_clear_empties_cache(self) -> None:
        cache = ContextCache(self.cache_path)
        cache.set("abc", {"summary": "x"})
        cache.clear()
        self.assertIsNone(cache.get("abc"))
        # And the new instance also sees the cleared state.
        self.assertEqual(len(ContextCache(self.cache_path)), 0)

    def test_persisted_payload_uses_schema(self) -> None:
        cache = ContextCache(self.cache_path)
        cache.set("abc", {"summary": "x"})
        import json as _json
        on_disk = _json.loads(self.cache_path.read_text())
        self.assertEqual(on_disk["schema"], CONTEXT_CACHE_SCHEMA)
        self.assertEqual(on_disk["entries"], {"abc": {"summary": "x"}})

    def test_keys_returns_sorted_sample(self) -> None:
        cache = ContextCache(self.cache_path)
        cache.set("def", {"summary": "2"})
        cache.set("abc", {"summary": "1"})
        self.assertEqual(cache.keys(limit=1), ["abc"])
        self.assertEqual(cache.keys(), ["abc", "def"])


if __name__ == "__main__":
    unittest.main()
