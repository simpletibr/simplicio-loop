"""Tests for simplicio_mapper.mapper.canonical_gc (issue #268).

Covers the acceptance criteria from issue #268 ("[#263] Implementar
canonical gc crash-safe e conservador"):

* dry-run by default, mutation only with explicit opt-in (``apply=True``)
* never removes a valid/referenced manifest, a live "lock" (here: a tmp
  staging dir owned by a live PID), or a recently-promoted manifest
* recovers interrupted temp/promotion dirs only with proof of a dead PID or
  an expired lease -- never merely because a directory "looks old"
* receipt is versioned, lists candidates/removed/preserved with reasons, and
  never leaks an absolute path
* ten concurrent readers of the still-current manifest observe no
  interference while GC runs and removes unrelated stale entries
* a dead process holding a staging dir is reclaimed; an interrupted
  promotion (same shape) is reclaimed; repeated GC is idempotent

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import orjson  # noqa: E402

from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_gc import (  # noqa: E402
    GC_RECEIPT_SCHEMA,
    run_canonical_gc,
)
from simplicio_mapper.mapper.canonical_storage import (  # noqa: E402
    canonical_manifest_dir,
    canonical_manifest_tmp_dir,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    src = path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


def _dead_pid() -> int:
    """Spawn and wait on a trivial subprocess, returning its (now-dead) pid."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _backdate(path: Path, seconds_ago: float) -> None:
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


class CanonicalGCTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.storage_root = str(self.base / "storage")

    def _build(self, config_fingerprint: str = "cfg-1"):
        manifest = build_canonical_manifest(str(self.repo), self.storage_root, config_fingerprint)
        self.assertIsNotNone(manifest)
        return manifest

    def _gc(self, **kwargs) -> dict:
        return run_canonical_gc(str(self.repo), storage_root=self.storage_root, **kwargs)


class NoAbsolutePathLeakAndSchemaTests(CanonicalGCTestCase):
    def test_receipt_is_versioned_and_leaks_no_absolute_paths(self) -> None:
        self._build()
        receipt = self._gc()
        self.assertEqual(receipt["schema"], GC_RECEIPT_SCHEMA)
        self.assertIn("schema_version", receipt)
        self.assertIn("candidates", receipt)
        self.assertIn("removed", receipt)
        self.assertIn("preserved", receipt)
        serialized = json.dumps(receipt)
        self.assertNotIn(str(self.base), serialized)
        self.assertNotIn(self.storage_root, serialized)
        self.assertNotIn(str(self.repo), serialized)

    def test_dry_run_is_the_default_and_never_mutates(self) -> None:
        manifest = self._build()
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        tmp_dir = Path(
            canonical_manifest_tmp_dir(self.storage_root, "stale-digest", str(_dead_pid()))
        )
        tmp_dir.mkdir(parents=True)
        _backdate(tmp_dir, 10)

        receipt = self._gc()  # apply defaults to False
        self.assertEqual(receipt["mode"], "dry_run")
        self.assertTrue(digest_dir.is_dir())
        self.assertTrue(tmp_dir.is_dir(), "dry-run must never remove anything")
        self.assertEqual(receipt["removed"], [])
        remove_candidates = [c for c in receipt["candidates"] if c["action"] == "remove"]
        self.assertEqual(len(remove_candidates), 1)
        self.assertEqual(remove_candidates[0]["reason"], "dead_process_owner")


