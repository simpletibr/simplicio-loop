"""Live composition root for ``simplicio tasks run``."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable, Sequence

from .worktree_queue import TaskSpec, WorktreeQueue
from .github_drain_intake import GitHubDrainIntake, ReadOnlyLocalGitMap, parse_natural_drain_request
from .source_adapter import GitHubSourceAdapter
from .tasks_materializer import LoopRunContractMaterializer
from .tasks_orchestrator import TasksOrchestrator
from .tasks_stage_pipeline import CommandPipelineCoordinator

def _forbidden_publish(*args, **kwargs):
    raise RuntimeError("tasks intake is read-only")

def run_live(
    request: str,
    *,
    workspace: str,
    agent_command: Sequence[str],
    action_gate: bool,
    dry_run: bool = False,
    cancel: bool = False,
    checkpoint: str = "",
    max_workers: int = 0,
    retry_budget: int = 1,
    source_factory: Callable[..., Any] = GitHubSourceAdapter,
    intake_factory: Callable[..., Any] = GitHubDrainIntake,
    materializer_factory: Callable[..., Any] = LoopRunContractMaterializer,
    pipeline_factory: Callable[..., Any] = CommandPipelineCoordinator,
    orchestrator_factory: Callable[..., Any] = TasksOrchestrator,
    queue_factory: Callable[..., Any] = WorktreeQueue,
) -> dict[str, Any]:
    root = Path(workspace).resolve()
    if max_workers <= 0:
        from .economy_profile import recommend_operator_workers
        max_workers = recommend_operator_workers()
    batch = hashlib.sha256(request.encode("utf-8")).hexdigest()[:16]
    journal_dir = root / ".simplicio-loop" / "tasks-run" / batch / "journals"
    cancel_path = journal_dir / "cancel.json"
    if dry_run:
        if cancel:
            return {
                "schema": "simplicio.tasks-orchestrator/v1",
                "plan": None,
                "idempotency_key": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                "state": "blocked",
                "reason": "dry_run_read_only",
                "cancelled": [],
                "evidence": [],
                "dry_run": True,
            }
        if cancel_path.exists():
            return {
                "schema": "simplicio.tasks-orchestrator/v1",
                "plan": None,
                "idempotency_key": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                "state": "cancelled",
                "reason": "persisted_cancel_observed",
                "cancelled": ["persisted_cancel"],
                "evidence": [],
                "dry_run": True,
            }
        # The orchestrator's existing action-gate-closed path is the
        # read-only production dry-run implementation.
        action_gate = False
    if cancel:
        journal_dir.mkdir(parents=True, exist_ok=True)
        cancel_path.write_text('{"reason":"cancel_requested","schema":"simplicio.tasks-cancel/v1"}', encoding="utf-8")
        return {
            "schema": "simplicio.tasks-orchestrator/v1",
            "plan": None,
            "idempotency_key": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "state": "cancelled",
            "reason": "cancel_requested",
            "cancelled": ["cancel_requested"],
            "evidence": [],
        }
    if cancel_path.exists():
        acknowledged = journal_dir / "cancel.ack.json"
        try:
            cancel_path.replace(acknowledged)
        except FileNotFoundError:
            pass  # Another invocation consumed this one-shot STOP first.
        else:
            return {"schema": "simplicio.tasks-orchestrator/v1", "plan": None,
                    "idempotency_key": hashlib.sha256(request.encode("utf-8")).hexdigest(),
                    "state": "cancelled", "reason": "persisted_cancel_enforced",
                    "cancelled": ["persisted_cancel"], "cancel_ack": str(acknowledged),
                    "evidence": []}
    # The production orchestrator already stops after read-only intake when the
    # action gate is closed.  Do not construct the agent-backed pipeline first:
    # its constructor correctly rejects an empty command, but dry-run must not
    # require or even initialize an agent.
    pipeline = None if dry_run else pipeline_factory(
        agent_command, str(journal_dir), host_total_slots=max_workers + 1
    )
    intent = parse_natural_drain_request(request)
    checkpoint_path = checkpoint or str(root / ".simplicio-loop" / "tasks-run" / batch / "intake.json")
    source = source_factory(intent.owner, intent.repo, publish_comment_fn=_forbidden_publish)
    intake = intake_factory(source=source, checkpoint=checkpoint_path, workspace=str(root), map_reader=ReadOnlyLocalGitMap())
    materializer = materializer_factory(str(root))
    holder = {}

    def contracts(plan):
        rows = materializer(plan)
        queue = queue_factory(repo_root=str(root), run_id=f"tasks-{batch}", state_path=str(root / ".simplicio-loop" / "tasks-run" / batch / "worktree-queue.json"), worktree_root=str(root / ".simplicio-loop" / "tasks-worktrees" / batch))
        specs = [TaskSpec(id=row["task_id"], goal=row["task_spec"]["goal"], files_affected=list(row["task_spec"]["files_affected"])) for row in rows]
        queue.register_tasks(specs)
        holder["orchestrator"].worktree_queue = queue
        return rows

    orchestrator = orchestrator_factory(intake, contracts, pipeline, max_workers=max_workers, retry_budget=retry_budget, journal_dir=str(journal_dir))
    holder["orchestrator"] = orchestrator
    return orchestrator.run(request, action_gate=action_gate, cancel=cancel)
