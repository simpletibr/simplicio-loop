"""Cross-worktree single-flight lock for the canonical-map builder (issue #236 gap #1).

ADR-008 (.specs/architecture/ADR-008-canonical-map-overlays.md) section 4
called for generalizing the existing, battle-tested index lock
(``simplicio_mapper.cli._index_engine`` / now
``simplicio_mapper.mapper.file_lock``) to a second ``operation`` value
(``"canonical-build"``) instead of writing a second lock implementation, and
wiring it into ``build_canonical_manifest`` so a losing builder waits
(bounded) for the winner's promotion rather than redoing the full
detached-checkout-and-pipeline-run work.

This module covers, in order:

* Unit -- lock acquire/wait/timeout logic in isolation, against a bare lock
  file with no git repo involved at all (``LockWaitLogicUnitTest``).
* Integration -- a real git repo + a real, manually-pre-created lock file,
  proving ``build_canonical_manifest`` actually waits/reuses/times out
  correctly against real filesystem state
  (``BuildCanonicalManifestLockIntegrationTest``).
* System -- two real OS processes racing `simplicio-mapper canonical build`
  against the same repo/digest, proving only one of them actually runs the
  expensive pipeline (``CanonicalBuildLockConcurrentProcessRaceTest``),
  mirroring the existing pattern in
  ``tests/python/test_lock_recovery.py::IndexLockConcurrentProcessRaceTest``.

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

from simplicio_mapper.mapper.canonical_builder import (  # noqa: E402
    build_canonical_manifest,
    build_canonical_manifest_with_diagnostics,
)
from simplicio_mapper.mapper.canonical_storage import (  # noqa: E402
    canonical_build_lock_path,
    canonical_manifest_dir,
)
from simplicio_mapper.mapper.file_lock import (  # noqa: E402
    acquire_lock_at,
    inspect_lock_at,
    release_lock_at,
)


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--initial-branch", default_branch], path)
    _run_git(["config", "user.email", "test@example.com"], path)
    _run_git(["config", "user.name", "Test User"], path)
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    src = path / "src"
    src.mkdir(exist_ok=True)
    (src / "mod.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run_git(["add", "."], path)
    _run_git(["commit", "-m", "init"], path)


class LockWaitLogicUnitTest(unittest.TestCase):
    """Unit-level coverage of the wait/timeout state machine, no git involved."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.lock_path = os.path.join(self._tmp.name, "canonical", "digest.build.lock")

    def test_acquire_then_release_round_trips(self) -> None:
        lock = acquire_lock_at(self.lock_path, operation="canonical-build")
        self.assertIsNotNone(lock)
        status = inspect_lock_at(self.lock_path)
        self.assertTrue(status["active"])
        self.assertEqual(status["owner"]["operation"], "canonical-build")
        release_lock_at(lock)
        self.assertFalse(inspect_lock_at(self.lock_path)["exists"])

    def test_second_acquire_fails_while_first_still_live(self) -> None:
        first = acquire_lock_at(self.lock_path, operation="canonical-build")
        self.assertIsNotNone(first)
        second = acquire_lock_at(self.lock_path, operation="canonical-build")
        self.assertIsNone(second)
        release_lock_at(first)

    def test_lock_becomes_acquirable_again_after_release(self) -> None:
        first = acquire_lock_at(self.lock_path, operation="canonical-build")
        release_lock_at(first)
        second = acquire_lock_at(self.lock_path, operation="canonical-build")
        self.assertIsNotNone(second)
        release_lock_at(second)

    def test_extra_fields_are_carried_into_the_lock_record(self) -> None:
        lock = acquire_lock_at(
            self.lock_path,
            operation="canonical-build",
            extra_fields={"root_fingerprint": "abc123", "digest": "deadbeef"},
        )
        self.assertIsNotNone(lock)
        status = inspect_lock_at(self.lock_path)
        self.assertEqual(status["owner"]["root_fingerprint"], "abc123")
        self.assertEqual(status["owner"]["digest"], "deadbeef")
        release_lock_at(lock)

    def test_release_is_a_noop_for_a_handle_that_is_not_the_current_owner(self) -> None:
        lock = acquire_lock_at(self.lock_path, operation="canonical-build")
        from simplicio_mapper.mapper.file_lock import LockHandle

        release_lock_at(LockHandle(self.lock_path, "not-the-real-token"))
        # The genuine owner's lock must still be there.
        self.assertTrue(inspect_lock_at(self.lock_path)["active"])
        release_lock_at(lock)


