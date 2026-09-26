"""TDD unit tests for bench/llm_ab/tasks.py (pure task table)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import tasks as bench_tasks  # noqa: E402


def test_exactly_two_tasks():
    assert len(bench_tasks.TASKS) == 2


def test_task_kinds_are_create_then_edit():
    kinds = [t["kind"] for t in bench_tasks.TASKS]
    assert kinds == ["create", "edit"]


def test_task2_depends_on_task1():
    t1, t2 = bench_tasks.TASKS
    assert t1["depends_on"] == []
    assert t2["depends_on"] == [t1["index"]]


def test_tasks_by_kind_groups_and_preserves_order():
    grouped = bench_tasks.tasks_by_kind()
    assert set(grouped) == {"create", "edit"}
    assert [t["index"] for t in grouped["create"]] == [1]
    assert [t["index"] for t in grouped["edit"]] == [2]


def test_every_task_targets_cadastro_html():
    for t in bench_tasks.TASKS:
        assert t["target"] == "cadastro.html"


def test_verify_stage_matches_task_order():
    t1, t2 = bench_tasks.TASKS
    assert t1["verify_stage"] == 1
    assert t2["verify_stage"] == 2


def test_verifier_command_uses_check_cadastro_with_stage():
    cmd1 = bench_tasks.verifier_command(1)
    cmd2 = bench_tasks.verifier_command(2)
    assert cmd1 == "python3 tests/check_cadastro.py --stage 1"
    assert cmd2 == "python3 tests/check_cadastro.py --stage 2"
    assert cmd1 != cmd2
