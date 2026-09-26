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


def test_verifier_command_accepts_a_different_checker():
    assert bench_tasks.verifier_command(1, checker="check_login.py") == (
        "python3 tests/check_login.py --stage 1"
    )


def test_every_task_declares_its_checker():
    for t in bench_tasks.TASKS:
        assert t["checker"] == "check_cadastro.py"


def test_login_tasks_target_login_html_and_use_check_login():
    assert len(bench_tasks.LOGIN_TASKS) == 2
    for t in bench_tasks.LOGIN_TASKS:
        assert t["target"] == "login.html"
        assert t["checker"] == "check_login.py"


def test_login_task_kinds_are_create_then_edit():
    t3, t4 = bench_tasks.LOGIN_TASKS
    assert t3["kind"] == "create"
    assert t4["kind"] == "edit"
    assert t3["verify_stage"] == 1
    assert t4["verify_stage"] == 2


def test_login_task_indices_continue_after_cadastro_tasks():
    t3, t4 = bench_tasks.LOGIN_TASKS
    assert t3["index"] == 3
    assert t4["index"] == 4
    assert t4["depends_on"] == [t3["index"]]


def test_task_set_1_returns_only_task_1():
    result = bench_tasks.task_set(1)
    assert [t["index"] for t in result] == [1]


def test_task_set_2_returns_both_cadastro_tasks():
    result = bench_tasks.task_set(2)
    assert [t["index"] for t in result] == [1, 2]
    assert result == bench_tasks.TASKS


def test_task_set_4_returns_cadastro_plus_login_tasks():
    result = bench_tasks.task_set(4)
    assert [t["index"] for t in result] == [1, 2, 3, 4]


def test_task_set_rejects_unsupported_count():
    import pytest

    with pytest.raises(ValueError):
        bench_tasks.task_set(3)


def test_task_set_returns_independent_copies():
    a = bench_tasks.task_set(2)
    b = bench_tasks.task_set(2)
    assert a == b
    assert a is not b
