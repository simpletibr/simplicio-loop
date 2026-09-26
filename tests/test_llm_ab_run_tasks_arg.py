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


def test_build_arg_parser_defaults_task_timeout_to_opencode_default():
    ap = run.build_arg_parser()
    args = ap.parse_args([])
    assert args.task_timeout == run.oc.DEFAULT_RUN_TIMEOUT


def test_build_arg_parser_accepts_custom_task_timeout():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--task-timeout", "120"])
    assert args.task_timeout == 120


def test_build_arg_parser_batch_defaults_to_false():
    ap = run.build_arg_parser()
    args = ap.parse_args([])
    assert args.batch is False


def test_build_arg_parser_accepts_batch_flag():
    ap = run.build_arg_parser()
    args = ap.parse_args(["--batch"])
    assert args.batch is True


def test_result_filename_gets_batch_suffix_when_batch():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4, batch=True)
    assert name == "2026-09-26-abc1234-t4-batch.json"


def test_result_filename_no_batch_suffix_by_default():
    name = run.result_filename(date="2026-09-26", short_sha="abc1234", task_count=4)
    assert name == "2026-09-26-abc1234-t4.json"


def test_build_batch_prompt_combines_all_task_texts_in_one_user_prompt():
    """Per-arm skill install/prefixing is ``opencode_agent.run_opencode``'s
    job now (``skill=True``); ``build_batch_prompt`` just concatenates the
    raw task texts into one prompt, arm-agnostic."""
    task_list = [
        {"index": 1, "text": "Create a.html"},
        {"index": 2, "text": "Edit a.html"},
    ]
    prompt = run.build_batch_prompt(task_list)
    assert "Create a.html" in prompt
    assert "Edit a.html" in prompt
    assert not prompt.startswith("/simplicio-loop")