class NeverRemovesLiveOrCurrentTests(CanonicalGCTestCase):
    def test_never_removes_the_current_valid_manifest(self) -> None:
        manifest = self._build()
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        receipt = self._gc(apply=True)
        self.assertTrue(digest_dir.is_dir())
        self.assertEqual(receipt["removed"], [])
        preserved_reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertIn("current_reference", preserved_reasons)

    def test_never_removes_a_tmp_dir_owned_by_a_live_process(self) -> None:
        self._build()
        # Our own pid is alive for the whole test.
        tmp_dir = Path(
            canonical_manifest_tmp_dir(self.storage_root, "in-progress-digest", str(os.getpid()))
        )
        tmp_dir.mkdir(parents=True)
        _backdate(tmp_dir, 10)  # old enough to pass the malformed-grace check

        receipt = self._gc(apply=True)
        self.assertTrue(tmp_dir.is_dir(), "a live owner's staging dir must never be reclaimed")
        reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertIn("owner_alive", reasons)

    def test_never_removes_a_recently_promoted_superseded_generation(self) -> None:
        first = self._build(config_fingerprint="cfg-a")
        # New commit -> new digest, becomes the "current" one.
        (self.repo / "src" / "mod2.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
        _run(["add", "."], self.repo)
        _run(["commit", "-m", "second"], self.repo)
        self._build(config_fingerprint="cfg-a")

        old_digest_dir = Path(canonical_manifest_dir(self.storage_root, first.key.digest()))
        self.assertTrue(old_digest_dir.is_dir())

        receipt = self._gc(apply=True)  # default grace window (5 min) not elapsed
        self.assertTrue(old_digest_dir.is_dir(), "must not remove a manifest still inside its grace window")
        reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertIn("recently_promoted", reasons)

    def test_removes_superseded_generation_once_grace_window_elapses(self) -> None:
        first = self._build(config_fingerprint="cfg-a")
        (self.repo / "src" / "mod2.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
        _run(["add", "."], self.repo)
        _run(["commit", "-m", "second"], self.repo)
        self._build(config_fingerprint="cfg-a")

        old_digest_dir = Path(canonical_manifest_dir(self.storage_root, first.key.digest()))
        _backdate(old_digest_dir, 3600)

        receipt = self._gc(apply=True, promoted_grace_seconds=1.0)
        self.assertFalse(old_digest_dir.is_dir())
        removed_reasons = {c["reason"] for c in receipt["removed"]}
        self.assertIn("superseded_generation", removed_reasons)


class DeadProcessAndInterruptedPromotionTests(CanonicalGCTestCase):
    def test_dead_process_holding_staging_dir_is_reclaimed(self) -> None:
        self._build()
        dead_pid = _dead_pid()
        tmp_dir = Path(canonical_manifest_tmp_dir(self.storage_root, "crashed-digest", str(dead_pid)))
        tmp_dir.mkdir(parents=True)
        (tmp_dir / "project-map.json").write_text("{}", encoding="utf-8")
        _backdate(tmp_dir, 10)

        receipt = self._gc(apply=True)
        self.assertFalse(tmp_dir.exists())
        removed = {c["location"]: c for c in receipt["removed"]}
        self.assertTrue(any(v["reason"] == "dead_process_owner" for v in removed.values()))
        self.assertTrue(any(v.get("pid") == dead_pid for v in removed.values()))

    def test_interrupted_promotion_directory_is_reclaimed(self) -> None:
        """A promotion crashing mid-write leaves a `.tmp-<pid>` dir behind.

        Same shape as the dead-process case above (the builder's staging
        directory *is* the in-progress promotion) -- covered separately per
        issue #268's explicit "promoção interrompida" test-plan bullet, using
        a partially-written artifact set to stand in for the interruption.
        """
        self._build()
        dead_pid = _dead_pid()
        tmp_dir = Path(
            canonical_manifest_tmp_dir(self.storage_root, "interrupted-digest", str(dead_pid))
        )
        tmp_dir.mkdir(parents=True)
        # Partial write: only one of the real artifacts landed before the
        # (simulated) crash -- no manifest.json at all.
        (tmp_dir / "project-map.json").write_text('{"files": []}', encoding="utf-8")
        _backdate(tmp_dir, 10)
        final_dir = Path(canonical_manifest_dir(self.storage_root, "interrupted-digest"))
        self.assertFalse(final_dir.exists(), "interrupted promotion must never have been promoted")

        receipt = self._gc(apply=True)
        self.assertFalse(tmp_dir.exists())
        self.assertFalse(final_dir.exists())
        removed_locations = {c["location"] for c in receipt["removed"]}
        self.assertIn(f"canonical/{tmp_dir.name}", removed_locations)

    def test_malformed_tmp_token_only_reclaimed_after_lease_expiry(self) -> None:
        self._build()
        tmp_dir = Path(self.storage_root) / "canonical" / "weird-digest.tmp-not-a-pid"
        tmp_dir.mkdir(parents=True)

        # Not yet expired: preserved.
        receipt = self._gc(apply=True, ttl_seconds=3600)
        self.assertTrue(tmp_dir.is_dir())
        reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertIn("lease_not_expired", reasons)

        # Backdate past a short TTL: now reclaimable.
        _backdate(tmp_dir, 100)
        receipt = self._gc(apply=True, ttl_seconds=1)
        self.assertFalse(tmp_dir.exists())
        removed_reasons = {c["reason"] for c in receipt["removed"]}
        self.assertIn("lease_expired", removed_reasons)

    def test_crash_leftover_deleting_dir_is_always_finished(self) -> None:
        self._build()
        leftover = Path(self.storage_root) / "canonical" / "orphan-digest.deleting-abc123"
        leftover.mkdir(parents=True)
        (leftover / "partial.json").write_text("{}", encoding="utf-8")
        # No backdating at all -- must be reclaimed unconditionally.

        receipt = self._gc(apply=True)
        self.assertFalse(leftover.exists())
        removed_reasons = {c["reason"] for c in receipt["removed"]}
        self.assertIn("crash_leftover_deleting", removed_reasons)


class RepeatedGCIsIdempotentTests(CanonicalGCTestCase):
    def test_repeated_gc_converges_to_no_further_removals(self) -> None:
        self._build()
        tmp_dir = Path(
            canonical_manifest_tmp_dir(self.storage_root, "stale-digest", str(_dead_pid()))
        )
        tmp_dir.mkdir(parents=True)
        _backdate(tmp_dir, 10)

        first = self._gc(apply=True)
        self.assertEqual(len(first["removed"]), 1)

        second = self._gc(apply=True)
        self.assertEqual(second["removed"], [])
        third = self._gc(apply=True)
        self.assertEqual(third["removed"], [])
        # `age_seconds` ticks forward between calls -- idempotency here means
        # the same *set* of locations/reasons/actions converges, not
        # byte-identical receipts.
        def _strip_age(entries: list[dict]) -> list[dict]:
            return [{k: v for k, v in entry.items() if k != "age_seconds"} for entry in entries]

        self.assertEqual(_strip_age(third["preserved"]), _strip_age(second["preserved"]))
        self.assertEqual(_strip_age(third["candidates"]), _strip_age(second["candidates"]))


class ConcurrentReadsDuringGCTests(CanonicalGCTestCase):
    def test_ten_concurrent_readers_see_no_interference(self) -> None:
        manifest = self._build()
        digest_dir = Path(canonical_manifest_dir(self.storage_root, manifest.key.digest()))
        manifest_path = digest_dir / "manifest.json"

        # Unrelated, genuinely stale entries GC should reclaim concurrently.
        for index in range(3):
            tmp_dir = Path(
                canonical_manifest_tmp_dir(self.storage_root, f"stale-{index}", str(_dead_pid()))
            )
            tmp_dir.mkdir(parents=True)
            _backdate(tmp_dir, 10)

        errors: list[Exception] = []
        stop = threading.Event()

        def _reader() -> None:
            while not stop.is_set():
                try:
                    with open(manifest_path, "rb") as handle:
                        payload = orjson.loads(handle.read())
                    assert payload["schema"]
                except Exception as error:  # noqa: BLE001 - captured for the assertion below
                    errors.append(error)
                    return

        threads = [threading.Thread(target=_reader) for _ in range(10)]
        for thread in threads:
            thread.start()
        try:
            for _ in range(5):
                self._gc(apply=True)
        finally:
            stop.set()
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertTrue(digest_dir.is_dir())
        self.assertTrue(manifest_path.is_file())


class OtherRepoOutOfScopeTests(CanonicalGCTestCase):
    def test_manifest_for_a_different_repo_identity_is_never_touched(self) -> None:
        self._build()
        other_repo = self.base / "other-repo"
        _init_repo(other_repo, default_branch="main")
        other_manifest = build_canonical_manifest(str(other_repo), self.storage_root, "cfg-1")
        self.assertIsNotNone(other_manifest)
        other_digest_dir = Path(canonical_manifest_dir(self.storage_root, other_manifest.key.digest()))
        _backdate(other_digest_dir, 3600)

        receipt = self._gc(apply=True, promoted_grace_seconds=0.0)
        self.assertTrue(other_digest_dir.is_dir())
        reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertIn("other_repo_out_of_scope", reasons)


class BrokenManifestTests(CanonicalGCTestCase):
    def test_broken_manifest_directory_is_reclaimed_after_grace(self) -> None:
        self._build()
        broken_dir = Path(self.storage_root) / "canonical" / "broken-digest"
        broken_dir.mkdir(parents=True)
        (broken_dir / "manifest.json").write_text("not-json{{{", encoding="utf-8")
        _backdate(broken_dir, 3600)

        receipt = self._gc(apply=True, ttl_seconds=1)
        self.assertFalse(broken_dir.exists())
        removed_reasons = {c["reason"] for c in receipt["removed"]}
        self.assertIn("broken_manifest_expired", removed_reasons)

    def test_freshly_created_broken_manifest_is_preserved(self) -> None:
        self._build()
        broken_dir = Path(self.storage_root) / "canonical" / "broken-digest-fresh"
        broken_dir.mkdir(parents=True)
        (broken_dir / "manifest.json").write_text("not-json{{{", encoding="utf-8")

        receipt = self._gc(apply=True)
        self.assertTrue(broken_dir.is_dir())
        reasons = {c["reason"] for c in receipt["preserved"]}
        self.assertTrue({"too_young_to_judge", "lease_not_expired"} & reasons)


if __name__ == "__main__":
    unittest.main()
