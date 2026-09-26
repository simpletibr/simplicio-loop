"""TDD unit tests for bench/llm_ab/agent.py's pure helpers.

``run_agent`` itself drives real subprocesses/LLM calls and is exercised by
the benchmark run, not here; these tests cover the pure, side-effect-free
pieces: tail truncation, command classification, tool-call parsing, and
totals aggregation.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import agent  # noqa: E402


def test_truncate_tail_keeps_text_under_limit_unchanged():
    assert agent.truncate_tail("short", limit=8000) == "short"


def test_truncate_tail_keeps_only_the_last_n_chars():
    text = "a" * 100 + "b" * 50
    out = agent.truncate_tail(text, limit=50)
    assert out == "b" * 50
    assert len(out) == 50


def test_truncate_tail_default_limit_is_8000():
    text = "x" * 9000
    out = agent.truncate_tail(text)
    assert len(out) == 8000
    assert out == text[-8000:]


def test_truncate_tail_tolerates_none():
    assert agent.truncate_tail(None) == ""


def test_classify_command_true_for_simplicio_loop():
    assert agent.classify_command("simplicio-loop orient --task foo --json") is True


def test_classify_command_true_for_simplicio_mapper_dev_cli_fast():
    assert agent.classify_command("simplicio-mapper scan .") is True
    assert agent.classify_command("simplicio-dev-cli edit --plan p.json") is True
    assert agent.classify_command("simplicio-fast ingest .") is True


def test_classify_command_true_with_leading_path():
    assert agent.classify_command("./simplicio-loop wave run-1 --repo .") is True
    assert agent.classify_command("/venv/bin/simplicio-loop verify run-1") is True


def test_classify_command_true_inside_a_compound_command():
    assert agent.classify_command("cd /tmp/repo && simplicio-loop orient --task x") is True
    assert agent.classify_command("mkdir -p a; timeout 120 simplicio-dev-cli edit --plan p.json") is True
    assert agent.classify_command("ls | simplicio-fast ingest .") is True


def test_classify_command_false_for_other_commands():
    assert agent.classify_command("git status") is False
    assert agent.classify_command("python3 tests/check_cadastro.py --stage 1") is False
    assert agent.classify_command("ls -la") is False


def test_classify_command_tolerates_empty_or_whitespace():
    assert agent.classify_command("") is False
    assert agent.classify_command("   ") is False
    assert agent.classify_command(None) is False


def test_parse_tool_calls_extracts_name_and_arguments():
    message = {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_1",
                "function": {"name": "bash", "arguments": '{"command": "ls -la"}'},
            }
        ],
    }
    calls = agent.parse_tool_calls(message)
    assert calls == [{"id": "call_1", "name": "bash", "arguments": {"command": "ls -la"}}]


def test_parse_tool_calls_returns_empty_list_when_absent():
    assert agent.parse_tool_calls({"role": "assistant", "content": "DONE"}) == []
    assert agent.parse_tool_calls({}) == []
    assert agent.parse_tool_calls(None) == []


def test_parse_tool_calls_tolerates_malformed_arguments_json():
    message = {"tool_calls": [{"id": "c1", "function": {"name": "bash", "arguments": "not json"}}]}
    calls = agent.parse_tool_calls(message)
    assert calls == [{"id": "c1", "name": "bash", "arguments": {}}]


def test_parse_tool_calls_handles_multiple_calls_in_order():
    message = {
        "tool_calls": [
            {"id": "c1", "function": {"name": "bash", "arguments": '{"command": "a"}'}},
            {"id": "c2", "function": {"name": "bash", "arguments": '{"command": "b"}'}},
        ]
    }
    calls = agent.parse_tool_calls(message)
    assert [c["id"] for c in calls] == ["c1", "c2"]
    assert [c["arguments"]["command"] for c in calls] == ["a", "b"]


def _llm_call(ok=True, prompt=100, completion=50, reasoning=10, cached=20, cost=0.001, latency=1.5):
    return {
        "ok": ok,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
        "cost_usd": cost,
        "latency_s": latency,
    }


def _command(wall=1.0, cpu=0.5, is_simplicio=False):
    return {"wall_s": wall, "cpu_s": cpu, "is_simplicio": is_simplicio, "returncode": 0}


def test_summarize_sums_tokens_cost_and_latency():
    calls = [_llm_call(prompt=100, completion=50, reasoning=10, cached=20, cost=0.001, latency=1.0),
              _llm_call(prompt=200, completion=80, reasoning=5, cached=0, cost=0.002, latency=2.0)]
    totals = agent.summarize(calls, [])
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 130
    assert totals["reasoning_tokens"] == 15
    assert totals["cached_tokens"] == 20
    assert round(totals["cost_usd"], 6) == 0.003
    assert round(totals["llm_latency_s"], 4) == 3.0


def test_summarize_skips_failed_llm_calls():
    calls = [_llm_call(ok=False, prompt=999, completion=999)]
    totals = agent.summarize(calls, [])
    assert totals["prompt_tokens"] == 0
    assert totals["completion_tokens"] == 0


def test_summarize_sums_command_wall_cpu_and_counts_simplicio():
    commands = [_command(wall=1.0, cpu=0.5, is_simplicio=True),
                _command(wall=2.0, cpu=1.0, is_simplicio=False),
                _command(wall=0.5, cpu=0.2, is_simplicio=True)]
    totals = agent.summarize([], commands)
    assert round(totals["cmd_wall_s"], 4) == 3.5
    assert round(totals["cmd_cpu_s"], 4) == 1.7
    assert totals["n_commands"] == 3
    assert totals["n_simplicio_commands"] == 2


def test_summarize_handles_no_calls_or_commands():
    totals = agent.summarize([], [])
    assert totals["prompt_tokens"] == 0
    assert totals["n_commands"] == 0
    assert totals["n_simplicio_commands"] == 0
    assert totals["cost_usd"] == 0.0


def test_default_work_dir_is_outside_the_repository():
    import run  # noqa: E402 - bench/llm_ab is on sys.path above
    work = run.default_work_dir()
    try:
        assert not os.path.abspath(work).startswith(os.path.abspath(REPO) + os.sep)
    finally:
        os.rmdir(work)
