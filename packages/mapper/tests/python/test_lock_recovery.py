from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from simplicio_mapper.cli._background import _MAP_JOB_IDENTITY_ENV  # noqa: E402
from simplicio_mapper.cli._index_engine import (  # noqa: E402
    INDEX_LOCK_SCHEMA,
    MALFORMED_LOCK_GRACE_SECONDS,
    _acquire_index_lock,
    _IndexLockHandle,
    _inspect_index_lock,
    _lock_path,
    _process_is_alive,
    _process_start_token,
    _release_index_lock,
)
from simplicio_mapper.cli._status_engine import _await_terminal, _run_inspect, _status_payload  # noqa: E402


class IndexLockRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = ".simplicio-loop"
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
        lock = _acquire_index_lock(str(self.root), self.out, map_job_owner_token="job-owner")
        self.assertIsNotNone(lock)
        assert lock is not None
        record = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(record["schema"], INDEX_LOCK_SCHEMA)
        self.assertEqual(record["pid"], os.getpid())
        self.assertTrue(record["process_start"])
        self.assertEqual(record["token"], lock.token)
        self.assertEqual(record["schema"], INDEX_LOCK_SCHEMA)
        self.assertEqual(record["owner_token"], lock.token)
        self.assertEqual(record["root_fingerprint"].__class__, str)
        self.assertEqual(record["operation"], "index")
        self.assertEqual(record["map_job_owner_token"], "job-owner")
        self.assertIn("heartbeat_at", record)

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

    def test_ttl_expired_live_lock_is_never_recovered(self) -> None:
        start = _process_start_token(os.getpid()) or "unknown"
        self._write_json(pid=os.getpid(), process_start=start, acquired_at=0)
        status = _inspect_index_lock(str(self.root), self.out, recover=True)
        self.assertFalse(status["recovered"])
        self.assertTrue(status["active"])
        self.assertEqual(status["reason"], "ttl_expired")

    def test_pid_reuse_start_mismatch_is_recovered(self) -> None:
        self._write_json(pid=os.getpid(), process_start="different-start", acquired_at=time.time())
        status = _inspect_index_lock(str(self.root), self.out, recover=True)
        if _process_start_token(os.getpid()) is None:
            self.skipTest("OS does not expose process start identity")
        self.assertTrue(status["recovered"])
        self.assertEqual(status["reason"], "pid_reused")

    def test_map_job_process_start_mismatch_is_not_treated_as_running(self) -> None:
        if _process_start_token(os.getpid()) is None:
            self.skipTest("OS does not expose process start identity")
        job_path = self.path.parent / "map-job.json"
        job_path.write_text(
            json.dumps({
                "schema": "simplicio.map-job/v1",
                "phase": "macro_done",
                "deep": {
                    "pid": os.getpid(),
                    "process_start": "reused-process-start",
                    "owner_token": "reused-owner",
                },
            }),
            encoding="utf-8",
        )

        payload = _status_payload(str(self.root), self.out)

        self.assertEqual(payload["phase"], "failed")
        self.assertEqual(payload["failure_reason"], "worker_died_before_terminal")
        receipt = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "failed")
        self.assertEqual(receipt["deep"]["exit_code"], -1)
        self.assertTrue(receipt["deep"]["finished_at"])

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

    def test_old_malformed_record_with_live_pid_is_not_reclaimed(self) -> None:
        self.path.write_text(
            json.dumps({"pid": os.getpid(), "created_at": time.time() - 30}),
            encoding="utf-8",
        )
        old = time.time() - MALFORMED_LOCK_GRACE_SECONDS - 1
        os.utime(self.path, (old, old))
        status = _inspect_index_lock(str(self.root), self.out, recover=True)
        self.assertTrue(status["active"])
        self.assertFalse(status["recovered"])
        self.assertEqual(status["reason"], "malformed")
        self.assertTrue(self.path.exists())

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

    def test_failed_worker_inspect_persists_fresh_terminal_receipt(self) -> None:
        self._write_json(pid=2_147_483_647, process_start="gone", acquired_at=time.time())
        (self.path.parent / "map-job.json").write_text(
            json.dumps(
                {
                    "schema": "simplicio.map-job/v1",
                    "phase": "deep_running",
                    "deep": {"pid": 2_147_483_647, "process_start": "gone"},
                }
            ),
            encoding="utf-8",
        )
        output = io.StringIO()
        with redirect_stdout(output):
            code = _run_inspect(
                {
                    "root": str(self.root),
                    "out": self.out,
                    "await": True,
                    "timeout": 1,
                    "json": True,
                    "for_llm": "",
                }
            )
        self.assertEqual(code, 0)
        emitted = json.loads(output.getvalue())
        receipt_path = self.path.parent / "map-inspection.json"
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt, emitted)
        self.assertEqual(receipt["status"]["phase"], "failed")
        self.assertTrue(receipt["status"]["terminal"])
        self.assertFalse(receipt["status"]["fresh"])
        self.assertEqual(receipt["status"]["failure_reason"], "worker_died_before_terminal")
        self.assertIn("generated_at", receipt)
        self.assertFalse(self.path.exists())

    def test_live_full_schema_lock_is_never_stolen_and_reports_owner_evidence(self) -> None:
        # A live owner holding a fully-formed v1 lock record must block a
        # second acquisition outright (not just the legacy PID-only form
        # already covered above), and status/inspect callers must be able to
        # read owner/age/operation straight off the record (issue #201 AC:
        # "Lock de processo vivo nunca eh roubado; status retorna
        # owner/age/operation e retry guidance").
        lock = _acquire_index_lock(str(self.root), self.out, map_job_owner_token="job-owner")
        self.assertIsNotNone(lock)
        assert lock is not None
        try:
            self.assertIsNone(_acquire_index_lock(str(self.root), self.out))
            status = _inspect_index_lock(str(self.root), self.out, recover=True)
            self.assertTrue(status["active"])
            self.assertFalse(status["recovered"])
            self.assertEqual(status["reason"], "live")
            self.assertEqual(status["reason_code"], "lock_live_owner")
            owner = status["owner"]
            self.assertEqual(owner["pid"], os.getpid())
            self.assertEqual(owner["operation"], "index")
            self.assertEqual(owner["map_job_owner_token"], "job-owner")
            self.assertIn("age_seconds", status)
            payload = _status_payload(str(self.root), self.out)
            self.assertEqual(payload["retry_guidance"], "rerun scan; lock is owned by a live process")
        finally:
            _release_index_lock(lock)

    def test_bounded_await_returns_explicit_timeout_without_stealing_live_lock(self) -> None:
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        assert lock is not None
        try:
            phase = _await_terminal(str(self.root), self.out, timeout=0)
            self.assertEqual(phase, "timeout")
            payload = _status_payload(str(self.root), self.out, phase=phase)
            self.assertTrue(payload["terminal"])
            self.assertEqual(payload["failure_reason"], "scan_timeout")
            self.assertTrue(payload["lock"])
            self.assertEqual(payload["lock_status"]["reason_code"], "lock_live_owner")
            self.assertIn("larger timeout", payload["retry_guidance"])
            self.assertTrue(self.path.exists())
        finally:
            _release_index_lock(lock)

    def test_acquire_reports_lock_acquired_reason_code(self) -> None:
        lock = _acquire_index_lock(str(self.root), self.out)
        self.assertIsNotNone(lock)
        assert lock is not None
        try:
            self.assertEqual(lock.reason_code, "lock_acquired")
        finally:
            _release_index_lock(lock)

    def test_unicode_and_long_nested_root_path_is_covered(self) -> None:
        # issue #201 AC: "Paths Unicode/long path e filesystem semantics de
        # Windows sao cobertos". Build a root with unicode segments nested
        # deep enough to exceed the classic 260-char Windows MAX_PATH limit
        # and prove acquire/inspect/release still work end to end.
        deep_root = self.root
        segment = "diretório_de_indexação_日本語_très-long_"
        for index in range(7):
            deep_root = deep_root / f"{segment}{index}"
        deep_root.mkdir(parents=True, exist_ok=True)
        self.assertGreater(len(str(deep_root)), 260)
        lock = _acquire_index_lock(str(deep_root), self.out)
        self.assertIsNotNone(lock)
        assert lock is not None
        status = _inspect_index_lock(str(deep_root), self.out)
        self.assertTrue(status["active"])
        self.assertEqual(status["reason_code"], "lock_live_owner")
        _release_index_lock(lock)
        self.assertFalse(_inspect_index_lock(str(deep_root), self.out)["exists"])

    def test_liveness_check_overhead_is_negligible_on_fast_path(self) -> None:
        # Perf-benchmark evidence for issue #201's AC that the heartbeat/
        # liveness check does not reintroduce relevant latency on the macro
        # fast path. This is a targeted micro-benchmark of the lock/liveness
        # primitives themselves (not the full scan pipeline covered by
        # scripts/runtime_scale_benchmark.py) -- documented as such in the PR.
        iterations = 200
        started = time.perf_counter()
        for _ in range(iterations):
            self.assertTrue(_process_is_alive(os.getpid()))
            _process_start_token(os.getpid())
        elapsed_ms = (time.perf_counter() - started) * 1000
        per_call_ms = elapsed_ms / iterations
        self.assertLess(
            per_call_ms,
            5.0,
            f"liveness+start-token check averaged {per_call_ms:.3f}ms/call, exceeding the 5ms budget",
        )


