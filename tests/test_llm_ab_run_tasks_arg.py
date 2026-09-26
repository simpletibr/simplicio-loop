"""TDD unit tests for run.py's ``--tasks`` CLI flag and task-count-aware
results filename -- the pure/parseable pieces, not a real benchmark run
(which needs live LLM calls and is never invoked from a test)."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import run  # noqa: E402


def test_build_arg_parser_defaults_tasks_to_2():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--arms", "normal"])
    assert args.tasks == 2


@pytest.mark.parametrize("n", [1, 2, 4])
def test_build_arg_parser_accepts_each_supported_task_count(n):
    ap = run.build_arg_parser()
    args = ap.parse_args(["--tasks", str(n)])
    assert args.tasks == n


def test_build_arg_parser_rejects_unsupported_task_count():
    ap = run.build_arg_parser()
    with pytest.raises(SystemExit):
        ap.parse_args(["--tasks", "3"])


def test_result_filename_includes_task_count():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert name == "2026-09-26-abc1234-t4.json"


def test_result_filename_differs_per_task_count():
    a = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=1)
    b = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=2)
    c = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert len({a, b, c}) == 3
