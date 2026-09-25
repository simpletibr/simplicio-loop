"""Tests for simplicio.task_operator (issue #210).

Covers the full spread the issue's acceptance criteria ask for:

- unit:        heartbeat cadence, startup-timeout vs total-timeout
                classification, cancellation, process-tree kill.
- integration: real (not mocked) short-lived Python subprocesses that stall
               before their first byte of output and after partial output.
- benchmark:   startup latency / deadline overhead, in the same lightweight
               timeit style as test_bench_hot_paths.py.

All child processes are short, local Python scripts — no network, no real
LLM calls, deterministic.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from simplicio import providers
from simplicio.task_operator import (
    PHASE_CANCELLED,
    PHASE_COMPLETED,
    PHASE_FAILED,
    PHASE_STARTUP_TIMEOUT,
    PHASE_TOTAL_TIMEOUT,
    run_bounded_subprocess,
)


def _write_script(tmp_path: Path, name: str, code: str) -> Path:
    path = tmp_path / name
    path.write_text(code, encoding="utf-8")
    return path


def _py(script: Path) -> list[str]:
    # -u: unbuffered, so the reader threads see bytes as soon as the child
    # writes them instead of waiting for a full buffer/flush.
    return [sys.executable, "-u", str(script)]


# --------------------------------------------------------------------------- #
# Unit: completion / failure / phase classification
# --------------------------------------------------------------------------- #


def test_completed_fast_process_returns_stdout(tmp_path):
    script = _write_script(tmp_path, "fast.py", "print('hi')\n")
    result = run_bounded_subprocess(_py(script), label="fast", startup_timeout=5, total_timeout=5)
    assert result.phase == PHASE_COMPLETED
    assert result.ok
    assert result.returncode == 0
    assert "hi" in result.stdout


def test_nonzero_exit_classified_as_failed(tmp_path):
    script = _write_script(
        tmp_path,
        "bad.py",
        "import sys\nsys.stderr.write('boom')\nsys.exit(3)\n",
    )
    result = run_bounded_subprocess(_py(script), label="bad", startup_timeout=5, total_timeout=5)
    assert result.phase == PHASE_FAILED
    assert result.returncode == 3
    assert "boom" in result.stderr
    assert not result.ok


def test_missing_executable_classified_as_failed_with_no_returncode():
    result = run_bounded_subprocess(
        ["simplicio-does-not-exist-binary"], label="missing", startup_timeout=1, total_timeout=1
    )
    assert result.phase == PHASE_FAILED
    assert result.returncode is None
    assert "not on PATH" in result.stderr


# --------------------------------------------------------------------------- #
# Unit: config parsing edge cases
# --------------------------------------------------------------------------- #


def test_env_float_falls_back_to_default_on_garbage_value(monkeypatch):
    from simplicio.task_operator import _env_float

    monkeypatch.setenv("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", "not-a-number")
    assert _env_float("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", 7.0) == 7.0


def test_env_float_falls_back_to_default_on_non_positive_value(monkeypatch):
    from simplicio.task_operator import _env_float

    monkeypatch.setenv("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", "-5")
    assert _env_float("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", 7.0) == 7.0


# --------------------------------------------------------------------------- #
# Unit: kill_process_tree — POSIX branch and stream-reader/writer error paths
#
# These exercise the code paths that this Windows CI box cannot naturally
# reach (getpgid/killpg genuinely do not exist here) by faking the `os.name`
# and `os` attributes the function reads, and the closed/broken-pipe error
# paths in the reader/writer helpers with doubles instead of real pipes.
# --------------------------------------------------------------------------- #


def test_kill_process_tree_posix_branch_uses_killpg(monkeypatch):
    from simplicio import task_operator

    calls = []
    monkeypatch.setattr(task_operator.os, "name", "posix", raising=False)
    monkeypatch.setattr(task_operator.os, "getpgid", lambda pid: 4242, raising=False)
    monkeypatch.setattr(
        task_operator.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)), raising=False
    )

    class _FakeProc:
        pid = 999

        def kill(self):
            raise AssertionError("should not fall back to proc.kill() on the happy path")

    task_operator.kill_process_tree(_FakeProc())
    assert len(calls) == 1
    assert calls[0][0] == 4242


def test_kill_process_tree_posix_branch_falls_back_when_getpgid_fails(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "posix", raising=False)

    def _boom(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(task_operator.os, "getpgid", _boom, raising=False)
    killed = []

    class _FakeProc:
        pid = 999

        def kill(self):
            killed.append(True)

    task_operator.kill_process_tree(_FakeProc())
    assert killed == [True]


def test_popen_kwargs_for_new_process_group_posix_branch(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "posix", raising=False)
    assert task_operator._popen_kwargs_for_new_process_group() == {"start_new_session": True}


def test_kill_process_tree_windows_branch_swallows_kill_oserror(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "nt", raising=False)
    monkeypatch.setattr(
        task_operator.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())
    )

    class _FakeProc:
        pid = 999

        def kill(self):
            raise OSError("already gone")

    # Must not raise even though both taskkill and the proc.kill() fallback
    # fail (the process may have already exited on its own).
    task_operator.kill_process_tree(_FakeProc())


def test_windows_descendant_probe_fails_closed_without_windll(monkeypatch):
    import ctypes

    from simplicio import task_operator

    monkeypatch.delattr(ctypes, "WinDLL", raising=False)
    assert task_operator._windows_descendant_pids(999) == []


def test_kill_process_tree_posix_branch_swallows_kill_oserror(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "posix", raising=False)

    def _boom(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(task_operator.os, "getpgid", _boom, raising=False)

    class _FakeProc:
        pid = 999

        def kill(self):
            raise OSError("already gone")

    task_operator.kill_process_tree(_FakeProc())


def test_kill_process_tree_windows_branch_falls_back_when_taskkill_missing(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "nt", raising=False)

    def _fake_run(*args, **kwargs):
        raise FileNotFoundError("no taskkill")

    monkeypatch.setattr(task_operator.subprocess, "run", _fake_run)
    killed = []

    class _FakeProc:
        pid = 999

        def kill(self):
            killed.append(True)

    task_operator.kill_process_tree(_FakeProc())
    assert killed == [True]


def test_kill_process_tree_windows_addresses_snapshot_descendants_first(monkeypatch):
    from simplicio import task_operator

    monkeypatch.setattr(task_operator.os, "name", "nt", raising=False)
    monkeypatch.setattr(task_operator, "_windows_descendant_pids", lambda pid: [1002, 1001])
    calls = []

    class _Result:
        returncode = 0

    def _fake_run(args, **kwargs):
        calls.append(args)
        return _Result()

    monkeypatch.setattr(task_operator.subprocess, "run", _fake_run)

    class _FakeProc:
        pid = 999

        def kill(self):
            raise AssertionError("taskkill succeeded, so the direct fallback is not expected")

    task_operator.kill_process_tree(_FakeProc())
    assert calls == [
        ["taskkill", "/PID", "1002", "/T", "/F"],
        ["taskkill", "/PID", "1001", "/T", "/F"],
        ["taskkill", "/PID", "999", "/T", "/F"],
    ]


def test_stream_reader_swallows_closed_stream_error():
    from simplicio.task_operator import _stream_reader

    class _BrokenStream:
        def read(self, n):
            raise OSError("closed")

        def close(self):
            raise OSError("already closed")

    chunks: list[str] = []
    # Must not raise even though both read() and the close() in `finally`
    # fail — a stalled/killed child's pipes are exactly this kind of messy.
    _stream_reader(_BrokenStream(), chunks, threading.Event())
    assert chunks == []


def test_stdin_writer_swallows_broken_pipe():
    from simplicio.task_operator import _stdin_writer

    class _BrokenStdin:
        def write(self, text):
            raise BrokenPipeError()

        def close(self):
            raise OSError("already closed")

    # Must not raise: the child may have already exited/closed stdin.
    _stdin_writer(_BrokenStdin(), "some prompt text")


def test_wait_after_kill_swallows_timeout(tmp_path, monkeypatch):
    """The final `proc.wait(timeout=5)` after a kill is best-effort — if the
    OS is slow to reap the process, that must not surface as a test/caller
    failure."""
    from simplicio import task_operator

    script = _write_script(tmp_path, "silent.py", "import time\ntime.sleep(5)\n")

    real_popen = task_operator.subprocess.Popen

    def _patched_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        original_wait = proc.wait

        def _flaky_wait(timeout=None):
            raise subprocess.TimeoutExpired(cmd="x", timeout=timeout or 0)

        proc.wait = _flaky_wait  # type: ignore[method-assign]
        proc._original_wait = original_wait  # keep a reference for cleanup
        return proc

    monkeypatch.setattr(task_operator.subprocess, "Popen", _patched_popen)
    result = run_bounded_subprocess(
        _py(script), label="wait-flaky", startup_timeout=0.2, total_timeout=30, heartbeat_interval=100
    )
    assert result.phase == PHASE_STARTUP_TIMEOUT


# --------------------------------------------------------------------------- #
# Unit + integration: startup timeout vs total timeout classification
#
# These run a *real* subprocess (not mocked) — the integration-test half of
# AC9: one script stalls before its first event, the other stalls after
# producing partial output.
# --------------------------------------------------------------------------- #


def test_startup_timeout_when_no_output_before_deadline(tmp_path):
    # Never prints anything, sleeps well past the startup deadline.
    script = _write_script(tmp_path, "silent_stall.py", "import time\ntime.sleep(5)\n")
    start = time.monotonic()
    result = run_bounded_subprocess(
        _py(script), label="silent", startup_timeout=0.3, total_timeout=30, heartbeat_interval=100
    )
    elapsed_wall = time.monotonic() - start
    assert result.phase == PHASE_STARTUP_TIMEOUT
    # returncode reflects whatever the OS reports for the killed process
    # (e.g. taskkill's own exit status on Windows, a negative signal number
    # on POSIX) — not part of the contract, only the phase classification is.
    assert "startup deadline" in result.recovery or "startup" in result.recovery.lower()
    # Bounded well under the sleep(5) the child would otherwise have taken.
    assert elapsed_wall < 3


def test_total_timeout_when_output_started_but_deadline_passed(tmp_path):
    # Produces output immediately (so it is NOT a startup stall) but then
    # never exits — this is the "actively progressing but past deadline"
    # case the issue asks to distinguish from a pure startup stall.
    script = _write_script(
        tmp_path,
        "partial_then_stall.py",
        "print('partial output', flush=True)\nimport time\ntime.sleep(5)\n",
    )
    result = run_bounded_subprocess(
        # Keep this explicit deadline comfortably above interpreter startup on
        # a loaded Windows host; the child still sleeps long enough to prove
        # the opt-in total deadline rather than normal completion.
        _py(script),
        label="partial",
        startup_timeout=30,
        total_timeout=2.0,
        heartbeat_interval=100,
    )
    assert result.phase == PHASE_TOTAL_TIMEOUT
    assert "partial output" in result.stdout
    assert "deadline" in result.recovery.lower()


# --------------------------------------------------------------------------- #
# Unit: cancellation
# --------------------------------------------------------------------------- #


def test_cancel_event_stops_a_long_running_process(tmp_path):
    script = _write_script(tmp_path, "long_running.py", "import time\ntime.sleep(30)\n")
    cancel_event = threading.Event()

    def _cancel_soon():
        time.sleep(0.2)
        cancel_event.set()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    start = time.monotonic()
    result = run_bounded_subprocess(
        _py(script),
        label="cancellable",
        startup_timeout=30,
        total_timeout=30,
        cancel_event=cancel_event,
    )
    elapsed_wall = time.monotonic() - start
    assert result.phase == PHASE_CANCELLED
    assert elapsed_wall < 3


# --------------------------------------------------------------------------- #
# Unit: heartbeat cadence
# --------------------------------------------------------------------------- #


def test_heartbeat_fires_at_configured_interval(tmp_path):
    script = _write_script(tmp_path, "slow_but_alive.py", "import time\ntime.sleep(0.7)\nprint('done')\n")
    root = tmp_path / "project"
    root.mkdir()

    result = run_bounded_subprocess(
        _py(script),
        label="heartbeat-test",
        startup_timeout=30,
        total_timeout=30,
        heartbeat_interval=0.1,
        root=str(root),
    )
    assert result.phase == PHASE_COMPLETED

    events_path = root / ".simplicio" / "events.jsonl"
    assert events_path.exists()
    records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line]
    heartbeats = [r for r in records if r["event"] == "provider_heartbeat"]
    # A ~0.7s run with a 0.1s heartbeat interval should fire multiple times;
    # generous lower bound to stay robust to scheduler jitter in CI.
    assert len(heartbeats) >= 2
    assert all(r["payload"]["label"] == "heartbeat-test" for r in heartbeats)


def test_long_running_process_emits_review_without_timeout(tmp_path):
    script = _write_script(
        tmp_path,
        "long_running_but_valid.py",
        "import time\ntime.sleep(0.25)\nprint('done')\n",
    )
    root = tmp_path / "project"
    root.mkdir()

    result = run_bounded_subprocess(
        _py(script),
        label="long-running-review",
        startup_timeout=None,
        total_timeout=None,
        long_running_review_after=0.05,
        heartbeat_interval=0.01,
        root=str(root),
    )

    assert result.phase == PHASE_COMPLETED
    records = [
        json.loads(line)
        for line in (root / ".simplicio" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    reviews = [record for record in records if record["event"] == "provider_long_running"]
    assert len(reviews) == 1
    assert reviews[0]["payload"]["pid"] > 0


# --------------------------------------------------------------------------- #
# Unit: process-tree kill — a timed-out parent must not leave its child alive
# --------------------------------------------------------------------------- #


def test_process_tree_kill_reaches_grandchildren(tmp_path):
    # The grandchild writes a growing heartbeat log instead of a single
    # marker after a fixed sleep — this makes the assertion robust to
    # scheduler jitter (CI/loaded-box variance in interpreter startup time)
    # because it observes "did activity stop after the kill", not "did one
    # specific write happen inside an exact timing window".
    heartbeat_log = tmp_path / "grandchild_heartbeat.log"
    child_script = _write_script(
        tmp_path,
        "tree_child.py",
        f"""
