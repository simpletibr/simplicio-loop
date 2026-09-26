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
    assert "Somente criação" in html


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


def _arm(cost, wall, turns, kind="create"):
    task = _task(1, kind)
    task["totals"]["cost_usd"] = cost
    task["wall_s"] = wall
    task["turns"] = turns
    return {"tasks": [task], "total_wall_s": wall}


def test_arm_table_has_simplicio_savings_column_in_value_and_percent():
    arms = {"normal": _arm(0.010, 10.0, 6), "simplicio": _arm(0.004, 20.0, 8)}
    html = report.build_arm_table_rows(arms)
    assert "Economia com simplicio" in html
    assert "$0.00600 (60.0%)" in html          # cost saved
    assert "-10.0 (-100.0%)" in html           # wall spent more


def test_kind_scoped_table_shows_time_and_savings():
    arms = {"normal": _arm(0.010, 10.0, 6, "edit"), "simplicio": _arm(0.004, 5.0, 8, "edit")}
    html = report.build_arm_table_rows(arms, task_kind="edit")
    assert "Tempo (s)" in html
    assert "5.0 (50.0%)" in html


# -- per-phase reasoning-effort table (issue #1310 follow-up) ----------------

def _task_with_calls(index, kind, calls):
    task = _task(index, kind)
    task["llm_calls"] = calls
    return task


def test_build_effort_table_counts_per_arm_per_effort_value():
    arms = {
        "normal": {"tasks": [_task_with_calls(1, "create", [
            {"ok": True, "reasoning_effort": None}, {"ok": True, "reasoning_effort": None},
        ])]},
        "simplicio": {"tasks": [_task_with_calls(1, "create", [
            {"ok": True, "reasoning_effort": "high"}, {"ok": True, "reasoning_effort": "low"},
        ])]},
    }
    html = report.build_effort_table(arms)
    assert "normal" in html and "simplicio" in html
    assert "default" in html
    assert "high" in html and "low" in html


# -- per-LLM-call cache breakdown (issue #1336) ------------------------------


def test_build_per_call_cache_table_has_one_row_per_ok_call():
    arms = {
        "simplicio": {"tasks": [_task_with_calls(1, "create", [
            {"ok": True, "turn": 1, "prompt_tokens": 1000, "cached_tokens": 100},
            {"ok": True, "turn": 2, "prompt_tokens": 1200, "cached_tokens": 1150},
        ])]},
    }
    html = report.build_per_call_cache_table(arms)
    assert html.count("<tr>") == 2
    assert "10.0%" in html   # first call: 100/1000
    assert "95.8%" in html   # second call: 1150/1200


def test_build_per_call_cache_table_skips_failed_calls():
    arms = {
        "simplicio": {"tasks": [_task_with_calls(1, "create", [
            {"ok": False, "turn": 1, "prompt_tokens": 0, "cached_tokens": 0},
        ])]},
    }
    html = report.build_per_call_cache_table(arms)
    assert "colspan" in html  # placeholder row only -- no per-call row was rendered


def test_build_per_call_cache_table_marks_the_first_call_distinctly():
    arms = {
        "simplicio": {"tasks": [_task_with_calls(1, "create", [
            {"ok": True, "turn": 1, "prompt_tokens": 500, "cached_tokens": 0},
            {"ok": True, "turn": 2, "prompt_tokens": 500, "cached_tokens": 500},
        ])]},
    }
    html = report.build_per_call_cache_table(arms)
    lines = [line for line in html.splitlines() if "<tr>" in line]
    assert len(lines) == 2
    assert lines[0] != lines[1]


def test_build_per_call_cache_table_empty_when_no_calls():
    html = report.build_per_call_cache_table({"normal": {"tasks": [_task(1, "create")]}})
    assert "<tr>" in html  # placeholder row
    assert "colspan" in html


def test_build_includes_per_call_cache_section_in_html(tmp_path):
    results = _results(1)
    results["arms"]["normal"]["tasks"][0]["llm_calls"] = [
        {"ok": True, "turn": 1, "prompt_tokens": 100, "cached_tokens": 10},
    ]
    html = report.build(results, str(tmp_path))
    assert "cache" in html.lower()
    assert "por chamada" in html.lower()


def test_build_includes_effort_section_in_the_page(tmp_path):
    results = _results(1)
    html = report.build(results, str(tmp_path))
    assert "esforço" in html.lower() or "effort" in html.lower()


def test_build_labels_sequential_mode_by_default(tmp_path):
    results = _results(1)
    results["meta"]["batch"] = False
    html = report.build(results, str(tmp_path))
    assert "sequencial" in html.lower()


def test_build_labels_batch_mode(tmp_path):
    results = _results(1)
    results["meta"]["batch"] = True
    html = report.build(results, str(tmp_path))
    assert "batch" in html.lower()


def test_batch_run_explains_single_session_instead_of_empty_edit_table(tmp_path):
    results = _results(4)
    results["meta"]["batch"] = True
    html = report.build(results, str(tmp_path))
    assert "uma única sessão" in html
    assert "Somente edição (mesma sessão)" not in html


def test_set_without_edit_task_says_so_instead_of_empty_table(tmp_path):
    html = report.build(_results(1), str(tmp_path))
    assert "não tem tarefa de edição" in html
