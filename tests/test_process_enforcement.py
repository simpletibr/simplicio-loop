"""Real tests for the #516 supervisor observability/enforcement slice.

These tests spawn actual OS subprocesses (never mocked) to prove: a process started outside the
supervisor is flagged by the detector, a process started through the supervisor is not, the
default (opt-in-off) enforcement mode never signals anything, an opt-in-on enforcement pass can
terminate a real flagged process, and the circuit breaker trips on repeated spawn failures while
still completing subsequent work via the standalone fallback path.

Safety note for this shared, multi-agent host: ``enforce(..., enabled=True)`` is only ever
called here with a list *filtered down to a canary pid this test itself spawned* -- never with
the raw, unfiltered output of a host-wide ``detect_unsupervised`` scan, which could otherwise
match and signal unrelated legitimate processes belonging to other concurrent agents/worktrees.
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import pytest
from pathlib import Path
from typing import Any

from simplicio_loop import process_enforcement as process_enforcement_module
from simplicio_loop.process_enforcement import (
    CircuitBreaker,
    ProcessRegistry,
    SupervisedProcessAdapter,
    append_event,
    detect_unsupervised,
    enforce,
    enforcement_enabled,
    is_simplicio_cmdline,
    read_events,
    run_guarded,
)
from simplicio_loop.process_supervisor import ProcessSpec

MARKER = "simplicio-mapper"  # matches SIMPLICIO_SIGNATURES, harmless extra argv token


def _concurrent_registry_register(path: str, gate: Any, lease_id: str) -> None:
    """Child-process target for the registry's real interprocess-lock test."""
    gate.wait()
    ProcessRegistry(Path(path)).register(
        os.getpid(), lease_id=lease_id, spec_hash="concurrent", argv=["worker"],
    )


def _wait_visible(pid: int, *, timeout: float = 15.0) -> None:
    """Block until the production scanner sees ``pid`` after the child's exec transition."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(record.pid == pid for record in process_enforcement_module.scan_host_processes()):
            return
        time.sleep(0.02)
    raise AssertionError("process %d never became visible to the production scanner" % pid)


def _spawn_marker_canary(sleep_seconds: float = 2.5) -> subprocess.Popen:
    """A real subprocess that bypasses the supervisor entirely, but whose cmdline still matches
    the ecosystem signature (via the extra ``MARKER`` positional argv token, which ``python -c``
    ignores at runtime -- it only affects what ``sys.argv`` would be inside the script)."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(%r)" % sleep_seconds, MARKER],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    _wait_visible(proc.pid)
    return proc


