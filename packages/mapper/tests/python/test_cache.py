"""Unit tests for simplicio_mapper.cache.FileProcessingCache.

Covers key derivation/fingerprinting, get/set round-trips, invalidation
when a file's size or mtime changes, expiry, clearing, and the context
manager protocol. See issue #220 (cache, invalidation and fingerprint
acceptance criteria).

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cache import FileProcessingCache  # noqa: E402


class MakeFileKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "cache"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_key_is_deterministic_for_identical_inputs(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            key_a = cache.make_file_key("src/app.py", 100, 123456789)
            key_b = cache.make_file_key("src/app.py", 100, 123456789)
            self.assertEqual(key_a, key_b)

    def test_key_changes_when_size_changes(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            key_a = cache.make_file_key("src/app.py", 100, 123456789)
            key_b = cache.make_file_key("src/app.py", 101, 123456789)
            self.assertNotEqual(key_a, key_b)

    def test_key_changes_when_mtime_changes(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            key_a = cache.make_file_key("src/app.py", 100, 123456789)
            key_b = cache.make_file_key("src/app.py", 100, 987654321)
            self.assertNotEqual(key_a, key_b)

    def test_key_changes_when_path_changes(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            key_a = cache.make_file_key("src/app.py", 100, 123456789)
            key_b = cache.make_file_key("src/other.py", 100, 123456789)
            self.assertNotEqual(key_a, key_b)

    def test_key_normalizes_windows_style_separators(self) -> None:
        # Path(...).as_posix() normalizes backslashes, so a Windows-style
        # relative path and its POSIX equivalent must fingerprint identically.
        with FileProcessingCache(self.cache_dir) as cache:
            key_a = cache.make_file_key("src\\pkg\\app.py", 100, 123456789)
            key_b = cache.make_file_key("src/pkg/app.py", 100, 123456789)
            self.assertEqual(key_a, key_b)

    def test_key_is_prefixed_and_hex(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            key = cache.make_file_key("a.py", 1, 1)
            self.assertTrue(key.startswith("file:"))
            digest = key.split(":", 1)[1]
            self.assertEqual(len(digest), 48)  # blake2b digest_size=24 -> 48 hex chars
            int(digest, 16)  # raises ValueError if not valid hex


class GetSetProcessedFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "cache"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_get_on_empty_cache_returns_none(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            self.assertIsNone(cache.get_processed_file("missing.py", 10, 1))

    def test_set_then_get_round_trips_the_same_dict(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            payload = {"language": "python", "file_hash": "abc123", "imports": ["os"], "exports": ["main"]}
            cache.set_processed_file("src/app.py", 42, 1000, payload)
            result = cache.get_processed_file("src/app.py", 42, 1000)
            self.assertEqual(result, payload)

    def test_changing_size_invalidates_the_cached_entry(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v1"})
            # Same path/mtime but a different size (e.g. the file grew) must
            # miss the cache -- this is the "alterar um arquivo invalida
            # somente o necessário" acceptance criterion at the unit level.
            self.assertIsNone(cache.get_processed_file("src/app.py", 43, 1000))

    def test_changing_mtime_invalidates_the_cached_entry(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v1"})
            self.assertIsNone(cache.get_processed_file("src/app.py", 42, 1001))

    def test_unrelated_files_do_not_invalidate_each_other(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/a.py", 10, 100, {"file_hash": "a"})
            cache.set_processed_file("src/b.py", 20, 200, {"file_hash": "b"})
            self.assertEqual(cache.get_processed_file("src/a.py", 10, 100), {"file_hash": "a"})
            self.assertEqual(cache.get_processed_file("src/b.py", 20, 200), {"file_hash": "b"})

    def test_set_overwrites_previous_entry_for_the_same_fingerprint(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v1"})
            cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v2"})
            self.assertEqual(cache.get_processed_file("src/app.py", 42, 1000), {"file_hash": "v2"})

    def test_get_returns_none_when_stored_value_is_not_a_dict(self) -> None:
        # Bypass set_processed_file to store a non-dict value directly, then
        # confirm the accessor's isinstance guard treats it as absent rather
        # than corrupting the caller with an unexpected type.
        with FileProcessingCache(self.cache_dir) as cache:
            key = cache.make_file_key("src/app.py", 1, 1)
            cache._cache.set(key, "not-a-dict")
            self.assertIsNone(cache.get_processed_file("src/app.py", 1, 1))

    def test_expire_evicts_entry_after_ttl(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/app.py", 1, 1, {"file_hash": "v1"}, expire=0.05)
            self.assertEqual(cache.get_processed_file("src/app.py", 1, 1), {"file_hash": "v1"})
            time.sleep(0.15)
            self.assertIsNone(cache.get_processed_file("src/app.py", 1, 1))

    def test_clear_removes_all_entries(self) -> None:
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/a.py", 1, 1, {"file_hash": "a"})
            cache.set_processed_file("src/b.py", 2, 2, {"file_hash": "b"})
            cache.clear()
            self.assertIsNone(cache.get_processed_file("src/a.py", 1, 1))
            self.assertIsNone(cache.get_processed_file("src/b.py", 2, 2))


class PersistenceAcrossInstancesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self._tmp.name) / "cache"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cached_entries_survive_close_and_reopen(self) -> None:
        # The cache is disk-backed (diskcache), so a fresh FileProcessingCache
        # pointed at the same directory must still see prior entries -- this
        # is what actually saves re-parsing work across mapper runs.
        cache = FileProcessingCache(self.cache_dir)
        cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v1"})
        cache.close()

        reopened = FileProcessingCache(self.cache_dir)
        try:
            self.assertEqual(reopened.get_processed_file("src/app.py", 42, 1000), {"file_hash": "v1"})
        finally:
            reopened.close()

    def test_version_bump_invalidates_entries_from_a_prior_cache_version(self) -> None:
        # make_file_key mixes in FileProcessingCache.VERSION. If the on-disk
        # schema for cached payloads ever changes, bumping VERSION must
        # silently invalidate stale entries rather than returning them (and
        # potentially corrupting the index with an incompatible shape).
        with FileProcessingCache(self.cache_dir) as cache:
            cache.set_processed_file("src/app.py", 42, 1000, {"file_hash": "v1"})

            class _NewerCache(FileProcessingCache):
                VERSION = "v3"

            newer = _NewerCache(self.cache_dir)
            try:
                self.assertIsNone(newer.get_processed_file("src/app.py", 42, 1000))
            finally:
                newer.close()


if __name__ == "__main__":
    unittest.main()
