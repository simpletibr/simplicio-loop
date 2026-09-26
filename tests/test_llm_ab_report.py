"""TDD smoke tests for bench/llm_ab/report.py's task-count independence and
the new pricing/cost-report sections (--tasks 1/2/4, issue: real cost from
OpenRouter + task sets)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

pytest.importorskip("matplotlib")
import report  # noqa: E402


def _task(index, kind, checker="check_cadastro.py"):
    return {
        "index": index,
        "kind": kind,
        "success": True,
        "turns": 1,
        "totals": {
            "prompt_tokens": 100, "completion_tokens": 50, "reasoning_tokens": 0,
            "cached_tokens": 10, "cost_usd": 0.0001, "cmd_wall_s": 0.1, "cmd_cpu_s": 0.05,
            "n_commands": 1, "n_simplicio_commands": 0,
        },
        "commands": [],
    }


PRICING = {
    "model": "deepseek/deepseek-v4.1-flash",
    "available": True,
    "prompt": 0.00000014,
    "completion": 0.00000042,
    "input_cache_read": 0.0000000042,
    "input_cache_write": None,
    "internal_reasoning": None,
    "fetched_at": "2026-09-26T00:00:00Z",
}


def _results(task_count):
    tasks = [_task(1, "create")] if task_count == 1 else [_task(1, "create"), _task(2, "edit")]
    if task_count == 4:
        tasks += [_task(3, "create", "check_login.py"), _task(4, "edit", "check_login.py")]
    arms = {"normal": {"tasks": tasks, "total_wall_s": 1.0}}
    results = {
        "meta": {"model": "x", "date": "2026-09-26", "main_commit": "abc", "pip_versions": {},
                 "task_count": task_count, "pricing": PRICING},
        "arms": arms,
    }
    results["cost_report"] = {"pricing_table": [], "cost_table": []}
    return results


def test_build_does_not_crash_for_single_task_run(tmp_path):
    html = report.build(_results(1), str(tmp_path))
    assert "<html" in html


def test_build_does_not_crash_for_four_task_run(tmp_path):
    html = report.build(_results(4), str(tmp_path))
    assert "<html" in html


def test_build_kinds_are_derived_from_results_not_the_fixed_2_task_table(tmp_path):
    # A 1-task run only has "create" -- report.py must not blow up (or
    # silently render an "edit" section with no data) by reading the fixed
    # 2-task bench_tasks.TASKS list for section headers.
    html = report.build(_results(1), str(tmp_path))
    assert "Tarefas de criação" in html


def test_build_includes_pricing_table_section(tmp_path):
    results = _results(2)
    results["cost_report"]["pricing_table"] = [dict(PRICING)]
    html = report.build(results, str(tmp_path))
    assert "0.00000014" in html or "1.4e-07" in html


def test_build_handles_missing_pricing_gracefully(tmp_path):
    results = _results(2)
    results["meta"]["pricing"] = {"available": False}
    results["cost_report"] = {"pricing_table": [], "cost_table": []}
    html = report.build(results, str(tmp_path))
    assert "<html" in html
