"""A continuation's request starts with the task contract and the fixed instructions, byte for byte the same in every
continuation of one chain, so the provider's prompt cache can read them; the handoff comes after (#1608).

The chain sends a request only when it fits the ceiling, so the refused attempts are captured by a stub planner.
"""
from __future__ import annotations

import json

from simplicio_loop import agent_handoff, exec_planner, input_ceiling
from tests.test_exec_planner_unit import run

TASK = "STABLE-TASK " + "word " * 100 + "TAIL-MARKER"
CRITERION = "answer the objective with one plan JSON object"


def _attempts(monkeypatch, tmp_path, refusals):
    """Run one chain whose first ``refusals`` attempts are over the ceiling; return the result and every attempt's prompt."""
    prompts = []

    async def planner(family, role, prompt, **_kwargs):
        prompts.append(prompt)
        code = "input_ceiling_exceeded" if len(prompts) <= refusals else "ok"
        return exec_planner.PlannerResult(code, family, role, "model", "")

    monkeypatch.setattr(exec_planner, "run_planner", planner)
    monkeypatch.setenv(input_ceiling.ENV_NAME, "2000")
    res = run(exec_planner.run_planner_with_fallback(
        "planning", TASK, cwd=str(tmp_path), families=["claude"], repo_root=tmp_path, run_id="run-p"))
    return res, prompts


def test_the_continuations_share_the_contract_and_the_instructions_byte_for_byte(monkeypatch, tmp_path):
    res, prompts = _attempts(monkeypatch, tmp_path, refusals=2)

    assert res.is_ok() and len(prompts) == 3
    first, second = prompts[1], prompts[2]
    contract = first[:first.index(exec_planner.CONTINUATION_PREFIX)]
    assert TASK in contract and CRITERION in contract
    stable = len(contract) + len(exec_planner.CONTINUATION_PREFIX)
    assert first[:stable] == second[:stable]
    assert first.count(TASK) == 1  # the task is not repeated after the instructions
    assert '"continuation": 1' in first[stable:] and '"continuation": 2' in second[stable:]


def test_the_handoff_of_a_continuation_records_no_cache_counters_because_no_request_was_sent(monkeypatch, tmp_path):
    res, _prompts = _attempts(monkeypatch, tmp_path, refusals=2)

    assert res.continuations == 2
    for n in (1, 2):
        tokens = json.loads(agent_handoff.handoff_path(tmp_path, "run-p-claude", n).read_text())["tokens"]
        assert tokens["basis"] == "ESTIMATED"
        assert tokens["cache_read_input_tokens"] is None and tokens["cache_creation_input_tokens"] is None
