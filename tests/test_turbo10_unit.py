"""Hermetic 10-task turbo comparison: no OpenRouter, one Mapper survey, cache prefix."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.llm_ab import compare10
from bench.llm_ab import tasks as bench_tasks
from bench.llm_ab.report import run_prefix_cache_miss
from simplicio_loop.turbo import survey_tasks


def test_task_set_ten_is_ten_pages():
    tasks = bench_tasks.task_set(10)
    assert len(tasks) == 10
    assert [task["target"] for task in tasks] == [f"p{i:02d}.html" for i in range(1, 11)]
    assert tasks[0]["checker"] == "check_page.py"


def test_hermetic_comparison_is_ten_tasks_and_does_not_call_openrouter(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("OpenRouter was called")

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", lambda _root: None)
    out = tmp_path / "hermetic.json"
    rc = compare10.main(["--root", str(tmp_path), "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["task_count"] == 10
    assert payload["arms"] == ["normal", "simplicio"]
    assert payload["live"] is False
    assert payload["prefix_cache_miss"] is None
    assert len(payload["tasks"]) == 10


def test_mapper_survey_runs_once_and_is_reused_for_the_other_nine(tmp_path, monkeypatch):
    calls = []

    def fake_index(root):
        calls.append(root)
        state = root / ".simplicio-loop"
        state.mkdir(parents=True, exist_ok=True)
        (state / "project-map.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("simplicio_loop.cli_impl._ensure_project_map", fake_index)
    tasks = bench_tasks.task_set(10)
    first = survey_tasks(tmp_path, tasks)
    second = survey_tasks(tmp_path, tasks)
    assert len(calls) == 1
    generations = {row["generation"] for row in first["tasks"]}
    assert generations == {second["generation"]}
    assert len(generations) == 1
    assert first["tasks"][0]["reused"] is False
    assert all(row["reused"] for row in first["tasks"][1:])
    assert second["indexed"] is False


def test_prefix_cache_rule_matches_the_deepseek_harness(tmp_path):
    cold = [
        {"ok": True, "turn": 1, "cached_tokens": 0, "prompt_tokens": 400},
        {"ok": True, "turn": 2, "cached_tokens": 256, "prompt_tokens": 420},
        {"ok": True, "turn": 3, "cached_tokens": 0, "prompt_tokens": 420},
    ]
    miss = run_prefix_cache_miss(cold)
    assert miss is not None
    assert miss["turn"] == 3
    held = compare10.recorded_prefix_calls(11)
    assert run_prefix_cache_miss(held) is None
    assert held[0]["cached_tokens"] == 0
    assert all(call["cached_tokens"] > 0 for call in held[1:])


def test_short_prefix_cannot_claim_a_cache_hit():
    calls = compare10.recorded_prefix_calls(3, prefix_tokens=16)
    assert calls[1]["cached_tokens"] == 0
    assert run_prefix_cache_miss(calls) is not None


def test_page_checker_accepts_boolean_required(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_page",
        Path("bench/llm_ab/fixture/tests/check_page.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    page = tmp_path / "p01.html"
    page.write_text(
        '<form id="p01"><label>Email</label>'
        '<input type="email" name="email" required>'
        '<button type="submit">Submit</button></form>',
        encoding="utf-8",
    )
    assert mod.check(page, 1) == []
