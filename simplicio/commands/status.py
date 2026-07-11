"""``simplicio-py status`` — show current simplicio-py run state.

Extracted from `cli.py`'s `_run_status_command`/`_status_claims_gate`
(issue #103); behavior unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

CLI_PROG = "simplicio-py"


def status_claims_gate(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a low-risk claim contract for ``status --json`` consumers.

    A persisted sprint state can prove that this adapter recorded a fresh,
    passing local execution for the tracked sprint flow. It still cannot prove
    repo-wide green on its own, so downstream consumers must not escalate that
    broader claim from a single status payload.
    """

    failed_features = payload.get("failed_features")
    failed_dod_gates = payload.get("failed_dod_gates")
    state = payload.get("state") or ("complete" if payload.get("complete") else "in-progress")
    has_fresh_passing_state = (
        bool(payload.get("complete")) and state == "complete" and not failed_features and not failed_dod_gates
    )
    if not has_fresh_passing_state:
        return {
            "allow_fresh_verification_claim": False,
            "allow_repo_green_claim": False,
            "proof_scope": "none",
            "reason": "fresh passing verification evidence is not available",
        }
    return {
        "allow_fresh_verification_claim": True,
        "allow_repo_green_claim": False,
        "proof_scope": "sprint_state",
        "reason": (
            "last passing evidence came from the stored sprint state; it does not prove repo-wide green"
        ),
    }


def _batch_state(batch_payload: Mapping[str, object]) -> str:
    counts = batch_payload.get("counts", {})
    if not isinstance(counts, Mapping):
        return "in-progress"
    pending = int(counts.get("pending", 0))
    running = int(counts.get("running", 0))
    blocked = int(counts.get("blocked", 0))
    if pending == 0 and running == 0 and blocked == 0:
        return "complete"
    if blocked:
        return "failed"
    return "in-progress"


def run(a: argparse.Namespace) -> int:
    from ..mapper import artifact_status
    from ..orchestrator.multi_task import BatchError, TaskBatch

    root = Path(a.root).resolve()
    state_path = root / ".simplicio" / "sprint_state.json"
    batch_path = root / ".simplicio" / "task_batch.json"
    batch_payload = None
    if batch_path.is_file():
        try:
            batch_payload = TaskBatch.load(batch_path).status()
        except BatchError as exc:
            print(f"{CLI_PROG} status: invalid task batch file: {exc}", file=sys.stderr)
            return 2
    if not state_path.is_file():
        if batch_payload is not None:
            payload = {
                "schema": "simplicio.dev-cli.status/v1",
                "root": str(root),
                "state": _batch_state(batch_payload),
                "path": str(batch_path),
                "task_batch": batch_payload,
                "artifacts": artifact_status(root),
            }
            payload["claims_gate"] = status_claims_gate(payload)
            if a.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                counts = batch_payload.get("counts", {})
                passed = counts.get("passed", 0) if isinstance(counts, Mapping) else 0
                total = sum(int(value) for value in counts.values()) if isinstance(counts, Mapping) else 0
                ready = batch_payload.get("ready", [])
                ready_count = len(ready) if isinstance(ready, list) else 0
                print(f"{payload['state']}: task batch {passed}/{total} passed ready={ready_count}")
            return 0
        payload = {
            "schema": "simplicio.dev-cli.status/v1",
            "root": str(root),
            "state": "none",
            "path": str(state_path),
            "artifacts": artifact_status(root),
        }
        payload["claims_gate"] = status_claims_gate(payload)
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"no simplicio sprint state at {state_path}")
        return 0
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{CLI_PROG} status: invalid state file: {exc}", file=sys.stderr)
        return 2
    json_payload = {
        "schema": "simplicio.dev-cli.status/v1",
        "root": str(root),
        **payload,
        "artifacts": artifact_status(root),
    }
    if batch_payload is not None:
        json_payload["task_batch"] = batch_payload
    json_payload["claims_gate"] = status_claims_gate(json_payload)
    if a.json:
        print(json.dumps(json_payload, sort_keys=True))
        return 0
    completed = payload.get("completed_features", 0)
    total = payload.get("total_features", 0)
    state = payload.get("state") or ("complete" if payload.get("complete") else "in-progress")
    if payload.get("failed_features") or payload.get("failed_dod_gates"):
        state = "failed"
    cost_suffix = ""
    cost = payload.get("cost")
    if isinstance(cost, dict):
        spent = cost.get("spent_usd")
        budget = cost.get("budget_usd")
        if spent is not None and budget is not None:
            cost_suffix = f" cost={spent}/{budget}"
    print(f"{state}: {payload.get('sprint', 'sprint')} {completed}/{total} features{cost_suffix}")
    for failed in payload.get("failed_features", []):
        print(f"failed: {failed}", file=sys.stderr)
    for failed in payload.get("failed_dod_gates", []):
        print(f"failed DoD: {failed}", file=sys.stderr)
    return 0
