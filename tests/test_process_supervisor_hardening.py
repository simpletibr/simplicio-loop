import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
import subprocess

from simplicio_loop.async_io_supervisor import AsyncProcessSupervisor, DuplicateLease
from simplicio_loop.process_supervisor import (
    ProcessSpec,
    ProcessSpecError,
    PythonProcessAdapter,
)
from simplicio_loop import process_supervisor as supervisor_module
from tests._procs import GRANDCHILD_LEADER, gone_within


def test_windows_taskkill_nonzero_falls_back_to_direct_kill(monkeypatch) -> None:
    class Process:
        pid = 123
        killed = False
        def kill(self):
            self.killed = True

    process = Process()
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(supervisor_module, "os", os_with_name(supervisor_module.os, "nt"))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1),
    )
    monkeypatch.setattr(supervisor_module.os, "getpgid", lambda pid: (_ for _ in ()).throw(OSError()), raising=False)

    PythonProcessAdapter._kill_tree(process)

    assert process.killed is True


def test_windows_taskkill_success_does_not_direct_kill(monkeypatch) -> None:
    class Process:
        pid = 123
        killed = False
        def kill(self):
            self.killed = True

    process = Process()
    from tests._os_proxy import os_with_name

    monkeypatch.setattr(supervisor_module, "os", os_with_name(supervisor_module.os, "nt"))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    PythonProcessAdapter._kill_tree(process)
    assert process.killed is False


def test_reap_after_kill_is_bounded_and_retries_direct_kill(monkeypatch) -> None:
    class Process:
        killed = False
        async def communicate(self):
            return b"never", b"never"
        def kill(self):
            self.killed = True

    async def timeout(awaitable, *, timeout):
        awaitable.close()
        raise asyncio.TimeoutError

    process = Process()
    monkeypatch.setattr(supervisor_module.asyncio, "wait_for", timeout)
    assert asyncio.run(PythonProcessAdapter._reap_after_kill(process)) == (b"", b"")
    assert process.killed is True


def test_reap_after_kill_returns_collected_output() -> None:
    class Process:
        async def communicate(self):
            return b"out", b"err"

    assert asyncio.run(PythonProcessAdapter._reap_after_kill(Process())) == (b"out", b"err")


@pytest.mark.skipif(os.name == "nt", reason="process groups are POSIX")
def test_kill_tree_still_reaches_the_group_once_its_leader_was_reaped(tmp_path) -> None:
    # The leader exits and is reaped while a grandchild it started keeps running in the leader's group, which the
    # leader's pid still names. Looking the group up with getpgid() fails once the leader is reaped, so the kill must
    # signal the group by that pid instead.
    pidfile = tmp_path / "grandchild.pid"

    async def scenario() -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-c", GRANDCHILD_LEADER, str(pidfile),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        await process.wait()
        PythonProcessAdapter._kill_tree(process)

    asyncio.run(scenario())
    assert gone_within(int(pidfile.read_text())), "the grandchild outlived the kill of its reaped leader"


def test_argv_with_shell_metacharacters_is_never_shell_interpreted() -> None:
    spec = ProcessSpec((sys.executable, "-c", "print('ok')", "; rm -rf /tmp/x && echo hi"))
    assert spec.argv[-1] == "; rm -rf /tmp/x && echo hi"
    assert spec.to_dict()["shell"] is False

    async def scenario() -> None:
        result = await PythonProcessAdapter().run(spec)
        assert result.returncode == 0
        assert result.stdout.strip() == "ok"

    asyncio.run(scenario())


def test_shell_string_as_single_argv_token_is_not_split_or_run() -> None:
    dangerous = ProcessSpec(("echo hi; touch /tmp/simplicio-should-not-exist",))

    async def scenario() -> None:
        result = await PythonProcessAdapter().run(dangerous)
        assert result.error_code == "executable_not_found"
        assert result.returncode is None

    asyncio.run(scenario())
    assert not Path("/tmp/simplicio-should-not-exist").exists()


def test_secret_env_var_is_stripped_unless_explicitly_allowlisted(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_FAKE_SECRET_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("SIMPLICIO_TEST_ALLOWED", "visible")
    spec = ProcessSpec(
        (
            sys.executable,
            "-c",
            "import os; print(os.environ.get('SIMPLICIO_FAKE_SECRET_API_KEY', '<absent>')); "
            "print(os.environ.get('SIMPLICIO_TEST_ALLOWED', '<absent>'))",
        ),
        env_allowlist=("SIMPLICIO_TEST_ALLOWED",),
    )

    async def scenario() -> str:
        result = await PythonProcessAdapter().run(spec)
        return result.stdout

    stdout = asyncio.run(scenario())
    lines = stdout.strip().splitlines()
    assert lines[0] == "<absent>"
    assert lines[1] == "visible"


def test_cwd_outside_allowed_root_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as root:
        allowed_root = str(Path(root).resolve())
        outside = str(Path(root).parent.resolve())
        with pytest.raises(ProcessSpecError):
            ProcessSpec(("echo",), cwd=outside, cwd_allowlist=(allowed_root,))


def test_cwd_path_traversal_out_of_allowed_root_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as root:
        allowed_root = Path(root).resolve()
        nested = allowed_root / "nested"
        nested.mkdir()
        traversal_cwd = str(nested / ".." / ".." / "etc")
        with pytest.raises(ProcessSpecError):
            ProcessSpec(("echo",), cwd=traversal_cwd, cwd_allowlist=(str(allowed_root),))


def test_cwd_inside_allowed_root_is_accepted() -> None:
    with tempfile.TemporaryDirectory() as root:
        allowed_root = Path(root).resolve()
        nested = allowed_root / "nested"
        nested.mkdir()
        spec = ProcessSpec(("echo",), cwd=str(nested), cwd_allowlist=(str(allowed_root),))
        assert spec.cwd == str(nested)


def test_concurrent_submission_with_same_idempotency_key_executes_once() -> None:
    async def scenario() -> None:
        supervisor = AsyncProcessSupervisor(max_concurrency=2)
        spec = ProcessSpec(
            (sys.executable, "-c", "import time; time.sleep(0.05); print('done')"),
            idempotency_key="dup-key",
        )
        results = await asyncio.gather(
            supervisor.run(spec), supervisor.run(spec), return_exceptions=True
        )
        successes = [r for r in results if not isinstance(r, BaseException)]
        duplicates = [r for r in results if isinstance(r, DuplicateLease)]
        assert len(successes) == 1
        assert len(duplicates) == 1
        assert successes[0].returncode == 0

    asyncio.run(scenario())