class BuildCanonicalManifestLockIntegrationTest(unittest.TestCase):
    """Real git repo + a real, manually-held lock file (no second process)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.storage_root = str(self.base / "storage")

    def test_blocking_false_fails_fast_when_lock_is_held(self) -> None:
        cache_root = os.path.abspath(self.storage_root)
        # We don't know the exact digest the real builder will compute
        # (mapper_version differs), so acquire the lock via the *builder's*
        # own path arithmetic by first doing a real (uncontended) build to
        # learn the digest, then re-lock it and prove a second call
        # fails fast.
        first = build_canonical_manifest(str(self.repo), self.storage_root, "cfg-lockprobe")
        self.assertIsNotNone(first)
        digest = first.key.digest()
        lock_path = canonical_build_lock_path(cache_root, digest)

        # Force a cache-miss on the second call so the lock path is actually
        # exercised: point at the digest dir removed, forcing a rebuild
        # attempt against the very same commit/config (still same digest).
        digest_dir = Path(canonical_manifest_dir(cache_root, digest))
        import shutil

        shutil.rmtree(digest_dir, ignore_errors=True)

        held = acquire_lock_at(lock_path, operation="canonical-build")
        self.assertIsNotNone(held)
        try:
            result = build_canonical_manifest_with_diagnostics(
                str(self.repo), self.storage_root, "cfg-lockprobe", blocking=False
            )
            self.assertIsNone(result.manifest)
            self.assertEqual(result.reason_code, "lock_contended_fail_fast")
        finally:
            release_lock_at(held)

    def test_blocking_true_waits_then_reuses_manifest_the_winner_promotes(self) -> None:
        """The core win-condition of this fix: the loser never re-runs the pipeline.

        Simulates a "winner" by holding the build lock on a background
        thread, writing the real promoted manifest shortly after (as the
        real builder would), then releasing. The blocking caller must
        observe `reused_after_wait`, never redo the checkout+pipeline work.
        """
        first = build_canonical_manifest(str(self.repo), self.storage_root, "cfg-waitreuse")
        self.assertIsNotNone(first)
        cache_root = os.path.abspath(self.storage_root)
        digest = first.key.digest()
        lock_path = canonical_build_lock_path(cache_root, digest)
        digest_dir = Path(canonical_manifest_dir(cache_root, digest))

        import shutil

        shutil.rmtree(digest_dir, ignore_errors=True)

        held = acquire_lock_at(lock_path, operation="canonical-build")
        self.assertIsNotNone(held)

        # A donor build under a *different* cache root but the *same*
        # config_fingerprint -- `CanonicalMapKey.digest()` (and therefore
        # every field serialized into `manifest.json`'s own `"key"`) depends
        # only on repo identity/commit/config, never on the storage root, so
        # this produces a manifest byte-identical in content to what the real
        # winner would promote at `digest_dir`, without colliding with the
        # lock this test holds manually via `held`.
        donor_storage_root = str(self.base / "donor-storage")

        def _simulate_winner() -> None:
            time.sleep(0.3)
            manifest = build_canonical_manifest(str(self.repo), donor_storage_root, "cfg-waitreuse")
            self.assertIsNotNone(manifest)
            self.assertEqual(manifest.key.digest(), digest)
            digest_dir.mkdir(parents=True, exist_ok=True)
            src_dir = Path(canonical_manifest_dir(os.path.abspath(donor_storage_root), digest))
            for item in src_dir.iterdir():
                shutil.copy2(item, digest_dir / item.name)
            release_lock_at(held)

        thread = threading.Thread(target=_simulate_winner)
        thread.start()
        try:
            result = build_canonical_manifest_with_diagnostics(
                str(self.repo),
                str(self.base / "storage"),
                "cfg-waitreuse",
                lock_wait_seconds=10.0,
            )
        finally:
            thread.join(timeout=10)

        self.assertIsNotNone(result.manifest)
        self.assertEqual(result.reason_code, "reused_after_wait")

    def test_blocking_true_times_out_when_lock_never_frees(self) -> None:
        first = build_canonical_manifest(str(self.repo), self.storage_root, "cfg-timeout")
        self.assertIsNotNone(first)
        cache_root = os.path.abspath(self.storage_root)
        digest = first.key.digest()
        lock_path = canonical_build_lock_path(cache_root, digest)
        digest_dir = Path(canonical_manifest_dir(cache_root, digest))

        import shutil

        shutil.rmtree(digest_dir, ignore_errors=True)

        held = acquire_lock_at(lock_path, operation="canonical-build")
        self.assertIsNotNone(held)
        try:
            start = time.monotonic()
            result = build_canonical_manifest_with_diagnostics(
                str(self.repo), self.storage_root, "cfg-timeout", lock_wait_seconds=0.5
            )
            elapsed = time.monotonic() - start
            self.assertIsNone(result.manifest)
            self.assertEqual(result.reason_code, "lock_wait_timeout")
            # Bounded: must not block anywhere near the lock's own dead-owner
            # TTL (hours) -- only the short caller-specified wait budget.
            self.assertLess(elapsed, 5.0)
        finally:
            release_lock_at(held)

    def test_uncontended_build_reports_built_reason_code(self) -> None:
        result = build_canonical_manifest_with_diagnostics(
            str(self.repo), self.storage_root, "cfg-plain-build"
        )
        self.assertIsNotNone(result.manifest)
        self.assertEqual(result.reason_code, "built")

    def test_cache_hit_reports_reused_cache_hit_reason_code(self) -> None:
        build_canonical_manifest(str(self.repo), self.storage_root, "cfg-plain-hit")
        result = build_canonical_manifest_with_diagnostics(
            str(self.repo), self.storage_root, "cfg-plain-hit"
        )
        self.assertEqual(result.reason_code, "reused_cache_hit")

    def test_lock_file_is_released_after_a_successful_build(self) -> None:
        manifest = build_canonical_manifest(str(self.repo), self.storage_root, "cfg-release-check")
        self.assertIsNotNone(manifest)
        cache_root = os.path.abspath(self.storage_root)
        lock_path = canonical_build_lock_path(cache_root, manifest.key.digest())
        self.assertFalse(os.path.exists(lock_path))


class CanonicalBuildLockConcurrentProcessRaceTest(unittest.TestCase):
    """Process-level (not thread-level) proof: only one process runs the pipeline."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.cache_root = str(self.base / "cache")
        old = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = self.cache_root

        def _restore() -> None:
            if old is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = old

        self.addCleanup(_restore)

    def test_two_concurrent_canonical_build_invocations_never_both_run_the_pipeline(self) -> None:
        # issue #236 gap #1 AC: two real OS processes race
        # `canonical build` against the same repo (-> same digest). Exactly
        # one of them may report a reason code proving it ran the real
        # pipeline (`built`); the other must report a reason code proving it
        # never redid that work (`reused_after_wait`, `reused_cache_hit`, or
        # `built_after_wait` if the first crashed mid-build -- not the case
        # here since both run to completion).
        args = [
            sys.executable,
            "-m",
            "simplicio_mapper.cli",
            "canonical",
            "build",
            str(self.repo),
            "--json",
        ]
        popen_kwargs = {
            "cwd": str(ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "env": {**os.environ},
        }
        first = subprocess.Popen(args, **popen_kwargs)
        second = subprocess.Popen(args, **popen_kwargs)
        out1, err1 = first.communicate(timeout=120)
        out2, err2 = second.communicate(timeout=120)
        self.assertEqual(first.returncode, 0, err1)
        self.assertEqual(second.returncode, 0, err2)
        payload1 = json.loads(out1.strip().splitlines()[-1])
        payload2 = json.loads(out2.strip().splitlines()[-1])

        for payload in (payload1, payload2):
            self.assertEqual(payload["status"], "ok", payload)

        reason_codes = sorted([payload1["reason_code"], payload2["reason_code"]])
        # Exactly one process must report having actually run the pipeline
        # uncontended-first ("built"); the other must report a code that
        # proves it *never* redid that work itself.
        never_redid_codes = {"reused_after_wait", "reused_cache_hit", "built_after_wait"}
        self.assertIn("built", reason_codes, reason_codes)
        other = reason_codes[0] if reason_codes[1] == "built" else reason_codes[1]
        self.assertIn(other, never_redid_codes, reason_codes)

        # Both must agree on the resulting manifest content (content-addressed
        # -> byte-identical outcome regardless of who built it).
        self.assertEqual(payload1["manifest"]["counts"], payload2["manifest"]["counts"])
        self.assertEqual(
            payload1["manifest"]["file_manifest_digest"],
            payload2["manifest"]["file_manifest_digest"],
        )

        # No stray lock file left behind by either process.
        from simplicio_mapper.mapper.canonical_storage import canonical_build_lock_path

        digest = payload1["key"]["digest"]
        lock_path = canonical_build_lock_path(os.path.abspath(self.cache_root), digest)
        self.assertFalse(os.path.exists(lock_path))


if __name__ == "__main__":
    unittest.main()
