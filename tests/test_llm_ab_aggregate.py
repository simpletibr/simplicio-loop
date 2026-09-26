"""TDD unit tests for bench/llm_ab/aggregate.py (pure results aggregation).

Every function here takes plain dicts/lists (already-parsed JSON) and
returns plain data -- no subprocess, no filesystem I/O except the one
history-loading helper, tested separately with tmp_path.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import aggregate as agg  # noqa: E402


def _attempt(ok=True, prompt=100, completion=50, reasoning=10, cached=20, cost=0.001,
             cpu_s=0.5, peak_rss_mb=30.0, wall_s=1.2, check_ran=True):
    rec = {
        "attempt": 1,
        "llm_call": {
            "ok": ok,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "cached_tokens": cached,
            "cost_usd": cost,
            "step_cpu_s": cpu_s,
            "step_peak_rss_mb": peak_rss_mb,
            "step_wall_s": wall_s,
        },
    }
    if check_ran:
        rec["check_step"] = {"cpu_s": 0.1, "peak_rss_mb": 15.0, "wall_s": 0.2}
    return rec


def _arm_data(tasks, steps=None):
    return {"tasks": tasks, "steps": steps or [], "total_wall_s": 10.0}


def test_token_totals_sums_and_splits_reasoning_and_cache():
    arm = _arm_data([
        {"task_index": 1, "success": True, "attempts": [_attempt(prompt=100, completion=50, reasoning=10, cached=20, cost=0.001)]},
        {"task_index": 2, "success": True, "attempts": [_attempt(prompt=200, completion=80, reasoning=5, cached=0, cost=0.002)]},
    ])
    totals = agg.token_totals(arm)
    assert totals["prompt_uncached"] == (100 - 20) + (200 - 0)
    assert totals["cached"] == 20
    assert totals["completion_non_reasoning"] == (50 - 10) + (80 - 5)
    assert totals["reasoning"] == 15
    assert round(totals["cost_usd"], 6) == 0.003


def test_token_totals_skips_failed_llm_calls():
    arm = _arm_data([
        {"task_index": 1, "success": False, "attempts": [_attempt(ok=False, prompt=999, completion=999)]},
    ])
    totals = agg.token_totals(arm)
    assert totals["prompt_uncached"] == 0
    assert totals["completion_non_reasoning"] == 0


def test_attempts_stats_counts_first_try_success():
    arm = _arm_data([
        {"task_index": 1, "success": True, "attempts": [_attempt()]},
        {"task_index": 2, "success": True, "attempts": [_attempt(), _attempt()]},
        {"task_index": 3, "success": False, "attempts": [_attempt()]},
    ])
    total_attempts, first_try, n_tasks = agg.attempts_stats(arm)
    assert total_attempts == 4
    assert first_try == 1
    assert n_tasks == 3


def test_success_summary_counts_successful_tasks():
    arm = _arm_data([
        {"task_index": 1, "success": True, "attempts": [_attempt()]},
        {"task_index": 2, "success": False, "attempts": [_attempt()]},
    ])
    n_success, n_tasks = agg.success_summary(arm)
    assert (n_success, n_tasks) == (1, 2)


def test_cpu_ram_sums_step_metrics_and_takes_peak_rss():
    arm = _arm_data(
        [{"task_index": 1, "success": True, "attempts": [_attempt(cpu_s=0.5, peak_rss_mb=30.0)]}],
        steps=[{"step": "orient", "task_index": 1, "metrics": {"cpu_s": 1.0, "peak_rss_mb": 50.0}}],
    )
    cpu_total, peak_rss = agg.cpu_ram(arm)
    # 0.5 (llm) + 0.1 (check) + 1.0 (orient step) = 1.6
    assert round(cpu_total, 4) == 1.6
    assert peak_rss == 50.0


def test_check_run_count_counts_every_attempt_that_ran_the_checker():
    arm = _arm_data([
        {"task_index": 1, "success": True, "attempts": [_attempt(check_ran=True), _attempt(check_ran=True)]},
        {"task_index": 2, "success": True, "attempts": [_attempt(check_ran=False)]},
    ])
    assert agg.check_run_count(arm) == 2


def test_diff_history_reports_deltas_between_two_summaries():
    current = {"model": "m", "arms": {"normal": {"total_wall_s": 12.0, "success": (2, 2)}}}
    previous = {"model": "m", "arms": {"normal": {"total_wall_s": 20.0, "success": (2, 2)}}}
    deltas = agg.diff_history(current, previous)
    assert deltas["normal"]["total_wall_s_delta"] == 12.0 - 20.0


def test_diff_history_tolerates_missing_arm_in_previous():
    current = {"arms": {"simplicio-fast": {"total_wall_s": 5.0}}}
    previous = {"arms": {}}
    deltas = agg.diff_history(current, previous)
    assert deltas["simplicio-fast"]["total_wall_s_delta"] is None


def test_load_history_reads_and_sorts_other_result_files(tmp_path):
    older = {"meta": {"date": "2026-01-01"}}
    newer = {"meta": {"date": "2026-06-01"}}
    (tmp_path / "2026-01-01-abc1234.json").write_text(json.dumps(older))
    (tmp_path / "2026-06-01-def5678.json").write_text(json.dumps(newer))
    (tmp_path / "not-a-result.txt").write_text("ignore me")
    history = agg.load_history(str(tmp_path), exclude_path=None)
    assert [h["meta"]["date"] for h in history] == ["2026-01-01", "2026-06-01"]


def test_load_history_excludes_the_current_file(tmp_path):
    current_path = tmp_path / "2026-06-01-def5678.json"
    current_path.write_text(json.dumps({"meta": {"date": "2026-06-01"}}))
    older = tmp_path / "2026-01-01-abc1234.json"
    older.write_text(json.dumps({"meta": {"date": "2026-01-01"}}))
    history = agg.load_history(str(tmp_path), exclude_path=str(current_path))
    assert len(history) == 1
    assert history[0]["meta"]["date"] == "2026-01-01"