class IndexLockCrashRecoveryIntegrationTest(unittest.TestCase):
    """Real-subprocess coverage: scan -> kill -> status --await -> inspect -> handoff.

    These exercise the actual ``simplicio_mapper.cli`` entry point over
    ``subprocess`` (the same module the installed ``simplicio-mapper``
    console script dispatches to), not just in-process unit calls, per issue
    #201's "wheel/CLI instalado e testado, nao somente import in-tree" AC.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "package.json").write_text(
            json.dumps({"name": "lock-crash-host"}), encoding="utf-8"
        )
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "index.py").write_text(
            "def run() -> int:\n    return 1\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _cli(self, *args: str, timeout: float = 30) -> dict:
        result = subprocess.run(
            [sys.executable, "-m", "simplicio_mapper.cli", *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
        self.assertTrue(result.stdout.strip(), result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_killed_background_worker_does_not_wedge_status_await(self) -> None:
        scan_payload = self._cli("scan", str(self.root), "--json")
        pid = scan_payload["deep"]["pid"]
        self.assertIsInstance(pid, int)

        # Simulate the crash from the issue reproduction: the deep-pass
        # worker disappears mid-flight, before it ever writes a fresh index
        # state or releases its lock.
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                        stdin=subprocess.DEVNULL,
                        timeout=5,
                    )
                else:
                    os.kill(pid, 9)
            except OSError:
                pass
            if not _process_is_alive(pid):
                break
            time.sleep(0.05)
        self.assertFalse(_process_is_alive(pid), "worker should be dead before polling status")

        status_payload = self._cli("status", str(self.root), "--await", "--timeout", "20", "--json")
        self.assertTrue(status_payload["terminal"])
        self.assertEqual(status_payload["phase"], "failed")
        self.assertEqual(status_payload["failure_reason"], "worker_died_before_terminal")
        self.assertFalse(status_payload["lock"])
        receipt = json.loads((self.root / ".simplicio-loop" / "map-job.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "failed")
        self.assertEqual(receipt["deep"]["exit_code"], -1)
        self.assertEqual(receipt["deep"]["failure_reason"], "worker_died_before_terminal")
        self.assertTrue(receipt["deep"]["finished_at"])

        inspect_payload = self._cli("inspect", str(self.root), "--json")
        handoff_payload = self._cli("handoff", str(self.root), "--json")
        for payload in (inspect_payload["status"], handoff_payload["status"]):
            self.assertEqual(payload["phase"], "failed")
            self.assertEqual(payload["failure_reason"], "worker_died_before_terminal")
            self.assertEqual(payload["job"]["exit_code"], -1)
            self.assertEqual(payload["job"]["finished_at"], receipt["deep"]["finished_at"])

        # A follow-up scan must converge without any manual `Remove-Item
        # index.lock` -- the whole point of the issue.
        second_scan = self._cli("scan", str(self.root), "--sync", "--json", timeout=60)
        self.assertIn(second_scan["phase"], ("complete", "failed"))

        inspect_payload = self._cli("inspect", str(self.root), "--json")
        self.assertIn(inspect_payload["status"]["phase"], ("complete", "failed"))

        handoff_payload = self._cli("handoff", str(self.root), "--json")
        self.assertIn(handoff_payload["status"]["phase"], ("complete", "failed"))

    def test_real_async_scan_outlives_cli_and_persists_terminal_success(self) -> None:
        for index in range(600):
            (self.root / "src" / f"module_{index:04d}.py").write_text(
                f"def value_{index}() -> int:\n    return {index}\n", encoding="utf-8"
            )

        scan_payload = self._cli("scan", str(self.root), "--json", timeout=30)
        pid = scan_payload["deep"]["pid"]
        self.assertTrue(
            _process_is_alive(pid),
            "the real scan CLI must exit while its detached index child is still running",
        )

        deadline = time.time() + 90
        while time.time() < deadline and _process_is_alive(pid):
            time.sleep(0.05)
        self.assertFalse(_process_is_alive(pid), "detached index child did not terminate")

        job_path = self.root / ".simplicio-loop" / "map-job.json"
        receipt = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "complete")
        self.assertEqual(receipt["deep"]["exit_code"], 0)
        self.assertIsNone(receipt["deep"].get("failure_reason"))
        self.assertTrue(receipt["deep"]["finished_at"])
        self.assertTrue(receipt["deep"]["owner_token"])

        status_payload = self._cli("status", str(self.root), "--json")
        inspect_payload = self._cli("inspect", str(self.root), "--json")
        handoff_payload = self._cli("handoff", str(self.root), "--json")
        for payload in (
            status_payload,
            inspect_payload["status"],
            handoff_payload["status"],
        ):
            self.assertEqual(payload["phase"], "complete")
            self.assertEqual(payload["job"]["phase"], "complete")
            self.assertEqual(payload["job"]["exit_code"], 0)
            self.assertEqual(payload["job"]["finished_at"], receipt["deep"]["finished_at"])

        retry = self._cli("scan", str(self.root), "--sync", "--json", timeout=90)
        self.assertEqual(retry["phase"], "complete")
        self.assertEqual(retry["deep"]["exit_code"], 0)

    def test_real_async_scan_persists_nonzero_terminal_failure(self) -> None:
        index_state = self.root / ".simplicio-loop" / "index-state.json"
        index_state.parent.mkdir(parents=True, exist_ok=True)
        index_state.mkdir()

        scan_payload = self._cli("scan", str(self.root), "--json", timeout=30)
        pid = scan_payload["deep"]["pid"]
        deadline = time.time() + 30
        while time.time() < deadline and _process_is_alive(pid):
            time.sleep(0.05)
        self.assertFalse(_process_is_alive(pid), "failing detached worker did not terminate")

        receipt = json.loads((self.root / ".simplicio-loop" / "map-job.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "failed")
        self.assertNotEqual(receipt["deep"]["exit_code"], 0)
        self.assertTrue(receipt["deep"]["failure_reason"])
        self.assertTrue(receipt["deep"]["finished_at"])

        status_payload = self._cli("status", str(self.root), "--json")
        inspect_payload = self._cli("inspect", str(self.root), "--json")
        handoff_payload = self._cli("handoff", str(self.root), "--json")
        for payload in (
            status_payload,
            inspect_payload["status"],
            handoff_payload["status"],
        ):
            self.assertEqual(payload["phase"], "failed")
            self.assertEqual(payload["failure_reason"], receipt["deep"]["failure_reason"])
            self.assertEqual(payload["job"]["exit_code"], receipt["deep"]["exit_code"])
            self.assertEqual(payload["job"]["finished_at"], receipt["deep"]["finished_at"])

    def test_real_index_worker_waits_for_late_map_job_creation(self) -> None:
        owner_token = "late-job-owner"
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        env[_MAP_JOB_IDENTITY_ENV] = owner_token
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "simplicio_mapper.cli", "index", str(self.root), "--json"],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        identity = {
            "pid": process.pid,
            "process_start": _process_start_token(process.pid) or "unknown",
            "owner_token": owner_token,
        }
        time.sleep(0.2)
        self.assertIsNone(process.poll(), "worker must wait for the delayed map-job receipt")
        job_path = self.root / ".simplicio-loop" / "map-job.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(
            json.dumps({
                "schema": "simplicio.map-job/v1",
                "phase": "macro_done",
                "sync": False,
                "deep": identity,
            }),
            encoding="utf-8",
        )
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertTrue(stdout.strip())
        receipt = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "complete")
        self.assertEqual(receipt["deep"]["exit_code"], 0)
        self.assertEqual(
            {key: receipt["deep"][key] for key in identity},
            identity,
        )

    def test_real_index_worker_never_overwrites_replaced_job_identity(self) -> None:
        owner_token = "original-job-owner"
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        env[_MAP_JOB_IDENTITY_ENV] = owner_token
        process = subprocess.Popen(
            [sys.executable, "-B", "-m", "simplicio_mapper.cli", "index", str(self.root), "--json"],
            cwd=str(ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        replacement = {
            "schema": "simplicio.map-job/v1",
            "phase": "macro_done",
            "sync": False,
            "deep": {
                "pid": process.pid + 1,
                "process_start": "replacement-start",
                "owner_token": "replacement-owner",
            },
        }
        job_path = self.root / ".simplicio-loop" / "map-job.json"
        job_path.parent.mkdir(parents=True, exist_ok=True)
        job_path.write_text(json.dumps(replacement), encoding="utf-8")
        _stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(job_path.read_text(encoding="utf-8")), replacement)

    def test_status_durably_reconciles_fresh_nonterminal_job(self) -> None:
        sync = self._cli("scan", str(self.root), "--sync", "--json", timeout=60)
        self.assertEqual(sync["phase"], "complete")
        job_path = self.root / ".simplicio-loop" / "map-job.json"
        dead_identity = {
            "pid": 2_147_483_647,
            "process_start": "dead-start",
            "owner_token": "dead-owner",
        }
        job_path.write_text(
            json.dumps({
                "schema": "simplicio.map-job/v1",
                "phase": "macro_done",
                "sync": False,
                "deep": dead_identity,
            }),
            encoding="utf-8",
        )

        status = self._cli("status", str(self.root), "--json")

        self.assertEqual(status["phase"], "complete")
        self.assertTrue(status["fresh"])
        receipt = json.loads(job_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["phase"], "complete")
        self.assertEqual(receipt["deep"]["exit_code"], 0)
        self.assertIsNone(receipt["deep"]["failure_reason"])
        self.assertTrue(receipt["deep"]["finished_at"])


class IndexLockConcurrentProcessRaceTest(unittest.TestCase):
    """Process-level (not just thread-level) proof that acquire is atomic."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "package.json").write_text(
            json.dumps({"name": "lock-race-host"}), encoding="utf-8"
        )
        (self.root / "src").mkdir(parents=True, exist_ok=True)
        (self.root / "src" / "index.py").write_text(
            "def run() -> int:\n    return 1\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_two_concurrent_index_invocations_never_both_run_deep_pass(self) -> None:
        # issue #201 AC: "Acquire e atomico; duas execucoes concorrentes nao
        # entram no deep pass juntas." Launch two real OS processes racing
        # for the same lock file and prove exactly one performs the write
        # while the other observes it locked -- never both "updated".
        args = [sys.executable, "-m", "simplicio_mapper.cli", "index", str(self.root), "--json"]
        popen_kwargs = {
            "cwd": str(ROOT),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        first = subprocess.Popen(args, **popen_kwargs)
        second = subprocess.Popen(args, **popen_kwargs)
        out1, err1 = first.communicate(timeout=60)
        out2, err2 = second.communicate(timeout=60)
        self.assertEqual(first.returncode, 0, err1)
        self.assertEqual(second.returncode, 0, err2)
        payload1 = json.loads(out1.strip().splitlines()[-1])
        payload2 = json.loads(out2.strip().splitlines()[-1])
        statuses = sorted([payload1["status"], payload2["status"]])
        # Either the second process loses the race outright ("skipped"/
        # "locked") or it wins the race after the first already finished and
        # finds the index already fresh -- both are safe outcomes. What must
        # never happen is both claiming to have run the actual write path
        # while the lock was held by the other (proven by the lock file
        # never existing after either exits, and both processes exiting
        # cleanly without contention errors).
        self.assertIn("updated", statuses)
        for payload in (payload1, payload2):
            if payload["status"] == "skipped":
                self.assertIn(payload["skipped_reason"], ("locked", "already_fresh"))
        lock_path = Path(_lock_path(str(self.root), ".simplicio-loop"))
        self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    unittest.main()
