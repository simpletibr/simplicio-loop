from __future__ import annotations

import pytest

from simplicio.orchestrator.multi_task import (
    BatchBuildError,
    BatchError,
    StaleBatchError,
    TaskBatch,
    build_batch_preview,
)


def test_batch_freezes_dag_and_resumes_passed_items(tmp_path):
    batch = TaskBatch.create(
        tmp_path / "batch.json",
        [
            {"id": "A"},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C"},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )
    assert [task["id"] for task in batch.ready()] == ["A", "C"]
    batch.transition("A", "running")
    batch.transition("A", "passed", receipt={"status": "MEASURED"})
    assert [task["id"] for task in batch.ready()] == ["B", "C"]
    restored = TaskBatch.load(tmp_path / "batch.json")
    assert restored.status()["counts"]["passed"] == 1
    assert restored.status()["ready"] == ["B", "C"]


def test_batch_rejects_cycles_unknown_dependencies_and_stale_transition(tmp_path):
    with pytest.raises(BatchError, match="cycle"):
        TaskBatch.create(
            tmp_path / "cycle.json",
            [{"id": "A", "depends_on": ["B"]}, {"id": "B", "depends_on": ["A"]}],
            source_hash="s",
            plan_hash="p",
            base_sha="b",
        )
    with pytest.raises(BatchError, match="unknown"):
        TaskBatch.create(
            tmp_path / "unknown.json",
            [{"id": "A", "depends_on": ["missing"]}],
            source_hash="s",
            plan_hash="p",
            base_sha="b",
        )
    batch = TaskBatch.create(
        tmp_path / "stale.json", [{"id": "A"}], source_hash="s", plan_hash="p", base_sha="b"
    )
    with pytest.raises(StaleBatchError):
        batch.transition("A", "running", source_hash="old")


def test_batch_blocks_dependent_task_until_predecessor_passes(tmp_path):
    batch = TaskBatch.create(
        tmp_path / "blocked.json",
        [{"id": "A"}, {"id": "B", "depends_on": ["A"]}],
        source_hash="s",
        plan_hash="p",
        base_sha="b",
    )
    with pytest.raises(BatchError, match="dependencies"):
        batch.transition("B", "running")


def test_batch_resume_rejects_late_arrivals_and_changed_task_shape(tmp_path):
    path = tmp_path / "resume.json"
    TaskBatch.create(
        path,
        [
            {"id": "A", "source_hash": "hash-a"},
            {"id": "B", "depends_on": ["A"], "source_hash": "hash-b"},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )

    with pytest.raises(StaleBatchError, match="late arrivals"):
        TaskBatch.resume(
            path,
            [
                {"id": "A", "source_hash": "hash-a"},
                {"id": "B", "depends_on": ["A"], "source_hash": "hash-b"},
                {"id": "C", "source_hash": "hash-c"},
            ],
            source_hash="source",
            plan_hash="plan",
            base_sha="base",
        )

    with pytest.raises(StaleBatchError, match="dependencies changed for B"):
        TaskBatch.resume(
            path,
            [
                {"id": "A", "source_hash": "hash-a"},
                {"id": "B", "source_hash": "hash-b"},
            ],
            source_hash="source",
            plan_hash="plan",
            base_sha="base",
        )


def test_batch_resume_allows_exact_frozen_inventory_and_passed_state(tmp_path):
    path = tmp_path / "resume-ok.json"
    batch = TaskBatch.create(
        path,
        [
            {"id": "A", "source_hash": "hash-a"},
            {"id": "B", "depends_on": ["A"], "source_hash": "hash-b"},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )
    batch.transition("A", "running")
    batch.transition("A", "passed", receipt={"status": "MEASURED"})

    resumed = TaskBatch.resume(
        path,
        [
            {"id": "A", "source_hash": "hash-a"},
            {"id": "B", "depends_on": ["A"], "source_hash": "hash-b"},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )

    assert resumed.status()["counts"]["passed"] == 1
    assert resumed.status()["ready"] == ["B"]


def test_build_batch_preview_infers_unique_dependencies_from_task_labels():
    preview = build_batch_preview(
        {
            "tasks": [
                {
                    "task_id": "TASK-LOGIN",
                    "functionality": "Login",
                    "source_hash": "a" * 64,
                    "dependencies": [],
                },
                {
                    "task_id": "TASK-REPORTS",
                    "functionality": "Reports",
                    "source_hash": "b" * 64,
                    "dependencies": [{"text": "depends on: Login"}],
                },
            ]
        }
    )

    assert preview["task_count"] == 2
    assert preview["ready"] == ["TASK-LOGIN"]
    assert preview["tasks"][1]["depends_on"] == ["TASK-LOGIN"]


def test_build_batch_preview_rejects_ambiguous_or_unknown_dependencies():
    with pytest.raises(BatchBuildError, match="ambiguous dependency"):
        build_batch_preview(
            {
                "tasks": [
                    {
                        "task_id": "TASK-LOGIN-A",
                        "functionality": "Login",
                        "source_hash": "a" * 64,
                        "dependencies": [],
                    },
                    {
                        "task_id": "TASK-LOGIN-B",
                        "functionality": "Login",
                        "source_hash": "b" * 64,
                        "dependencies": [],
                    },
                    {
                        "task_id": "TASK-REPORTS",
                        "functionality": "Reports",
                        "source_hash": "c" * 64,
                        "dependencies": [{"text": "depends on: Login"}],
                    },
                ]
            }
        )
    with pytest.raises(BatchBuildError, match="unknown dependency"):
        build_batch_preview(
            {
                "tasks": [
                    {
                        "task_id": "TASK-LOGIN",
                        "functionality": "Login",
                        "source_hash": "a" * 64,
                        "dependencies": [{"text": "depends on: Missing"}],
                    }
                ]
            }
        )


def test_batch_drain_executes_ready_items_deterministically_and_stabilizes_empty_rounds(tmp_path):
    batch = TaskBatch.create(
        tmp_path / "drain.json",
        [
            {"id": "A"},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C"},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )
    calls: list[str] = []

    def executor(task):
        calls.append(task["id"])
        return {
            "status": "passed",
            "cost_usd": {"A": 0.25, "B": 0.5, "C": 0.75}[task["id"]],
            "receipt": {"status": "MEASURED", "task_id": task["id"]},
        }

    first = batch.drain(executor, empty_rounds=2)

    assert calls == ["A", "C", "B"]
    assert first["executed"] == ["A", "C", "B"]
    assert first["quarantined"] == []
    assert first["rounds"] == 4
    assert first["empty_rounds"] == 2
    assert first["counts"]["passed"] == 3
    assert first["cost_usd"] == 1.5
    assert first["run_cost_usd"] == 1.5
    assert [task["attempts"] for task in first["tasks"]] == [1, 1, 1]
    assert [task["cost_usd"] for task in first["tasks"]] == [0.25, 0.5, 0.75]

    second = batch.drain(executor, empty_rounds=2)

    assert calls == ["A", "C", "B"]
    assert second["executed"] == []
    assert second["quarantined"] == []
    assert second["rounds"] == 2
    assert second["empty_rounds"] == 2
    assert second["counts"]["passed"] == 3
    assert second["cost_usd"] == 1.5
    assert second["run_cost_usd"] == 0.0


def test_batch_drain_quarantines_failures_and_preserves_receipts(tmp_path):
    batch = TaskBatch.create(
        tmp_path / "drain-failure.json",
        [
            {"id": "A"},
            {"id": "B", "depends_on": ["A"]},
            {"id": "C", "depends_on": ["B"]},
        ],
        source_hash="source",
        plan_hash="plan",
        base_sha="base",
    )
    calls: list[str] = []

    def executor(task):
        calls.append(task["id"])
        if task["id"] == "A":
            return {"status": "passed", "cost_usd": 0.1, "receipt": {"status": "MEASURED"}}
        raise RuntimeError("boom")

    summary = batch.drain(executor, empty_rounds=1)

    assert calls == ["A", "B"]
    assert summary["executed"] == ["A", "B"]
    assert summary["quarantined"] == ["B"]
    assert summary["counts"]["passed"] == 1
    assert summary["counts"]["blocked"] == 1
    assert summary["counts"]["pending"] == 1
    assert summary["ready"] == []
    assert summary["cost_usd"] == 0.1
    assert summary["run_cost_usd"] == 0.1

    tasks = {task["id"]: task for task in summary["tasks"]}
    assert tasks["A"]["receipt"] == {"status": "MEASURED"}
    assert tasks["B"]["attempts"] == 1
    assert tasks["B"]["receipt"]["status"] == "UNVERIFIED"
    assert tasks["B"]["receipt"]["error_type"] == "RuntimeError"
    assert "boom" in tasks["B"]["receipt"]["error"]
    assert tasks["C"]["attempts"] == 0
    assert tasks["C"]["status"] == "pending"
