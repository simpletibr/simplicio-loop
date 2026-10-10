"""The turbo request error keeps the cause (start of stderr) and the end, not only one of them (part of #1631)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from simplicio_loop.watcher247 import host_mode, sandbox

CAUSE = "subprocess.TimeoutExpired: simplicio-mapper canonical overlay timed out after 300.0 seconds"
END = "RuntimeError: turbo gave up"


def _fail_with(monkeypatch, dest, stderr: str) -> RuntimeError:
    async def fake_run(argv, **kwargs):
        return SimpleNamespace(stdout="", stderr=stderr)

    monkeypatch.setattr(host_mode.proc, "run", fake_run)
    monkeypatch.setattr(sandbox, "wrap", lambda argv, **kwargs: argv)
    monkeypatch.setattr(sandbox, "scrubbed_env", lambda env, **kwargs: {})
    with pytest.raises(RuntimeError) as failure:
        asyncio.run(host_mode._request(dest, "task"))
    return failure.value


def test_a_long_stderr_keeps_its_cause_and_its_end(monkeypatch, tmp_path):
    stderr = CAUSE + "\n" + ("  File \"mapper.py\", line 1, in step\n" * 40) + END
    message = str(_fail_with(monkeypatch, tmp_path, stderr))

    assert CAUSE[:60] in message, message
    assert message.endswith(END), message
    assert len(message) <= 500


def test_a_short_stderr_is_kept_whole(monkeypatch, tmp_path):
    message = str(_fail_with(monkeypatch, tmp_path, "boom: " + END))

    assert message == f"turbo request failed: boom: {END}"
