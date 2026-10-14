"""3.44.1: pinned session, no fixed wave sleep, reasoning off, per-call telemetry, independent tasks."""
from __future__ import annotations

import asyncio
import io
import json
import subprocess
from unittest.mock import AsyncMock

from bench.llm_ab import llm_client as lc
from bench.llm_ab import run as bench_run
from bench.llm_ab import tasks as bench_tasks
from simplicio_loop.turbo import _call_record, run_turbo


def _repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=tmp_path, check=True)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", AsyncMock(return_value=None))
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "project-map.json").write_text('{"mark":"MAP"}', encoding="utf-8")


def test_wave_does_not_sleep_after_the_first_call(tmp_path, monkeypatch):
    _repo(tmp_path, monkeypatch)
    slept = []
    real_sleep = asyncio.sleep

    async def recording_sleep(seconds, *args, **kwargs):
        slept.append(seconds)
        return await real_sleep(seconds, *args, **kwargs)

    monkeypatch.setattr("time.sleep", lambda seconds: slept.append(seconds))
    monkeypatch.setattr(asyncio, "sleep", recording_sleep)

    async def complete(arm, messages, **kwargs):
        if kwargs.get("max_tokens") == 1:  # warm-up call
            return {"ok": True, "content": "OK"}
        name = "page" + messages[-1]["content"].split("Tasks:", 1)[1].strip().split(".", 1)[0].strip()
        return {"ok": True, "content": '{"operations":[{"path":"%s.html","find":"","replace":"x"}]}' % name}

    result = asyncio.run(run_turbo(tmp_path, [{"index": i, "text": "Create %s" % i} for i in range(1, 5)], complete))
    assert result["wave"] is True and result["applied_all"] is True and len(result["llm_calls"]) == 5  # warm-up + 4 tasks
    assert slept == []


def test_call_record_keeps_latency_and_provider():
    record = _call_record({"ok": True, "latency_s": 1.234, "provider": "Relace"}, 1)
    assert record["latency_s"] == 1.234
    assert record["provider"] == "Relace"


def test_chat_pins_the_session_and_sends_the_reasoning_block(monkeypatch):
    seen = {}

    class _Response(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        seen["headers"] = {k.lower(): v for k, v in request.header_items()}
        seen["body"] = json.loads(request.data)
        return _Response(json.dumps({"provider": "Relace", "choices": [{"message": {"content": "ok"}}],
                                     "usage": {"prompt_tokens": 1}}).encode())

    monkeypatch.setattr(lc, "get_key", lambda arm: "sk-test")
    monkeypatch.setattr(lc.urllib.request, "urlopen", fake_urlopen)
    reply = lc.chat("simplicio", [{"role": "user", "content": "hi"}],
                    session_id="sess-1", reasoning={"enabled": False})
    assert seen["headers"]["x-session-id"] == "sess-1"
    assert seen["body"]["reasoning"] == {"enabled": False}
    assert reply["provider"] == "Relace"


def test_turbo_complete_pins_the_arm_session_and_turns_reasoning_off(monkeypatch):
    import asyncio

    from simplicio_loop import turbo_provider

    captured = {}

    async def complete(arm, messages, **kw):
        captured.update(kw)
        return {"ok": True}

    monkeypatch.setattr(bench_run.lc, "get_key", lambda arm: "sk-arm")
    monkeypatch.setattr(turbo_provider, "complete", complete)
    monkeypatch.delenv("SIMPLICIO_BENCH_TURBO_REASONING", raising=False)
    asyncio.run(bench_run.turbo_complete("simplicio", [{"role": "user", "content": "x"}]))
    assert captured["session_id"] == bench_run.oc.session_id_for_arm("simplicio")
    assert captured["reasoning_off"] is True


def test_independent_ten_pages_have_no_dependencies_and_their_own_results_file():
    assert all(task["depends_on"] == [] for task in bench_tasks.task_set(10, independent=True))
    assert bench_tasks.task_set(10)[1]["depends_on"] == [1]  # the standard stays a chain
    assert bench_run.result_filename("d", "s", 10, independent=True) == "d-s-t10-ind.json"
    args = bench_run.build_arg_parser().parse_args(["--tasks", "10", "--independent"])
    assert args.independent is True