def _wait_reaped(proc: subprocess.Popen, *, timeout: float = 15.0) -> bool:
    """True once this test's own child ``proc`` has actually exited, reaping it along the way
    so it is not left as a zombie waiting on a ``wait()`` this test never calls."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


def test_signature_matching() -> None:
    assert is_simplicio_cmdline(["python3", "-m", "simplicio_loop.cli", "status"])
    assert is_simplicio_cmdline(["simplicio-mapper", "scan"])
    assert not is_simplicio_cmdline(["python3", "-c", "print(1)"])
    assert not is_simplicio_cmdline(["bash", "-c", "ls"])


def test_detector_does_not_suppress_a_reused_pid_with_a_different_identity(monkeypatch, tmp_path) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    monkeypatch.setattr(
        registry, "active", lambda: {4242: {"process_identity": "linux-proc:4242:starttime:1"}},
    )
    monkeypatch.setattr(
        process_enforcement_module, "scan_host_processes",
        lambda: [process_enforcement_module.ProcessRecord(
            4242, ["python", "-m", "simplicio_loop.cli"],
            "linux-proc:4242:starttime:2",
        )],
    )
    assert [record.pid for record in detect_unsupervised(registry)] == [4242]


def test_detector_suppresses_only_the_same_registered_identity(monkeypatch, tmp_path) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    monkeypatch.setattr(
        registry, "active", lambda: {4242: {"process_identity": "linux-proc:4242:starttime:1"}},
    )
    monkeypatch.setattr(
        process_enforcement_module, "scan_host_processes",
        lambda: [process_enforcement_module.ProcessRecord(
            4242, ["python", "-m", "simplicio_loop.cli"],
            "linux-proc:4242:starttime:1",
        )],
    )
    assert detect_unsupervised(registry) == []


def test_proc_scan_uses_pid_at_callers_namespace_depth_for_child_target(tmp_path) -> None:
    caller = tmp_path / str(os.getpid())
    caller.mkdir()
    (caller / "status").write_text("NSpid:\t1\t42\n", encoding="utf-8")
    proc_entry = tmp_path / "42000"
    proc_entry.mkdir()
    (proc_entry / "cmdline").write_bytes(b"python\x00simplicio-mapper\x00")
    (proc_entry / "status").write_text(
        "Name:\tpython\nNSpid:\t1\t37\t9\n", encoding="utf-8",
    )

    assert process_enforcement_module._scan_proc(tmp_path) == [
        process_enforcement_module.ProcessRecord(37, ["python", "simplicio-mapper"]),
    ]


def test_proc_scan_omits_target_without_callers_namespace_level(tmp_path) -> None:
    caller = tmp_path / str(os.getpid())
    caller.mkdir()
    (caller / "status").write_text("NSpid:\t1\t42\n", encoding="utf-8")
    proc_entry = tmp_path / "42000"
    proc_entry.mkdir()
    (proc_entry / "cmdline").write_bytes(b"python\x00simplicio-mapper\x00")
    (proc_entry / "status").write_text("NSpid:\t1\n", encoding="utf-8")

    assert process_enforcement_module._scan_proc(tmp_path) == []


def test_proc_scan_omits_when_nspid_metadata_is_absent(tmp_path) -> None:
    caller = tmp_path / str(os.getpid())
    caller.mkdir()
    (caller / "status").write_text("NSpid:\t1\n", encoding="utf-8")
    proc_entry = tmp_path / "42000"
    proc_entry.mkdir()
    (proc_entry / "cmdline").write_bytes(b"python\x00simplicio-mapper\x00")
    (proc_entry / "status").write_text("Name:\tpython\n", encoding="utf-8")

    assert process_enforcement_module._scan_proc(tmp_path) == []


def test_proc_scan_omits_when_callers_nspid_is_missing(tmp_path) -> None:
    proc_entry = tmp_path / "42000"
    proc_entry.mkdir()
    (proc_entry / "cmdline").write_bytes(b"python\x00simplicio-mapper\x00")
    (proc_entry / "status").write_text("NSpid:\t1\n", encoding="utf-8")

    assert process_enforcement_module._scan_proc(tmp_path) == []


@pytest.mark.skipif(sys.platform == "darwin", reason="process registration timing is Linux-specific")
def test_detector_flags_unsupervised_but_not_supervised(tmp_path) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")

    # 1) A process launched OUTSIDE the supervisor: no registry entry at all.
    outside = _spawn_marker_canary()
    try:
        flagged_pids = {record.pid for record in detect_unsupervised(registry)}
        assert outside.pid in flagged_pids, "unsupervised marker process must be flagged"
    finally:
        outside.terminate()
        outside.wait(timeout=5)

    # 2) The same kind of process, but launched PROPERLY through the supervisor: while it is
    #    still running, its pid must be registered and therefore NOT flagged.
    adapter = SupervisedProcessAdapter(registry=registry)
    spec = ProcessSpec((sys.executable, "-c", "import time; time.sleep(1.2)", MARKER))

    async def scenario() -> None:
        task = asyncio.ensure_future(adapter.run(spec))
        # Give the child a moment to spawn and register before we scan.
        deadline = time.monotonic() + 15.0
        supervised_pid = None
        while time.monotonic() < deadline and not registry.active():
            await asyncio.sleep(0.02)
        active = registry.active()
        assert active, "supervised process should have registered a pid before completing"
        supervised_pid = next(iter(active))
        flagged_pids = {record.pid for record in detect_unsupervised(registry)}
        assert supervised_pid not in flagged_pids, "supervised process must not be flagged"
        await task

    asyncio.run(scenario())


def test_enforcement_default_off_observes_only_and_kills_nothing(tmp_path) -> None:
    assert enforcement_enabled() is False, "enforcement must default to opt-in OFF"
    canary = _spawn_marker_canary()
    try:
        registry = ProcessRegistry(tmp_path / "registry.json")
        flagged = [r for r in detect_unsupervised(registry) if r.pid == canary.pid]
        assert flagged, "the canary should be detected as flagged"
        actions = enforce(flagged, enabled=False)
        assert all(action["action"] == "observed_only" for action in actions)
        # Real proof nothing was killed: the process is still alive.
        assert canary.poll() is None, "enforcement-off must never kill a flagged process"
    finally:
        canary.terminate()
        canary.wait(timeout=5)


@pytest.mark.skipif(sys.platform == "darwin", reason="process signaling semantics are Linux-specific")
def test_enforcement_opt_in_terminates_a_flagged_process(tmp_path) -> None:
    canary = _spawn_marker_canary(sleep_seconds=10.0)
    try:
        registry = ProcessRegistry(tmp_path / "registry.json")
        # Scope strictly to the canary this test owns -- never act on the unfiltered host-wide
        # scan on this shared, multi-agent machine.
        flagged = [r for r in detect_unsupervised(registry) if r.pid == canary.pid]
        assert flagged
        actions = enforce(flagged, enabled=True)
        assert actions[0]["action"] == "signaled"
        assert _wait_reaped(canary), "opt-in enforcement must actually terminate the process"
    finally:
        if canary.poll() is None:
            canary.terminate()
        canary.wait(timeout=5)


def test_circuit_breaker_trips_and_standalone_fallback_still_completes_work() -> None:
    async def scenario() -> None:
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=100.0)
        bad_spec = ProcessSpec(("simplicio-no-such-executable-516",))
        good_spec = ProcessSpec((sys.executable, "-c", "print('ok')"))

        first = await run_guarded(bad_spec, breaker=breaker)
        assert first["mode"] == "supervised"
        assert first["result"].error_code == "executable_not_found"
        assert breaker.state == "closed", "one failure must not trip a threshold-of-2 breaker"

        second = await run_guarded(bad_spec, breaker=breaker)
        assert second["mode"] == "supervised"
        assert breaker.state == "open", "two consecutive spawn failures must trip the breaker"

        third = await run_guarded(good_spec, breaker=breaker)
        assert third["mode"] == "standalone_fallback"
        assert third["result"].returncode == 0
        assert third["result"].stdout.strip() == "ok"

    asyncio.run(scenario())


def test_circuit_breaker_persists_across_load_save(tmp_path) -> None:
    path = tmp_path / "breaker.json"
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=100.0)
    breaker.record_failure("spawn_error")
    assert breaker.state == "open"
    breaker.save(path)

    reloaded = CircuitBreaker.load(path)
    assert reloaded.state == "open"
    assert reloaded.trip_reason == "spawn_error"


def test_registry_prunes_dead_pids(tmp_path) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=5)
    registry.register(proc.pid, lease_id="lease-1", spec_hash="hash-1", argv=["x"])
    # The pid has already exited; prune_dead (called by active()) must drop it rather than
    # report a stale/possibly-reused pid as still supervised.
    assert proc.pid not in registry.active()


def test_registry_register_keeps_all_concurrent_process_updates(tmp_path) -> None:
    """A coordinated burst must not lose JSON read-modify-write updates."""
    if os.name == "nt":
        # The production implementation has a Windows lock path, but this
        # high-contention test is the Linux contract requested by #623.
        return
    path = tmp_path / "registry.json"
    context = multiprocessing.get_context("fork")
    gate = context.Event()
    workers = [
        context.Process(
            target=_concurrent_registry_register,
            args=(str(path), gate, "lease-%d" % index),
        )
        for index in range(40)
    ]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        worker.join(timeout=15)
        assert worker.exitcode == 0

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert len(raw["processes"]) == len(workers)
    assert {record["lease_id"] for record in raw["processes"].values()} == {
        "lease-%d" % index for index in range(len(workers))
    }


def test_registry_late_unregister_cannot_remove_reused_pid_registration(tmp_path, monkeypatch) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    identities = {12345: "start-a"}
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: identities.get(pid))

    old_identity = registry.register(12345, lease_id="old", spec_hash="h", argv=["old"])
    identities[12345] = "start-b"
    new_identity = registry.register(12345, lease_id="new", spec_hash="h", argv=["new"])

    assert registry.unregister(
        12345, lease_id="old", process_identity=old_identity,
    ) is False
    assert registry.unregister(12345) is False
    raw = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    assert raw["processes"]["12345"]["lease_id"] == "new"
    assert raw["processes"]["12345"]["process_identity"] == new_identity


def test_registry_prunes_pid_reused_with_different_start_identity(tmp_path, monkeypatch) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    identities = {12345: "start-a"}
    monkeypatch.setattr(process_enforcement_module, "_pid_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: identities.get(pid))
    registry.register(12345, lease_id="lease-1", spec_hash="hash-1", argv=["x"])
    identities[12345] = "start-b"  # same PID, unrelated later process

    assert registry.active() == {}


def test_registry_terminate_refuses_reused_pid(tmp_path, monkeypatch) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    identities = {23456: "start-a"}
    monkeypatch.setattr(process_enforcement_module, "_pid_alive", lambda pid: pid == 23456)
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: identities.get(pid))
    registry.register(23456, lease_id="lease-1", spec_hash="hash-1", argv=["x"])
    identities[23456] = "start-b"
    called = []
    monkeypatch.setattr(process_enforcement_module, "kill_process_tree", lambda pid, sig: called.append(pid))

    assert registry.terminate("lease-1") == {
        "found": False, "pid": None, "lease_id": "lease-1", "killed": False,
    }
    assert called == []


def test_registry_terminate_forwards_explicit_dedicated_group_evidence(tmp_path, monkeypatch) -> None:
    registry = ProcessRegistry(tmp_path / "registry.json")
    monkeypatch.setattr(process_enforcement_module, "_pid_alive", lambda pid: pid == 23457)
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda _pid: "start-a")
    registry.register(
        23457, lease_id="lease-group", spec_hash="hash-1", argv=["x"],
        dedicated_process_group=True,
    )
    calls = []

    def kill(pid, *, sig, expected_identity, dedicated_process_group):
        calls.append((pid, sig, expected_identity, dedicated_process_group))
        return True

    monkeypatch.setattr(process_enforcement_module, "kill_process_tree", kill)
    result = registry.terminate("lease-group", sig=signal.SIGTERM)
    assert result["killed"] is True
    assert calls == [(23457, signal.SIGTERM, "start-a", True)]


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX pidfd/process-group primitives')
def test_unsupervised_target_never_kills_group_even_when_pid_is_group_leader(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(process_enforcement_module, "_linux_pidfd_open", lambda pid: 99)
    monkeypatch.setattr(process_enforcement_module.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(process_enforcement_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(process_enforcement_module.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    monkeypatch.setattr(
        process_enforcement_module, "_linux_pidfd_send_signal",
        lambda pidfd, sig: calls.append(("pidfd", pidfd, sig)) or True,
    )

    assert process_enforcement_module.kill_process_tree(123, sig=signal.SIGTERM) is True
    assert calls == [("pidfd", 99, signal.SIGTERM), ("close", 99)]


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX pidfd/process-group primitives')
def test_supervised_dedicated_group_evidence_allows_group_signal(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(process_enforcement_module, "_linux_pidfd_open", lambda pid: 99)
    monkeypatch.setattr(process_enforcement_module.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(process_enforcement_module.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(
        process_enforcement_module.os, "killpg",
        lambda pgid, sig: calls.append(("killpg", pgid, sig)),
    )
    monkeypatch.setattr(
        process_enforcement_module, "_linux_pidfd_send_signal",
        lambda *args: calls.append(("pidfd",) + args) or True,
    )
    assert process_enforcement_module.kill_process_tree(
        123, sig=signal.SIGTERM, dedicated_process_group=True,
    ) is True
    assert calls == [("killpg", 123, signal.SIGTERM), ("close", 99)]


@pytest.mark.skipif(os.name == 'nt', reason='requires POSIX pidfd/process-group primitives')
def test_kill_process_tree_revalidates_identity_after_pidfd_pinning(monkeypatch) -> None:
    """A PID recycled between registry validation and pidfd acquisition is never signalled."""
    calls = []
    monkeypatch.setattr(process_enforcement_module, "_linux_pidfd_open", lambda pid: 99)
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: "new-start")
    monkeypatch.setattr(process_enforcement_module.os, "close", lambda fd: calls.append(("close", fd)))
    monkeypatch.setattr(process_enforcement_module.os, "killpg", lambda *args: calls.append(args))
    monkeypatch.setattr(
        process_enforcement_module, "_linux_pidfd_send_signal",
        lambda *args: calls.append(args) or True,
    )

    assert process_enforcement_module.kill_process_tree(
        123, sig=signal.SIGTERM, expected_identity="old-start",
    ) is False
    assert calls == [("close", 99)]


def test_enforce_fails_closed_when_process_cannot_be_pinned(monkeypatch) -> None:
    monkeypatch.setattr(
        process_enforcement_module,
        "kill_process_tree",
        lambda pid, sig, expected_identity: False,
    )

    actions = enforce(
        [
            process_enforcement_module.ProcessRecord(
                123, ["simplicio-mapper"], "linux-proc:123:starttime:1",
            ),
        ],
        enabled=True,
    )

    assert actions[0]["action"] == "signal_failed"


def test_enforce_refuses_identityless_record_without_calling_killer(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        process_enforcement_module,
        "kill_process_tree",
        lambda *args, **kwargs: calls.append((args, kwargs)) or True,
    )

    actions = enforce(
        [process_enforcement_module.ProcessRecord(123, ["simplicio-mapper"])], enabled=True,
    )

    assert actions[0]["action"] == "signal_failed"
    assert calls == []


def test_proc_scan_omits_pid_reused_while_collecting_cmdline(tmp_path, monkeypatch) -> None:
    caller = tmp_path / str(os.getpid())
    caller.mkdir()
    (caller / "status").write_text("NSpid:\\t1\\n", encoding="utf-8")
    proc_entry = tmp_path / "123"
    proc_entry.mkdir()
    (proc_entry / "cmdline").write_bytes(b"simplicio-mapper\\x00")
    (proc_entry / "status").write_text("NSpid:\\t123\\n", encoding="utf-8")
    identities = iter(["linux-proc:123:starttime:old", "linux-proc:123:starttime:new"])
    monkeypatch.setattr(
        process_enforcement_module,
        "_proc_entry_identity",
        lambda entry: next(identities) if entry.name == "123" else None,
    )

    assert process_enforcement_module._scan_proc(tmp_path) == []


def test_windows_taskkill_failure_is_not_reported_as_success(monkeypatch) -> None:
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(
        process_enforcement_module,
        "os",
        os_with_name(process_enforcement_module.os, "nt"),
    )
    monkeypatch.setattr(process_enforcement_module, "_windows_open_process", lambda pid, access: 77)
    monkeypatch.setattr(process_enforcement_module, "_windows_close_handle", lambda handle: None)
    monkeypatch.setattr(
        process_enforcement_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1),
    )
    assert process_enforcement_module.kill_process_tree(123) is False


@pytest.mark.skipif(os.name != "nt", reason="requires CommandLineToArgvW")
def test_windows_command_line_parser_preserves_quoted_arguments() -> None:
    assert process_enforcement_module._split_windows_command_line(
        '"C:\\Program Files\\Python\\python.exe" -c "print(1 + 2)"'
    ) == ["C:\\Program Files\\Python\\python.exe", "-c", "print(1 + 2)"]


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process metadata")
def test_windows_scanner_pins_identity_and_preserves_argv(monkeypatch) -> None:
    class Process:
        info = {"pid": 123, "cmdline": ["simplicio-mapper", "argument with spaces"]}

    import psutil
    monkeypatch.setattr(psutil, "process_iter", lambda fields: [Process()])
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: "windows-creation:1")

    assert process_enforcement_module._scan_windows_processes() == [
        process_enforcement_module.ProcessRecord(
            123, ["simplicio-mapper", "argument with spaces"], "windows-creation:1",
        )
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process metadata")
def test_windows_scanner_cim_fallback_parses_and_pins(monkeypatch) -> None:
    import psutil
    monkeypatch.setattr(psutil, "process_iter", lambda fields: [])
    monkeypatch.setattr(
        process_enforcement_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout='{"ProcessId":123,"CommandLine":"simplicio-mapper \\\"argument with spaces\\\""}',
        ),
    )
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: "windows-creation:1")

    assert process_enforcement_module._scan_windows_processes() == [
        process_enforcement_module.ProcessRecord(
            123, ["simplicio-mapper", "argument with spaces"], "windows-creation:1",
        )
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process metadata")
def test_windows_scanner_rejects_failed_cim_and_identity_drift(monkeypatch) -> None:
    import psutil
    monkeypatch.setattr(psutil, "process_iter", lambda fields: [])
    monkeypatch.setattr(
        process_enforcement_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="[]"),
    )
    assert process_enforcement_module._scan_windows_processes() == []


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows process metadata")
def test_windows_scanner_skips_invalid_rows_and_keeps_non_simplicio_cim(monkeypatch) -> None:
    import psutil
    class InvalidProcess:
        info = {"pid": "invalid", "cmdline": []}
    monkeypatch.setattr(psutil, "process_iter", lambda fields: [InvalidProcess()])
    monkeypatch.setattr(
        process_enforcement_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout='[{"ProcessId":"bad"},{"ProcessId":123,"CommandLine":"python worker.py"}]',
        ),
    )
    assert process_enforcement_module._scan_windows_processes() == [
        process_enforcement_module.ProcessRecord(123, ["python", "worker.py"]),
    ]
    assert process_enforcement_module._split_windows_command_line("") == []

    class Process:
        info = {"pid": 123, "cmdline": ["simplicio-mapper"]}
    identities = iter(["windows-creation:1", "windows-creation:2"])
    monkeypatch.setattr(psutil, "process_iter", lambda fields: [Process()])
    monkeypatch.setattr(process_enforcement_module, "_process_identity", lambda pid: next(identities))
    monkeypatch.setattr(
        process_enforcement_module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="[]"),
    )
    assert process_enforcement_module._scan_windows_processes() == []


def test_events_log_round_trips(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    append_event("detection_scan", {"flagged_count": 0}, path=path)
    append_event("cancel", {"pid": 4242, "ok": True}, path=path)
    events = read_events(path=path, limit=10)
    assert [event["kind"] for event in events] == ["detection_scan", "cancel"]


@pytest.mark.skipif(sys.platform == "darwin", reason="process CLI integration is Linux-specific")
def test_cli_status_top_queue_cancel_drain_reports(tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    module = [sys.executable, "-m", "simplicio_loop.process_enforcement_cli"]

    def run_cli(*args: str) -> dict:
        completed = subprocess.run(
            module + ["--registry", str(registry_path)] + list(args),
            capture_output=True, text=True, timeout=15, check=True,
        )
        return json.loads(completed.stdout)

    status = run_cli("status")
    assert status["schema"] == "simplicio.supervisor-status/v1"
    assert status["enforcement_enabled"] is False
    assert status["active_supervised_count"] == 0

    empty_top = run_cli("top")
    assert empty_top["processes"] == []

    empty_queue = run_cli("queue")
    assert empty_queue["in_flight"] == 0
    assert "note" in empty_queue

    # Register a real disposable process directly (simulating a supervised lease) so top/queue
    # /cancel have something real to operate on.
    canary = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    try:
        registry = ProcessRegistry(registry_path)
        registry.register(canary.pid, lease_id="cli-lease", spec_hash="h", argv=["sleep"])

        top = run_cli("top")
        assert len(top["processes"]) == 1
        assert top["processes"][0]["pid"] == canary.pid
        assert top["processes"][0]["lease_id"] == "cli-lease"

        queue = run_cli("queue")
        assert queue["in_flight"] == 1

        cancelled = run_cli("cancel", "--lease-id", "cli-lease")
        assert cancelled["ok"] is True
        assert cancelled["pid"] == canary.pid
        assert _wait_reaped(canary), "CLI cancel must actually terminate the process"
    finally:
        if canary.poll() is None:
            canary.terminate()
        canary.wait(timeout=5)

    # Drain: registry should self-prune the now-dead pid and report drained quickly.
    drained = run_cli("drain", "--timeout", "2", "--poll-interval", "0.1")
    assert drained["drained"] is True
    assert drained["remaining"] == 0

    reports = run_cli("reports", "--limit", "10")
    assert reports["schema"] == "simplicio.supervisor-reports/v1"
    kinds = [event["kind"] for event in reports["events"]]
    assert "cancel" in kinds


def test_cli_queue_reports_only_in_flight_leases_and_rejects_hub_socket(tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    base = [sys.executable, "-m", "simplicio_loop.process_enforcement_cli", "--registry", str(registry_path)]
    completed = subprocess.run(base + ["queue"], capture_output=True, text=True, timeout=15, check=True)
    report = json.loads(completed.stdout)
    assert report["schema"] == "simplicio.supervisor-queue/v1"
    assert report["in_flight"] == 0
    assert "hub" not in report
    rejected = subprocess.run(
        base + ["queue", "--hub-socket", str(tmp_path / "hub.sock")],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert rejected.returncode == 2


@pytest.mark.skipif(sys.platform == "darwin", reason="process-group termination is Linux-specific")
def test_cli_drain_force_kills_remaining_after_timeout(tmp_path) -> None:
    registry_path = tmp_path / "registry.json"
    module = [sys.executable, "-m", "simplicio_loop.process_enforcement_cli"]
    canary = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    try:
        registry = ProcessRegistry(registry_path)
        registry.register(canary.pid, lease_id="force-lease", spec_hash="h", argv=["sleep"])

        completed = subprocess.run(
            module + ["--registry", str(registry_path), "drain",
                      "--timeout", "0.3", "--poll-interval", "0.1", "--force"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        result = json.loads(completed.stdout)
        assert result["drained"] is False
        assert result["remaining"] == 1
        assert result["forced"] is True
        assert _wait_reaped(canary, timeout=5), "--force must actually terminate the leftover process"
    finally:
        if canary.poll() is None:
            canary.terminate()
        canary.wait(timeout=5)
