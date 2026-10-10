"""Each production site that cuts an error message keeps the cause and the end (#1665, #1636)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

CAUSE = "CAUSE: the first line that says why it failed"
END = "END: the last line of the report"


def _long(cause: str = CAUSE, end: str = END) -> str:
    return f"{cause}\n{'x' * 3000}\n{end}"


def test_mapper_index_failure_keeps_the_cause(monkeypatch, tmp_path: Path) -> None:
    from simplicio_loop import map_service_gc, map_service_mapper

    async def fake_run(argv, timeout):
        return 2, "", _long()

    monkeypatch.setattr(map_service_gc, "startup_gc", lambda path: None)
    monkeypatch.setattr(map_service_mapper, "mapper_binary_path", lambda: "simplicio-mapper")
    monkeypatch.setattr(map_service_mapper, "_run_mapper", fake_run)
    with pytest.raises(map_service_mapper.MapperIndexError) as caught:
        asyncio.run(map_service_mapper.run_mapper_index(str(tmp_path)))
    message = str(caught.value)
    assert CAUSE in message and END in message
    assert "truncated" in message


def test_fabric_failed_job_journal_keeps_the_cause(tmp_path: Path) -> None:
    from simplicio_loop.fabric_scheduler import AsyncFabricScheduler, FabricJob

    async def scenario() -> list:
        scheduler = AsyncFabricScheduler(
            max_running=1, queue_capacity=2, journal_path=str(tmp_path / "journal.jsonl")
        )

        async def fail() -> None:
            raise RuntimeError(_long())

        future = await scheduler.submit(FabricJob("bad", fail))
        await asyncio.gather(future, return_exceptions=True)
        await scheduler.shutdown()
        return scheduler.journal.rows

    rows = asyncio.run(scenario())
    failed = [row for row in rows if row["state"] == "failed"]
    assert len(failed) == 1
    message = failed[0]["detail"]["message"]
    assert CAUSE in message and END in message


def test_watcher_tick_error_status_keeps_the_cause(monkeypatch, tmp_path: Path) -> None:
    from simplicio_loop.watcher247 import __main__ as watcher_main

    written: list = []

    async def fake_tick(dry_run: bool = False) -> None:
        raise RuntimeError(_long())

    async def fake_write_status(**extra) -> None:
        written.append(extra)

    class FakeStore:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def migrate_legacy(self, ttl_s: int = 0) -> None:
            return None

    monkeypatch.setattr(watcher_main.worktrees, "cancel_on_sigterm", lambda: None)
    monkeypatch.setattr(watcher_main.author_executor, "refusal", lambda: None)
    monkeypatch.setattr(watcher_main.env_guard, "refusal", lambda: None)
    monkeypatch.setattr(watcher_main.config, "WORK", tmp_path / "work")
    monkeypatch.setattr(watcher_main, "ClaimStore", FakeStore)
    monkeypatch.setattr(watcher_main.tick, "tick", fake_tick)
    monkeypatch.setattr(watcher_main.state, "write_status", fake_write_status)
    monkeypatch.setattr(watcher_main.state, "log", lambda *args, **kwargs: None)
    assert asyncio.run(watcher_main.main(once=True)) == 0
    errors = [item["error"] for item in written if item.get("phase") == "error"]
    assert len(errors) == 1
    assert CAUSE in errors[0] and END in errors[0]


def test_strict_probe_failure_keeps_the_cause(monkeypatch) -> None:
    from simplicio_loop import strict_mode

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr=_long())

    monkeypatch.setattr(strict_mode.subprocess, "run", fake_run)
    result = strict_mode._probe_version("tool", path="/bin/tool")
    assert CAUSE in result["error"] and END in result["error"]

    def raising_run(*args, **kwargs):
        raise subprocess.SubprocessError(_long())

    monkeypatch.setattr(strict_mode.subprocess, "run", raising_run)
    result = strict_mode._probe_version("tool", path="/bin/tool")
    assert CAUSE in result["error"] and END in result["error"]
