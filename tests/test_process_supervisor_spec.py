import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

from simplicio_loop.process_supervisor import (
    ProcessLease,
    ProcessSpec,
    ProcessSpecError,
    PythonProcessAdapter,
)


def _linux_visible_process_state(pid: int):
    """Return the state for a PID visible in this namespace, or ``None``.

    A container may mount procfs from an ancestor namespace, so `/proc/<pid>`
    is not necessarily the process addressed by `os.kill(pid, ...)`.  Match
    the caller's NSpid level before deciding whether the killed child is a
    zombie or has disappeared.
    """
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return ""

    def nspids(path: Path):
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("NSpid:"):
                    return [int(value) for value in line.split()[1:]]
        except (OSError, ValueError):
            return None
        return None

    caller = nspids(proc_root / "self" / "status")
    if not caller:
        return ""
    depth = len(caller) - 1
    try:
        entries = proc_root.iterdir()
    except OSError:
        return ""
    for entry in entries:
        if not entry.name.isdigit():
            continue
        values = nspids(entry / "status")
        if not values or depth >= len(values) or values[depth] != pid:
            continue
        try:
            return (entry / "stat").read_text(
                encoding="utf-8", errors="replace",
            ).rsplit(") ", 1)[1].split()[0]
        except (IndexError, OSError):
            return ""
    return None


def test_process_spec_is_structured_and_allowlisted() -> None:
    with tempfile.TemporaryDirectory() as directory:
        spec = ProcessSpec(
            (sys.executable, "-c", "print('ok')"),
            cwd=str(Path(directory).resolve()),
            env={"SIMPLICIO_TEST": "yes"},
            env_allowlist=("SIMPLICIO_TEST",),
            idempotency_key="one",
        )
        assert spec.to_dict()["shell"] is False
        assert spec.spec_hash
        with pytest.raises(ProcessSpecError):
            ProcessSpec(("echo",), shell=True)
        with pytest.raises(ProcessSpecError):
            ProcessSpec(("echo",), env={"NO": "x"}, env_allowlist=())


def test_lease_heartbeat_expiry_and_cancel() -> None:
    lease = ProcessLease("lease-1", "spec-1", ttl_seconds=5, expires_at=10)
    assert not lease.expired(now=9)
    assert lease.heartbeat(now=20) == 25
    assert not lease.expired(now=24)
    assert lease.expired(now=25)
    lease.cancel()
    assert lease.state == "cancelled"


def test_adapter_runs_argv_and_bounds_output() -> None:
    async def scenario() -> None:
        adapter = PythonProcessAdapter()
        spec = ProcessSpec(
            (sys.executable, "-c", "print('x' * 100)"),
            max_output_bytes=10,
        )
        result = await adapter.run(spec)
        assert result.returncode == 0
        assert len(result.stdout) == 10
        assert result.truncated

        failed = await adapter.run(
            ProcessSpec((sys.executable, "-c", "raise SystemExit(3)"))
        )
        assert failed.returncode == 3

    asyncio.run(scenario())


def test_adapter_classifies_timeout_and_missing_executable() -> None:
    async def scenario() -> None:
        adapter = PythonProcessAdapter()
        timeout = await adapter.run(
            ProcessSpec(
                (sys.executable, "-c", "import time; time.sleep(2)"),
                timeout_seconds=0.01,
            )
        )
        assert timeout.timed_out
        assert timeout.error_code == "deadline_exceeded"

        missing = await adapter.run(ProcessSpec(("simplicio-no-such-executable",)))
        assert missing.error_code == "executable_not_found"

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="process-group kill is POSIX-only")
def test_timeout_kills_the_whole_child_tree() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "grandchild.pid"
            script = (
                "import subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(30)'])\n"
                f"open({str(pid_file)!r}, 'w').write(str(child.pid))\n"
                "time.sleep(30)\n"
            )
            adapter = PythonProcessAdapter()
            result = await adapter.run(
                # The leader writes the grandchild pid only after its interpreter has
                # started; on a loaded host that takes seconds, so the deadline must
                # not race interpreter start-up.
                ProcessSpec((sys.executable, "-c", script), timeout_seconds=5.0)
            )
            assert result.timed_out
            assert result.error_code == "deadline_exceeded"

            deadline = time.monotonic() + 2.0
            grandchild_pid = None
            while time.monotonic() < deadline:
                if pid_file.exists():
                    grandchild_pid = int(pid_file.read_text())
                    break
                await asyncio.sleep(0.02)
            assert grandchild_pid is not None, "grandchild never reported its pid"

            deadline = time.monotonic() + 2.0
            alive = True
            while time.monotonic() < deadline:
                try:
                    os.kill(grandchild_pid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                state = _linux_visible_process_state(grandchild_pid)
                if state in {None, "Z"}:
                    # A zombie has already exited and cannot execute work; PID 1
                    # reaping latency in a container is not a process-tree leak.
                    alive = False
                    break
                await asyncio.sleep(0.02)
            assert not alive, "grandchild process survived the deadline kill"

    asyncio.run(scenario())


def test_adapter_cancellation_is_classified() -> None:
    async def scenario() -> None:
        task = asyncio.create_task(
            PythonProcessAdapter().run(
                ProcessSpec((sys.executable, "-c", "import time; time.sleep(2)"))
            )
        )
        await asyncio.sleep(0.02)
        task.cancel()
        result = await task
        assert result.cancelled
        assert result.error_code == "cancelled"

    asyncio.run(scenario())
