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

from simplicio_mapper.cli._index_engine import (  # noqa: E402
    INDEX_LOCK_SCHEMA,
    MALFORMED_LOCK_GRACE_SECONDS,
    _acquire_index_lock,
    _IndexLockHandle,
    _inspect_index_lock,
    _lock_path,
    _process_start_token,
    _release_index_lock,
)
from simplicio_mapper.cli._status_engine import _status_payload  # noqa: E402


class IndexLockRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = ".simplicio"
        self.path = Path(_lock_path(str(self.root), self.out))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_json(self, *, pid: int, process_start: str, acquired_at: float, token: str = "owner") -> None:
        self.path.write_text(
            json.dumps(
                {
                    "schema": INDEX_LOCK_SCHEMA,
                    "pid": pid,
                    "process_start": process_start,
                    "token": token,
                    "acquired_at": acquired_at,
                }
            ),
            encoding="utf-8",
        )

    def test_lock_record_has_pid_start_token_and_owned_release(self) -> None:
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        assert lock is not None
        record = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], INDEX_LOCK_SCHEMA)
        self.assertEqual(record["pid"], os.getpid())
        self.assertTrue(record["process_start"])
        self.assertEqual(record["token"], lock.token)

        _release_index_lock(_IndexLockHandle(str(self.path), "not-the-owner"))
        self.assertTrue(self.path.exists())
        _release_index_lock(lock)
        self.assertFalse(self.path.exists())

    def test_live_lock_serializes_concurrent_acquisition(self) -> None:
        barrier = threading.Barrier(8)
        winners: list[_IndexLockHandle] = []
        guard = threading.Lock()

        def contend() -> None:
            barrier.wait()
            lock = _acquire_index_lock(str(self.root), self.out)
            if lock is not None:
                with guard:
                    winners.append(lock)

        threads = [threading.Thread(target=contend) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(winners), 1)
        _release_index_lock(winners[0])

    def test_dead_json_lock_is_recovered(self) -> None:
        self._write_json(pid=2_147_483_647, process_start="gone", acquired_at=time.time())
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        assert lock is not None
        self.assertNotEqual(json.loads(self.path.read_text(encoding="utf-8"))["token"], "owner")
        _release_index_lock(lock)

    def test_ttl_expired_live_lock_is_recovered(self) -> None:
        start = _process_start_token(os.getpid()) or "unknown"
        self._write_json(pid=os.getpid(), process_start=start, acquired_at=0)
        status = _inspect_index_lock(str(self.root), self.out, recover=True)
        self.assertTrue(status["recovered"])
        self.assertEqual(status["reason"], "ttl_expired")

    def test_pid_reuse_start_mismatch_is_recovered(self) -> None:
        self._write_json(pid=os.getpid(), process_start="different-start", acquired_at=time.time())
        status = _inspect_index_lock(str(self.root), self.out, recover=True)
        if _process_start_token(os.getpid()) is None:
            self.skipTest("OS does not expose process start identity")
        self.assertTrue(status["recovered"])
        self.assertEqual(status["reason"], "pid_reused")

    def test_live_legacy_pid_lock_remains_compatible(self) -> None:
        self.path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        self.assertIsNone(_acquire_index_lock(str(self.root), self.out))
        status = _inspect_index_lock(str(self.root), self.out)
        self.assertTrue(status["active"])
        self.assertEqual(status["reason"], "legacy_live")

    def test_dead_legacy_pid_lock_is_recovered(self) -> None:
        self.path.write_text("2147483647\n", encoding="utf-8")
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        _release_index_lock(lock)

    def test_old_malformed_lock_is_recovered_but_fresh_partial_write_is_not(self) -> None:
        self.path.write_text("not-json", encoding="utf-8")
        self.assertIsNone(_acquire_index_lock(str(self.root), self.out))
        old = time.time() - MALFORMED_LOCK_GRACE_SECONDS - 1
        os.utime(self.path, (old, old))
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        _release_index_lock(lock)

    @unittest.skipUnless(os.name == "nt", "Windows kill/recovery coverage")
    def test_windows_killed_owner_is_recovered(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            start = _process_start_token(child.pid) or "unknown"
            self._write_json(pid=child.pid, process_start=start, acquired_at=time.time())
            self.assertTrue(_inspect_index_lock(str(self.root), self.out)["active"])
            child.terminate()
            child.wait(timeout=5)
            lock = _acquire_index_lock(str(self.root), self.out)
            self.assertIsNotNone(lock)
            _release_index_lock(lock)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_status_recovers_orphan_and_becomes_terminal(self) -> None:
        self._write_json(pid=2_147_483_647, process_start="gone", acquired_at=time.time())
        map_job = self.path.parent / "map-job.json"
        map_job.write_text(
            json.dumps(
                {
                    "schema": "simplicio.map-job/v1",
                    "phase": "macro_done",
                    "deep": {"pid": 2_147_483_647, "process_start": "gone"},
                }
            ),
            encoding="utf-8",
        )
        payload = _status_payload(str(self.root), self.out)
        self.assertEqual(payload["phase"], "failed")
        self.assertTrue(payload["terminal"])
        self.assertTrue(payload["lock_status"]["recovered"])
        self.assertEqual(payload["lock_status"]["reason"], "dead_process")
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
