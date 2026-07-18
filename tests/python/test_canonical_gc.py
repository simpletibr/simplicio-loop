"""Unit/integration tests for simplicio_mapper.mapper.canonical_gc (issue #268).

Exercises the conservative, crash-safe canonical-map GC against real
temporary git repositories and real subprocesses (never a mocked
filesystem/lock seam) -- covers concurrent "readers" that must never be
reclaimed, a dead process's abandoned temp dir that IS reclaimed, an
interrupted promotion cleaned up only after proving staleness, running GC
twice in a row (idempotent), and dry-run vs ``--apply`` behavior.

Run with: python3 -m unittest discover -s tests/python
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.mapper.canonical_builder import build_canonical_manifest  # noqa: E402
from simplicio_mapper.mapper.canonical_gc import (  # noqa: E402
    CANONICAL_GC_SCHEMA,
    CANONICAL_GC_SCHEMA_VERSION,
    scan_canonical_gc,
)


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path: Path, *, default_branch: str = "main") -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["init", "--initial-branch", default_branch], path)
    _run(["config", "user.email", "test@example.com"], path)
    _run(["config", "user.name", "Test User"], path)
    (path / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-m", "init"], path)


def _spawn_sleeper() -> subprocess.Popen:
    """Spawn a real subprocess that stays alive until terminated."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _spawn_and_reap() -> int:
    """Spawn and wait for a real subprocess to exit; return its now-dead pid."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=10)
    return proc.pid


class CanonicalGcTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.repo = self.base / "repo"
        _init_repo(self.repo)
        self.cache_root = str(self.base / "cache")
        self._env_patch = {"SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR": self.cache_root}
        self._old_env = {k: os.environ.get(k) for k in self._env_patch}
        os.environ.update(self._env_patch)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _canonical_dir(self) -> Path:
        path = Path(self.cache_root) / "canonical"
        path.mkdir(parents=True, exist_ok=True)
        return path


class ReportShapeTests(CanonicalGcTestBase):
    def test_empty_storage_root_yields_empty_report(self) -> None:
        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.schema, CANONICAL_GC_SCHEMA)
        self.assertEqual(report.schema_version, CANONICAL_GC_SCHEMA_VERSION)
        self.assertFalse(report.apply)
        self.assertEqual(report.candidates, [])
        self.assertEqual(report.removed, [])
        self.assertEqual(report.recovered, [])
        self.assertEqual(report.preserved, [])
        self.assertEqual(report.errors, [])

    def test_receipt_never_contains_absolute_paths(self) -> None:
        build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        report = scan_canonical_gc(str(self.repo))
        payload = report.to_dict()
        blob = str(payload)
        # No leaked absolute filesystem path from this test's own tempdir.
        self.assertNotIn(str(self.base), blob)
        self.assertNotIn(self.cache_root, blob)

    def test_non_git_root_without_override_reports_error_not_crash(self) -> None:
        old = os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR", None)
        try:
            plain = self.base / "plain"
            plain.mkdir()
            report = scan_canonical_gc(str(plain))
            self.assertTrue(report.errors)
            self.assertEqual(report.candidates, [])
        finally:
            if old is not None:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_CACHE_DIR"] = old


class CurrentManifestPreservationTests(CanonicalGcTestBase):
    def test_current_default_branch_manifest_is_never_a_candidate(self) -> None:
        manifest = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(manifest)
        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.candidates, [])
        self.assertEqual(len(report.preserved), 1)
        self.assertEqual(report.preserved[0].reason, "current_default_branch_manifest")

    def test_ten_concurrent_readers_never_see_their_snapshot_removed(self) -> None:
        """Simulate 10 concurrent readers of the same current manifest.

        Each "reader" is a real thread calling scan_canonical_gc(apply=True)
        concurrently while the manifest is the current default-branch
        snapshot -- none of them may ever remove it, and the manifest must
        still be on disk (and reusable) after all of them finish.
        """
        import threading

        manifest = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(manifest)
        digest_dir = self._canonical_dir() / manifest.key.digest()
        self.assertTrue(digest_dir.is_dir())

        results: list[dict] = []
        errors: list[Exception] = []
        barrier = threading.Barrier(10)

        def _reader() -> None:
            try:
                barrier.wait(timeout=10)
                report = scan_canonical_gc(str(self.repo), apply=True)
                results.append(report.to_dict())
            except Exception as error:  # noqa: BLE001 - surfaced via `errors`
                errors.append(error)

        threads = [threading.Thread(target=_reader) for _ in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 10)
        for result in results:
            self.assertEqual(result["removed"], [])
            self.assertEqual(result["recovered"], [])
        self.assertTrue(digest_dir.is_dir(), "current manifest must survive concurrent GC runs")
        self.assertTrue((digest_dir / "manifest.json").is_file())

    def test_unable_to_resolve_identity_preserves_everything(self) -> None:
        build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        plain = self.base / "plain-root"
        plain.mkdir()
        # `root` passed to scan_canonical_gc is not itself a git repo, but the
        # cache-root override still points at real canonical storage.
        report = scan_canonical_gc(str(plain))
        self.assertEqual(report.candidates, [])
        self.assertEqual(len(report.preserved), 1)
        self.assertEqual(report.preserved[0].reason, "unable_to_resolve_current_identity")


class TempDirLivenessTests(CanonicalGcTestBase):
    def test_temp_dir_with_alive_builder_pid_is_preserved(self) -> None:
        proc = _spawn_sleeper()
        self.addCleanup(lambda: (proc.terminate(), proc.wait(timeout=10)))
        tmp_dir = self._canonical_dir() / f"digest-alive.tmp-{proc.pid}"
        tmp_dir.mkdir()

        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.candidates, [])
        self.assertEqual(len(report.preserved), 1)
        self.assertEqual(report.preserved[0].reason, "temp_dir_builder_pid_alive")
        self.assertTrue(tmp_dir.is_dir())

    def test_temp_dir_with_dead_builder_pid_past_grace_is_reclaimed_on_apply(self) -> None:
        dead_pid = _spawn_and_reap()
        tmp_dir = self._canonical_dir() / f"digest-dead.tmp-{dead_pid}"
        tmp_dir.mkdir()
        project_map = tmp_dir / "project-map.json"
        project_map.write_text("{}", encoding="utf-8")
        past = time.time() - 1000
        os.utime(project_map, (past, past))
        os.utime(tmp_dir, (past, past))

        dry_run = scan_canonical_gc(str(self.repo), apply=False)
        self.assertEqual(len(dry_run.candidates), 1)
        self.assertEqual(dry_run.candidates[0].reason, "temp_dir_builder_pid_dead")
        self.assertEqual(dry_run.removed, [])
        self.assertEqual(dry_run.recovered, [])
        self.assertTrue(tmp_dir.is_dir(), "dry-run must never delete")

        applied = scan_canonical_gc(str(self.repo), apply=True)
        self.assertEqual(len(applied.recovered), 1)
        self.assertEqual(applied.recovered[0].reason, "temp_dir_builder_pid_dead")
        self.assertFalse(tmp_dir.exists(), "apply must actually reclaim the dead temp dir")

    def test_temp_dir_within_grace_window_is_preserved_even_with_dead_pid(self) -> None:
        dead_pid = _spawn_and_reap()
        tmp_dir = self._canonical_dir() / f"digest-recent.tmp-{dead_pid}"
        tmp_dir.mkdir()
        # No os.utime() call -- mtime is "now", well inside the default
        # 60s grace window, simulating a build that JUST crashed/finished.
        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.candidates, [])
        self.assertEqual(report.preserved[0].reason, "temp_dir_within_grace_window")
        self.assertTrue(tmp_dir.is_dir())

    def test_temp_dir_with_unparseable_token_past_grace_is_reclaimed(self) -> None:
        tmp_dir = self._canonical_dir() / "digest-weird.tmp-not-a-pid"
        tmp_dir.mkdir()
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))

        applied = scan_canonical_gc(str(self.repo), apply=True)
        self.assertEqual(len(applied.recovered), 1)
        self.assertEqual(applied.recovered[0].reason, "temp_dir_token_unparseable_stale")
        self.assertFalse(tmp_dir.exists())


class IdempotencyTests(CanonicalGcTestBase):
    def test_running_gc_twice_in_a_row_is_idempotent(self) -> None:
        dead_pid = _spawn_and_reap()
        tmp_dir = self._canonical_dir() / f"digest-idem.tmp-{dead_pid}"
        tmp_dir.mkdir()
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))

        first = scan_canonical_gc(str(self.repo), apply=True)
        self.assertEqual(len(first.recovered), 1)
        self.assertFalse(tmp_dir.exists())

        second = scan_canonical_gc(str(self.repo), apply=True)
        self.assertEqual(second.recovered, [])
        self.assertEqual(second.candidates, [])
        self.assertEqual(second.errors, [])

    def test_dry_run_twice_with_nothing_reclaimable_reports_same_empty_result(self) -> None:
        build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        first = scan_canonical_gc(str(self.repo), apply=False)
        second = scan_canonical_gc(str(self.repo), apply=False)
        self.assertEqual(first.to_dict()["candidates"], second.to_dict()["candidates"])
        self.assertEqual(first.to_dict()["candidates"], [])


class StaleManifestTests(CanonicalGcTestBase):
    def test_manifest_for_superseded_commit_within_ttl_is_preserved(self) -> None:
        first = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(first)
        (self.repo / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
        _run(["add", "."], self.repo)
        _run(["commit", "-m", "second"], self.repo)
        second = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(second)
        self.assertNotEqual(first.key.digest(), second.key.digest())

        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.candidates, [])
        reasons = {c.reason for c in report.preserved}
        self.assertIn("current_default_branch_manifest", reasons)
        self.assertIn("within_grace_window_recent_promotion", reasons)

    def test_manifest_for_superseded_commit_past_ttl_is_gc_candidate(self) -> None:
        first = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(first)
        first_digest_dir = self._canonical_dir() / first.key.digest()

        (self.repo / "b.py").write_text("def bar():\n    return 2\n", encoding="utf-8")
        _run(["add", "."], self.repo)
        _run(["commit", "-m", "second"], self.repo)
        second = build_canonical_manifest(str(self.repo), self.cache_root, "cfg-1")
        self.assertIsNotNone(second)

        old_env = os.environ.get("SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS")
        os.environ["SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS"] = "1"
        try:
            import orjson

            past = time.time() - 100
            manifest_path = first_digest_dir / "manifest.json"
            manifest_payload = orjson.loads(manifest_path.read_bytes())
            manifest_payload["created_at"] = "2020-01-01T00:00:00.000Z"
            manifest_path.write_bytes(orjson.dumps(manifest_payload))
            os.utime(first_digest_dir, (past, past))
            for name in os.listdir(first_digest_dir):
                os.utime(first_digest_dir / name, (past, past))

            report = scan_canonical_gc(str(self.repo), apply=True)
            removed_paths = {c.relative_path for c in report.removed}
            self.assertIn(f"canonical/{first.key.digest()}", removed_paths)
            self.assertFalse(first_digest_dir.exists())
            second_digest_dir = self._canonical_dir() / second.key.digest()
            self.assertTrue(second_digest_dir.exists(), "current manifest must survive")
        finally:
            if old_env is None:
                os.environ.pop("SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS", None)
            else:
                os.environ["SIMPLICIO_MAPPER_CANONICAL_GC_TTL_SECONDS"] = old_env


class BuildLockRecordTests(CanonicalGcTestBase):
    """Forward-compat coverage for an optional `build.lock` inside a temp dir.

    No production writer creates this file yet (see canonical_gc.py module
    docstring) -- these tests only prove the detection path itself is
    correct so a future `canonical_builder.py` change can start writing one
    without `canonical gc` needing changes.
    """

    def test_live_build_lock_preserves_temp_dir_even_with_dead_token_pid(self) -> None:
        import orjson

        alive_proc = _spawn_sleeper()
        self.addCleanup(lambda: (alive_proc.terminate(), alive_proc.wait(timeout=10)))
        dead_pid = _spawn_and_reap()
        tmp_dir = self._canonical_dir() / f"digest-lock.tmp-{dead_pid}"
        tmp_dir.mkdir()
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))
        (tmp_dir / "build.lock").write_bytes(
            orjson.dumps({"pid": alive_proc.pid, "process_start_identity": "unknown"})
        )

        report = scan_canonical_gc(str(self.repo))
        self.assertEqual(report.candidates, [])
        self.assertEqual(report.preserved[0].reason, "temp_dir_build_lock_live")

    def test_dead_build_lock_pid_is_reclaimed_past_grace(self) -> None:
        import orjson

        dead_pid = _spawn_and_reap()
        tmp_dir = self._canonical_dir() / "digest-deadlock.tmp-999999"
        tmp_dir.mkdir()
        past = time.time() - 1000
        os.utime(tmp_dir, (past, past))
        (tmp_dir / "build.lock").write_bytes(orjson.dumps({"pid": dead_pid}))

        applied = scan_canonical_gc(str(self.repo), apply=True)
        self.assertEqual(len(applied.recovered), 1)
        self.assertEqual(applied.recovered[0].reason, "temp_dir_build_lock_dead")
        self.assertFalse(tmp_dir.exists())


if __name__ == "__main__":
    unittest.main()