import time
for _ in range(100):
    with open(r"{heartbeat_log}", "a", encoding="utf-8") as fh:
        fh.write("beat\\n")
    time.sleep(0.1)
""",
    )
    parent_script = _write_script(
        tmp_path,
        "tree_parent.py",
        f"""
import subprocess
import sys
import time
subprocess.Popen([sys.executable, "-u", r"{child_script}"])
time.sleep(30)
""",
    )

    # Cancellation (not a race against a short timeout) triggers the kill —
    # the test waits for the grandchild to actually start writing heartbeats
    # before cancelling, so a slow interpreter start on a loaded CI box can
    # never make this kill fire before the grandchild was spawned, which
    # would prove nothing about tree-kill.
    cancel_event = threading.Event()
    outcome: list = []

    def _run():
        outcome.append(
            run_bounded_subprocess(
                _py(parent_script),
                label="tree-kill",
                startup_timeout=30,
                total_timeout=30,
                heartbeat_interval=100,
                cancel_event=cancel_event,
            )
        )

    runner = threading.Thread(target=_run, daemon=True)
    runner.start()

    for _ in range(400):
        if heartbeat_log.exists() and heartbeat_log.stat().st_size > 0:
            break
        time.sleep(0.05)
    else:
        pytest.fail("grandchild never started writing heartbeats — test setup broken")

    cancel_event.set()
    runner.join(timeout=15)
    assert outcome and outcome[0].phase == PHASE_CANCELLED

    # Give the (now-killed) grandchild's last in-flight write time to land,
    # then confirm no *further* heartbeats are appended — i.e. it actually
    # stopped running rather than merely not having written yet.
    time.sleep(0.5)
    size_after_kill = heartbeat_log.stat().st_size
    time.sleep(2.0)
    size_later = heartbeat_log.stat().st_size
    assert size_later == size_after_kill, (
        "grandchild kept writing heartbeats after the parent was killed — orphan process left behind"
    )


@pytest.mark.skip(reason="provider CLI execution was removed from simplicio-py")
def test_shell_out_codex_success_path_unchanged_under_bounded_timeout(monkeypatch, tmp_path):
    # A tiny Python "CLI" launched via a one-line shell/.cmd shim is more
    # portable across POSIX/Windows than hand-writing the --output-last-
    # message argv parsing in shell script, and it is what the real
    # `codex exec --output-last-message <path>` contract cares about anyway
    # (writing the completion to that file).
    fake_codex = tmp_path / "fake_codex_cli.py"
    fake_codex.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "out_path = args[args.index('--output-last-message') + 1]\n"
        "with open(out_path, 'w', encoding='utf-8') as fh:\n"
        "    fh.write('fake codex output')\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    if os.name == "nt":
        launcher = bin_dir / "codex.cmd"
        launcher.write_text(f'@echo off\r\n"{sys.executable}" "{fake_codex}" %*\r\n', encoding="utf-8")
    else:
        launcher = bin_dir / "codex"
        launcher.write_text(f'#!/bin/sh\n"{sys.executable}" "{fake_codex}" "$@"\n', encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("SIMPLICIO_PROVIDER_STARTUP_TIMEOUT_S", "10")
    monkeypatch.setenv("SIMPLICIO_PROVIDER_TOTAL_TIMEOUT_S", "10")

    out = providers._shell_out_codex("refactor x", "gpt-5")
    assert out == "fake codex output"


# --------------------------------------------------------------------------- #
# Benchmark: startup latency + deadline overhead (AC11), lightweight timeit
# budget in the style of tests/python/test_bench_hot_paths.py — not a
# micro-benchmark, a regression tripwire against an accidental perf cliff.
# --------------------------------------------------------------------------- #


def test_bounded_subprocess_startup_latency_budget(tmp_path):
    """The bounded helper's own overhead (thread spawn, polling loop) on top
    of a trivial subprocess should stay well under a generous budget."""
    script = _write_script(tmp_path, "noop.py", "pass\n")

    iterations = 10
    start = time.perf_counter()
    for _ in range(iterations):
        result = run_bounded_subprocess(_py(script), label="noop", startup_timeout=5, total_timeout=5)
        assert result.phase == PHASE_COMPLETED
    elapsed = time.perf_counter() - start
    per_call = elapsed / iterations
    print(f"\nBENCH run_bounded_subprocess noop: {per_call * 1000:.1f} ms/call ({iterations} calls)")
    # A bare `python -c pass` subprocess already costs tens of ms; this
    # budget is generous headroom for the bounded helper's own bookkeeping
    # (two reader threads + a 0.2s-granularity poll loop), not a tight target.
    assert per_call < 2.0, (
        f"run_bounded_subprocess noop took {per_call * 1000:.0f} ms/call, expected < 2000ms"
    )


def test_bounded_subprocess_deadline_overhead_is_small(tmp_path):
    """Compare wall time of a startup-timeout trip against the configured
    deadline itself — the *overhead* the polling loop adds on top of the
    deadline should be small (poll granularity, not another full second)."""
    script = _write_script(tmp_path, "silent.py", "import time\ntime.sleep(5)\n")
    deadline = 0.3

    start = time.perf_counter()
    result = run_bounded_subprocess(
        _py(script),
        label="deadline-overhead",
        startup_timeout=deadline,
        total_timeout=30,
        heartbeat_interval=100,
    )
    elapsed = time.perf_counter() - start
    overhead = elapsed - deadline
    print(f"\nBENCH startup-timeout deadline overhead: {overhead * 1000:.1f} ms (deadline={deadline}s)")
    assert result.phase == PHASE_STARTUP_TIMEOUT
    # Poll interval is 0.2s plus kill/join bookkeeping; budget generously.
    assert overhead < 1.5, f"deadline overhead was {overhead * 1000:.0f} ms, expected < 1500ms"
