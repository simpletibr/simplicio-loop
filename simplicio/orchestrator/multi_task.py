"""Deterministic multi-task DAG state for governed task batches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

BATCH_SCHEMA = "simplicio.dev-cli.task-batch/v1"
TERMINAL = {"passed", "blocked"}
VALID_STATES = {"pending", "running", "passed", "blocked"}
ExecutorResult = Mapping[str, Any] | bool | None


class BatchError(ValueError):
    """Invalid batch graph or state transition."""


class StaleBatchError(BatchError):
    """Persisted state belongs to a different source/plan/base identity."""


class BatchBuildError(BatchError):
    """Raw intake tasks cannot become an unambiguous deterministic DAG."""

    def __init__(self, diagnostics: list[str]) -> None:
        self.diagnostics = list(diagnostics)
        super().__init__("; ".join(self.diagnostics))


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

    @classmethod
    def resume(
        cls,
        path: str | Path,
        tasks: list[Mapping[str, Any]],
        *,
        source_hash: str,
        plan_hash: str,
        base_sha: str,
    ) -> TaskBatch:
        batch = cls.load(path)
        batch.assert_resume_compatible(
            tasks,
            source_hash=source_hash,
            plan_hash=plan_hash,
            base_sha=base_sha,
        )
        return batch

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
                    "anchor": raw.get("anchor"),
                    "contract": raw.get("contract"),
                    "status": str(raw.get("status", "pending")),
                    "attempts": int(raw.get("attempts", 0)),
                    "cost": raw.get("cost"),
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

    def assert_resume_compatible(
        self,
        tasks: list[Mapping[str, Any]],
        *,
        source_hash: str,
        plan_hash: str,
        base_sha: str,
    ) -> None:
        if (
            source_hash != self.identity.source_hash
            or plan_hash != self.identity.plan_hash
            or base_sha != self.identity.base_sha
        ):
            raise StaleBatchError("resume identity does not match the frozen batch")
        candidate_tasks = self._normalize(tasks)
        frozen_ids = [task["id"] for task in self.tasks]
        candidate_ids = [task["id"] for task in candidate_tasks]
        late_arrivals = [task_id for task_id in candidate_ids if task_id not in set(frozen_ids)]
        missing = [task_id for task_id in frozen_ids if task_id not in set(candidate_ids)]
        if late_arrivals or missing:
            details: list[str] = []
            if late_arrivals:
                details.append(f"late arrivals: {late_arrivals}")
            if missing:
                details.append(f"missing tasks: {missing}")
            raise StaleBatchError("resume task inventory changed; " + ", ".join(details))
        frozen_by_id = {task["id"]: task for task in self.tasks}
        for candidate in candidate_tasks:
            frozen = frozen_by_id[candidate["id"]]
            if candidate["depends_on"] != frozen["depends_on"]:
                raise StaleBatchError(
                    f"resume dependencies changed for {candidate['id']}: "
                    f"{frozen['depends_on']} -> {candidate['depends_on']}"
                )
            if candidate["source_hash"] != frozen["source_hash"]:
                raise StaleBatchError(f"resume source changed for {candidate['id']}")
            if candidate["plan_hash"] and candidate["plan_hash"] != frozen["plan_hash"]:
                raise StaleBatchError(f"resume plan changed for {candidate['id']}")
            if candidate["base_sha"] and candidate["base_sha"] != frozen["base_sha"]:
                raise StaleBatchError(f"resume base changed for {candidate['id']}")

    def transition(
        self,
        task_id: str,
        status: str,
        *,
        receipt: Mapping[str, Any] | None = None,
        cost_usd: float | int | str | None = None,
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
            if "cost" in receipt:
                task["cost"] = receipt["cost"]
        if cost_usd is not None:
            task["cost_usd"] = _coerce_cost(task.get("cost_usd", 0.0)) + _coerce_cost(cost_usd)
        self.save()
        return dict(task)

    def _executor_outcome(self, result: ExecutorResult) -> tuple[str, Mapping[str, Any] | None, float]:
        if isinstance(result, bool):
            return ("passed" if result else "blocked"), None, 0.0
        if result is None or not isinstance(result, Mapping):
            raise BatchError("executor callback must return a bool or mapping")
        status_value = result.get("status")
        if status_value is None and "passed" in result:
            status_value = "passed" if bool(result.get("passed")) else "blocked"
        status = str(status_value or "").strip()
        if status not in TERMINAL:
            raise BatchError(f"executor callback returned unsupported status: {status or '<empty>'}")
        receipt = result.get("receipt")
        if receipt is not None and not isinstance(receipt, Mapping):
            raise BatchError("executor callback receipt must be a mapping")
        return status, cast(Mapping[str, Any] | None, receipt), _coerce_cost(result.get("cost_usd", 0.0))

    def drain(
        self,
        executor: Callable[[dict[str, Any]], ExecutorResult],
        *,
        empty_rounds: int = 1,
    ) -> dict[str, Any]:
        if empty_rounds < 0:
            raise BatchError("empty_rounds must be >= 0")
        rounds = 0
        consecutive_empty_rounds = 0
        executed: list[str] = []
        quarantined: list[str] = []
        run_cost_usd = 0.0
        while consecutive_empty_rounds < empty_rounds:
            ready = self.ready()
            rounds += 1
            if not ready:
                consecutive_empty_rounds += 1
                continue
            consecutive_empty_rounds = 0
            for candidate in ready:
                task_id = str(candidate["id"])
                current = self.transition(task_id, "running")
                executed.append(task_id)
                try:
                    status, receipt, cost_usd = self._executor_outcome(executor(dict(current)))
                except Exception as exc:
                    status = "blocked"
                    receipt = {
                        "status": "UNVERIFIED",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                    cost_usd = 0.0
                self.transition(task_id, status, receipt=receipt, cost_usd=cost_usd)
                run_cost_usd += cost_usd
                if status == "blocked":
                    quarantined.append(task_id)
        payload = self.status()
        payload.update(
            {
                "rounds": rounds,
                "empty_rounds": consecutive_empty_rounds,
                "executed": executed,
                "quarantined": quarantined,
                "run_cost_usd": round(run_cost_usd, 10),
            }
        )
        return payload

    def status(self) -> dict[str, Any]:
        counts = {state: sum(task["status"] == state for task in self.tasks) for state in VALID_STATES}
        return {
            "schema": BATCH_SCHEMA,
            "identity": self.identity.to_dict(),
            "counts": counts,
            "tasks": self.tasks,
            "ready": [task["id"] for task in self.ready()],
            "cost_usd": round(sum(_coerce_cost(task.get("cost_usd", 0.0)) for task in self.tasks), 10),
        }

    def cancel(self, *, reason: str = "stop requested") -> dict[str, Any]:
        """Cancel non-terminal items and persist a machine-readable receipt."""

        for task in self.tasks:
            if task["status"] in {"pending", "running"}:
                task["status"] = "blocked"
                task["receipt"] = {
                    "status": "CANCELLED",
                    "reason": reason,
                }
        self.save()
        return self.status()

    def finalize(self, integration_gate: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return a completion decision requiring terminal tasks and green gates."""

        counts = self.status()["counts"]
        terminal = counts["pending"] == 0 and counts["running"] == 0
        gate = dict(integration_gate or {})
        gates_green = bool(gate.get("passed", False)) and not bool(gate.get("failures"))
        return {
            "schema": "simplicio.dev-cli.task-batch-completion/v1",
            "complete": terminal and gates_green and counts["blocked"] == 0,
            "terminal": terminal,
            "gates_green": gates_green,
            "counts": counts,
            "integration_gate": gate,
        }


