"""Deterministic multi-task DAG state for governed task batches."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BATCH_SCHEMA = "simplicio.dev-cli.task-batch/v1"
TERMINAL = {"passed", "blocked"}
VALID_STATES = {"pending", "running", "passed", "blocked"}


class BatchError(ValueError):
    """Invalid batch graph or state transition."""


class StaleBatchError(BatchError):
    """Persisted state belongs to a different source/plan/base identity."""


@dataclass(frozen=True)
class BatchIdentity:
    source_hash: str
    plan_hash: str
    base_sha: str

    def to_dict(self) -> dict[str, str]:
        return {"source_hash": self.source_hash, "plan_hash": self.plan_hash, "base_sha": self.base_sha}


class TaskBatch:
    """Freeze a task DAG and persist resumable per-item state atomically."""

    def __init__(self, path: str | Path, tasks: list[Mapping[str, Any]], identity: BatchIdentity):
        self.path = Path(path)
        self.identity = identity
        self.tasks = self._normalize(tasks)
        self._validate_graph()

    @classmethod
    def create(
        cls,
        path: str | Path,
        tasks: list[Mapping[str, Any]],
        *,
        source_hash: str,
        plan_hash: str,
        base_sha: str,
    ) -> TaskBatch:
        batch = cls(path, tasks, BatchIdentity(source_hash, plan_hash, base_sha))
        batch.save()
        return batch

    @classmethod
    def load(cls, path: str | Path) -> TaskBatch:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema") != BATCH_SCHEMA:
            raise BatchError("unsupported task batch schema")
        identity = BatchIdentity(**payload["identity"])
        return cls(path, payload.get("tasks", []), identity)

    @staticmethod
    def _normalize(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for raw in tasks:
            task_id = str(raw.get("id", "")).strip()
            if not task_id:
                raise BatchError("every task requires a stable id")
            deps = tuple(dict.fromkeys(str(item) for item in raw.get("depends_on", [])))
            result.append(
                {
                    "id": task_id,
                    "depends_on": list(deps),
                    "source_hash": str(raw.get("source_hash", "")),
                    "plan_hash": str(raw.get("plan_hash", "")),
                    "base_sha": str(raw.get("base_sha", "")),
                    "status": str(raw.get("status", "pending")),
                    "attempts": int(raw.get("attempts", 0)),
                    "receipt": raw.get("receipt"),
                }
            )
        return result

    def _validate_graph(self) -> None:
        ids = [task["id"] for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise BatchError("duplicate task id")
        known = set(ids)
        for task in self.tasks:
            if task["status"] not in VALID_STATES:
                raise BatchError(f"invalid state for {task['id']}: {task['status']}")
            unknown = set(task["depends_on"]) - known
            if unknown:
                raise BatchError(f"unknown dependency for {task['id']}: {sorted(unknown)}")
        visiting: set[str] = set()
        visited: set[str] = set()
        by_id = {task["id"]: task for task in self.tasks}

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise BatchError("task dependency cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dep in by_id[task_id]["depends_on"]:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in ids:
            visit(task_id)

    def save(self) -> None:
        payload = {"schema": BATCH_SCHEMA, "identity": self.identity.to_dict(), "tasks": self.tasks}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline=chr(10)) as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write(chr(10))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def _task(self, task_id: str) -> dict[str, Any]:
        for task in self.tasks:
            if task["id"] == task_id:
                return task
        raise KeyError(task_id)

    def ready(self) -> list[dict[str, Any]]:
        by_id = {task["id"]: task for task in self.tasks}
        return [
            task
            for task in self.tasks
            if task["status"] == "pending"
            and all(by_id[dep]["status"] == "passed" for dep in task["depends_on"])
        ]

    def transition(
        self,
        task_id: str,
        status: str,
        *,
        receipt: Mapping[str, Any] | None = None,
        source_hash: str | None = None,
        plan_hash: str | None = None,
        base_sha: str | None = None,
    ) -> dict[str, Any]:
        if status not in VALID_STATES - {"pending"}:
            raise BatchError(f"unsupported transition state: {status}")
        task = self._task(task_id)
        if (
            source_hash
            and source_hash != self.identity.source_hash
            or plan_hash
            and plan_hash != self.identity.plan_hash
            or base_sha
            and base_sha != self.identity.base_sha
        ):
            raise StaleBatchError("transition identity does not match the frozen batch")
        if status in {"running", "passed"} and task not in self.ready() and status == "running":
            raise BatchError(f"dependencies are not passed for {task_id}")
        if task["status"] == "passed" and status != "passed":
            raise BatchError(f"passed task cannot regress: {task_id}")
        task["status"] = status
        if status == "running":
            task["attempts"] += 1
        if receipt is not None:
            task["receipt"] = dict(receipt)
        self.save()
        return dict(task)

    def status(self) -> dict[str, Any]:
        counts = {state: sum(task["status"] == state for task in self.tasks) for state in VALID_STATES}
        return {
            "schema": BATCH_SCHEMA,
            "identity": self.identity.to_dict(),
            "counts": counts,
            "tasks": self.tasks,
            "ready": [task["id"] for task in self.ready()],
        }
