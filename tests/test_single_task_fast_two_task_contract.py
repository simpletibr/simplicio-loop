"""Provider-free contract tests for the ordered two-task public route."""
from __future__ import annotations

import pytest

from simplicio_loop.intake_planner import dispatch_single_task_fast
from simplicio_loop.task_contract import compile_many


TASKS_MARKDOWN = """
System: Simplicio
Feature: TASK-CHECKERS-001 — criação
Type: criação
Goal: Criar site/checkers.html.
Target: site/checkers.html

1. Acceptance Criteria
Scenario 1: create
Given an empty site
When the creation task is applied
Then site/checkers.html exists

System: Simplicio
Feature: TASK-CHECKERS-002 — edição
Type: edição
Goal: Editar site/checkers.html.
Target: site/checkers.html
Depends on: TASK-CHECKERS-001

1. Acceptance Criteria
Scenario 1: edit
Given the created page
When the edit task is applied
Then the target is updated
"""


def _provider_free_collection_runner(calls):
    def run(*, tasks, task_file, repo, provider_worker):
        assert task_file == "checkers-tasks.md"
        assert repo == "."
        assert provider_worker == "openrouter"
        evidence = []
        for index, task in tasks:
            task_id = task["id"]
            calls.append(("mapper", task_id))
            mapper = {"schema": "simplicio.mapper-receipt/v1", "status": "MEASURED"}
            calls.append(("fast", task_id))
            fast = {"schema": "simplicio.fast-plan-receipt/v1", "status": "MEASURED"}
            calls.append(("provider", task_id))
            provider = {"schema": "simplicio.provider-worker-receipt/v1", "status": "READY"}
            calls.append(("dev_cli", task_id))
            dev_cli = {"schema": "simplicio.dev-cli-receipt/v1", "status": "applied"}
            evidence.append({
                "task_id": task_id,
                "task_index": index,
                "status": "succeeded",
                "mapper_receipt": mapper,
                "fast_receipt": fast,
                "provider_receipt": provider,
                "dev_cli_receipt": dev_cli,
                "evidence": {"schema": "simplicio.evidence-receipt/v1", "status": "VERIFIED"},
            })
        return {"status": "COMPLETED", "tasks": evidence}

    return run


def test_public_two_task_route_orders_and_runs_each_real_boundary_once():
    tasks = compile_many(TASKS_MARKDOWN, source_path="checkers-tasks.md")["tasks"]
    calls = []
    result = dispatch_single_task_fast(
        list(reversed(tasks)),
        operations={"provider_backed_collection": _provider_free_collection_runner(calls)},
        task_file="checkers-tasks.md",
    )

    assert result["status"] == "COMPLETED"
    assert result["execution_order"] == ["TASK-CHECKERS-001", "TASK-CHECKERS-002"]
    assert calls == [
        ("mapper", "TASK-CHECKERS-001"),
        ("fast", "TASK-CHECKERS-001"),
        ("provider", "TASK-CHECKERS-001"),
        ("dev_cli", "TASK-CHECKERS-001"),
        ("mapper", "TASK-CHECKERS-002"),
        ("fast", "TASK-CHECKERS-002"),
        ("provider", "TASK-CHECKERS-002"),
        ("dev_cli", "TASK-CHECKERS-002"),
    ]


def test_public_two_task_route_never_claims_completion_without_per_task_evidence():
    tasks = compile_many(TASKS_MARKDOWN)["tasks"]

    def incomplete(**_kwargs):
        return {"status": "COMPLETED", "tasks": [{"task_id": tasks[0]["id"]}]}

    result = dispatch_single_task_fast(
        tasks,
        operations={"provider_backed_collection": incomplete},
        task_file="checkers-tasks.md",
    )

    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "per_task_evidence_missing"


def test_one_task_json_compatibility_stays_on_local_first_route():
    task = {
        "goal": "edit one target",
        "acceptance_criteria": ["correct edit"],
        "issue": "repo#1",
        "source_revision": "rev-1",
        "target_hints": ["site/checkers.html"],
        "verification_commands": [["true"]],
        "bounded": True,
        "delivery_contract": {"watcher": True, "dod": True},
        "budgets": {"max_context_bytes": 100, "max_context_tokens": 100,
                    "max_diff_lines": 10, "max_iterations": 1},
        "stop": {"preserve": True},
        "recovery": {"preserve": True},
    }
    calls = []
    result = dispatch_single_task_fast(
        [task],
        operations={"provider_backed_collection": lambda **_kwargs: calls.append(True)},
    )

    assert result["route"] == "single-task-fast"
    assert result["status"] == "BLOCKED"
    assert calls == []


def test_public_help_names_both_accepted_contracts(capsys):
    from simplicio_loop.cli import main

    with pytest.raises(SystemExit) as exc_info:
        main(["single-task-fast", "--help"])
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "JSON task for local-first execution" in output
    assert "two-task Markdown collection" in output
