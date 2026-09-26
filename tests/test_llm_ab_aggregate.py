"""TDD unit tests for bench/llm_ab/aggregate.py (pure results aggregation).

Every function here takes plain dicts/lists (already-parsed JSON, in the
agentic-arm shape written by agent.run_agent + run.py) and returns plain
data -- no subprocess, no filesystem I/O except the one history-loading
helper, tested separately with tmp_path.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import aggregate as agg  # noqa: E402


def _totals(prompt=100, completion=50, reasoning=10, cached=20, cost=0.001,
            cmd_wall=1.0, cmd_cpu=0.5, n_commands=2, n_simplicio_commands=1):
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
        "cost_usd": cost,
        "llm_latency_s": 1.5,
        "cmd_wall_s": cmd_wall,
        "cmd_cpu_s": cmd_cpu,
        "n_commands": n_commands,
        "n_simplicio_commands": n_simplicio_commands,
    }


def _command(command="git status", cpu=0.1, peak_rss=15.0, rc=0):
    return {"command": command, "cpu_s": cpu, "wall_s": 0.2, "peak_rss_mb": peak_rss, "returncode": rc}


def _task(index=1, kind="create", success=True, turns=2, totals=None, commands=None):
    return {
        "index": index, "kind": kind, "success": success, "turns": turns,
        "totals": totals if totals is not None else _totals(),
        "commands": commands if commands is not None else [_command()],
        "llm_calls": [], "wall_s": 5.0,
    }


def _arm_data(tasks, total_wall_s=10.0):
    return {"tasks": tasks, "total_wall_s": total_wall_s}


def test_token_totals_sums_and_splits_reasoning_and_cache():
    arm = _arm_data([
        _task(1, totals=_totals(prompt=100, completion=50, reasoning=10, cached=20, cost=0.001)),
        _task(2, totals=_totals(prompt=200, completion=80, reasoning=5, cached=0, cost=0.002)),
    ])
    totals = agg.token_totals(arm)
    assert totals["prompt_uncached"] == (100 - 20) + (200 - 0)
    assert totals["cached"] == 20
    assert totals["completion_non_reasoning"] == (50 - 10) + (80 - 5)
    assert totals["reasoning"] == 15
    assert round(totals["cost_usd"], 6) == 0.003


def test_token_totals_handles_task_with_no_totals():
    arm = _arm_data([{"index": 1, "kind": "create", "success": False}])
    totals = agg.token_totals(arm)
    assert totals["prompt_uncached"] == 0
    assert totals["cost_usd"] == 0.0


def test_success_summary_counts_successful_tasks():
    arm = _arm_data([_task(1, success=True), _task(2, success=False)])
    n_success, n_tasks = agg.success_summary(arm)
    assert (n_success, n_tasks) == (1, 2)


def test_turns_stats_counts_first_try_success_and_total_turns():
    arm = _arm_data([
        _task(1, success=True, turns=1),
        _task(2, success=True, turns=3),
        _task(3, success=False, turns=1),
    ])
    total_turns, first_try, n_tasks = agg.turns_stats(arm)
    assert total_turns == 5
    assert first_try == 1
    assert n_tasks == 3


def test_cpu_ram_sums_command_cpu_and_takes_peak_rss():
    arm = _arm_data([
        _task(1, commands=[_command(cpu=0.5, peak_rss=30.0), _command(cpu=0.2, peak_rss=50.0)]),
    ])
    cpu_total, peak_rss = agg.cpu_ram(arm)
    assert round(cpu_total, 4) == 0.7
    assert peak_rss == 50.0


def test_cpu_ram_handles_no_commands():
    arm = _arm_data([{"index": 1, "kind": "create", "success": True}])
    cpu_total, peak_rss = agg.cpu_ram(arm)
    assert (cpu_total, peak_rss) == (0.0, 0.0)


def test_simplicio_command_count_sums_totals_field():
    arm = _arm_data([
        _task(1, totals=_totals(n_simplicio_commands=3)),
        _task(2, totals=_totals(n_simplicio_commands=2)),
    ])
    assert agg.simplicio_command_count(arm) == 5


def test_check_run_count_counts_checker_invocations_in_commands():
    arm = _arm_data([
        _task(1, commands=[_command("python3 tests/check_cadastro.py --stage 1"), _command("git status")]),
        _task(2, commands=[_command("python3 tests/check_cadastro.py --stage 2")]),
    ])
    assert agg.check_run_count(arm) == 2


def test_check_run_count_zero_when_never_invoked():
    arm = _arm_data([_task(1, commands=[_command("git status")])])
    assert agg.check_run_count(arm) == 0


def test_diff_history_reports_deltas_between_two_summaries():
    current = {"model": "m", "arms": {"normal": {"total_wall_s": 12.0}}}
    previous = {"model": "m", "arms": {"normal": {"total_wall_s": 20.0}}}
    deltas = agg.diff_history(current, previous)
    assert deltas["normal"]["total_wall_s_delta"] == 12.0 - 20.0


def test_diff_history_tolerates_missing_arm_in_previous():
    current = {"arms": {"simplicio": {"total_wall_s": 5.0}}}
    previous = {"arms": {}}
    deltas = agg.diff_history(current, previous)
    assert deltas["simplicio"]["total_wall_s_delta"] is None


def test_diff_history_tolerates_older_shape_results_file():
    # An older results.json (pre-agent-loop shape) still has total_wall_s at
    # the arm level, but under a different arm-name set -- diff_history must
    # not crash on it, only skip arms it cannot match.
    current = {"arms": {"simplicio": {"total_wall_s": 5.0}}}
    previous = {"arms": {"simplicio-files": {"total_wall_s": 1.0}, "simplicio-fast": {"total_wall_s": 2.0}}}
    deltas = agg.diff_history(current, previous)
    assert deltas["simplicio"]["total_wall_s_delta"] is None


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


def test_load_history_skips_unreadable_files_gracefully(tmp_path):
    (tmp_path / "2026-01-01-abc1234.json").write_text("{not valid json")
    history = agg.load_history(str(tmp_path), exclude_path=None)
    assert history == []


def test_load_history_filters_by_task_count_suffix(tmp_path):
    (tmp_path / "2026-01-01-abc1234-t2.json").write_text(json.dumps({"meta": {"date": "2026-01-01", "task_count": 2}}))
    (tmp_path / "2026-02-01-def5678-t4.json").write_text(json.dumps({"meta": {"date": "2026-02-01", "task_count": 4}}))
    history = agg.load_history(str(tmp_path), exclude_path=None, task_count=4)
    assert len(history) == 1
    assert history[0]["meta"]["task_count"] == 4


def test_load_history_task_count_filter_excludes_legacy_unsuffixed_files(tmp_path):
    (tmp_path / "2026-01-01-abc1234.json").write_text(json.dumps({"meta": {"date": "2026-01-01"}}))
    (tmp_path / "2026-02-01-def5678-t2.json").write_text(json.dumps({"meta": {"date": "2026-02-01", "task_count": 2}}))
    history = agg.load_history(str(tmp_path), exclude_path=None, task_count=2)
    assert len(history) == 1
    assert history[0]["meta"]["date"] == "2026-02-01"