def _coerce_cost(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        cost = float(str(value))
    except (TypeError, ValueError) as exc:
        raise BatchError("cost_usd must be numeric") from exc
    if cost < 0 or cost != cost or cost in (float("inf"), float("-inf")):
        raise BatchError("cost_usd must be finite and >= 0")
    return cost


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _stable_hash(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _dependency_text(item: object) -> str:
    if isinstance(item, Mapping):
        return str(item.get("text", "")).strip()
    return str(item).strip()


def _dependency_target(text: str) -> str:
    lowered = text.strip()
    lowered = re.sub(
        r"^(?:dep(?:ende|ends)?\s+(?:de|on)|blocked by|after|requires?)\s*[:\-–—]?\s*",
        "",
        lowered,
        flags=re.IGNORECASE,
    )
    return lowered.strip()


def _task_label(task: Mapping[str, Any]) -> str:
    return str(task.get("functionality") or task.get("task_id") or "").strip()


def _resolve_batch_tasks(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    known_ids = [str(task.get("task_id", "")).strip() for task in tasks]
    labels: dict[str, list[str]] = {}
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        if not task_id:
            continue
        for label in {task_id, _task_label(task)}:
            normalized = _normalize_label(label)
            if normalized:
                labels.setdefault(normalized, []).append(task_id)

    diagnostics: list[str] = []
    resolved: list[dict[str, Any]] = []
    for task in tasks:
        task_id = str(task.get("task_id", "")).strip()
        deps: list[str] = []
        for raw_dep in task.get("dependencies", []):
            text = _dependency_text(raw_dep)
            if not text:
                continue
            if re.search(r"\b(?:none|nenhuma|nenhum|n/a|nao ha|não há)\b", text, re.IGNORECASE):
                continue
            explicit = [
                candidate
                for candidate in known_ids
                if candidate
                and candidate != task_id
                and re.search(rf"(?<![A-Za-z0-9_-]){re.escape(candidate)}(?![A-Za-z0-9_-])", text)
            ]
            if explicit:
                deps.extend(explicit)
                continue
            target = _dependency_target(text)
            matches = [
                candidate for candidate in labels.get(_normalize_label(target), []) if candidate != task_id
            ]
            if len(matches) == 1:
                deps.append(matches[0])
                continue
            if len(matches) > 1:
                diagnostics.append(f"task {task_id} has ambiguous dependency reference: {text}")
                continue
            diagnostics.append(f"task {task_id} references unknown dependency: {text}")
        resolved.append(
            {
                "id": task_id,
                "depends_on": list(dict.fromkeys(deps)),
                "source_hash": str(task.get("source_hash", "")),
                "anchor": task.get("anchor") or task_id,
                "contract": task.get("contract"),
                "status": "pending",
                "attempts": 0,
                "receipt": None,
            }
        )
    if diagnostics:
        raise BatchBuildError(diagnostics)
    return resolved


def build_batch_preview(
    task_document: Mapping[str, Any] | Any,
    *,
    base_sha: str = "",
) -> dict[str, Any]:
    """Build a deterministic multi-task DAG preview from a TaskSpec document."""

    if hasattr(task_document, "to_dict"):
        payload = task_document.to_dict()
    elif isinstance(task_document, Mapping):
        payload = dict(task_document)
    else:
        raise TypeError("task_document must be a mapping or expose to_dict()")
    raw_tasks = payload.get("tasks", [])
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise BatchBuildError(["task document contains no tasks"])
    resolved = _resolve_batch_tasks(raw_tasks)
    source_hash = _stable_hash([str(task.get("source_hash", "")) for task in raw_tasks])
    plan_hash = _stable_hash(
        [
            {
                "id": task["id"],
                "depends_on": task["depends_on"],
                "source_hash": task["source_hash"],
            }
            for task in resolved
        ]
    )
    batch = TaskBatch(
        Path("<preview>"),
        cast(list[Mapping[str, Any]], resolved),
        BatchIdentity(source_hash, plan_hash, base_sha),
    )
    return {
        "schema": "simplicio.task-batch-preview/v1",
        "task_count": len(resolved),
        **batch.status(),
    }
