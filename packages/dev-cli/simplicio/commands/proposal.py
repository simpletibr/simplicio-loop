"""``simplicio-py proposal`` -- compile a canonical, non-mutating proposal."""

from __future__ import annotations

import json


def run(a) -> int:
    from ..pipeline import run_task
    from ..precedent import auto_detect_stack
    from .task import _task_arguments

    args = _task_arguments(a)
    if args is None:
        return 2
    goal, target, criteria, constraints, task_spec = args
    result = run_task(
        a.root,
        auto_detect_stack(a.root, a.stack),
        goal,
        target,
        criteria,
        constraints,
        bound_paths=a.bound_paths,
        quiet=True,
        mode="integrated",
        proposal_only=True,
        task_spec=task_spec,
        context_snapshot_path=getattr(a, "context_snapshot", None),
        context_pack_path=getattr(a, "context_pack", None),
        execution_context_path=getattr(a, "execution_context", None),
        authorization_path=getattr(a, "effect_authorization", None),
        attempt_id=getattr(a, "attempt_id", None),
        lease_id=getattr(a, "lease_id", None),
        fencing_token=getattr(a, "fencing_token", None),
        context_handle=getattr(a, "context_handle", None),
        coordinator_kind=getattr(a, "coordinator_kind", None),
        coordinator_id=getattr(a, "coordinator_id", None),
        repo_root=getattr(a, "repo_root", None),
        scope_root=getattr(a, "scope_root", None),
        context_snapshot_id=getattr(a, "context_snapshot_id", None),
        context_pack_hash=getattr(a, "context_pack_hash", None),
    )
    proposal = result.get("proposal")
    if result.get("status") == "proposal_only" and isinstance(proposal, dict):
        print(json.dumps(proposal, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 1
