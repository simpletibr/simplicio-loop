#!/usr/bin/env python3
"""Installed single/cross-repo Agent Fabric E2E and measured stress."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import resource
import statistics
import time

from simplicio_loop.agent_fabric import (
    AddressRegistry, FabricAddress, FabricCapability, FabricController,
    HookwallAdapter, build_envelope,
)
from simplicio_loop.coverage_custodian_host import proceed_decision
from simplicio_loop.work_gap_ledger import (
    WorkGap, WorkGapLedger, sha256_evidence, validate_work_gap_snapshot,
)

# Distribution -> importable module for the three installed seats.
PROJECTS = {
    "simplicio-loop": "simplicio_loop",
    "simplicio-mapper": "simplicio_mapper",
    "simplicio-cli": "simplicio",
}


def evidence(kind: str, actor: str):
    return sha256_evidence(kind, f"installed://{kind}", kind.encode(), actor)


def complete(ledger: WorkGapLedger, gap: WorkGap, project: str, commit: str) -> None:
    ledger.assign_owner(gap.key, owner_project=project, owner_agent=f"{project}-owner",
                        actor_id="coverage-seat")
    ledger.transition(gap.key, "PLANNED", actor_id="planner-seat", seat="planner")
    ledger.transition(
        gap.key, "IMPLEMENTED", actor_id=f"{project}-executor", seat="executor",
        executor_id=f"{project}-executor", expected_revision=commit,
        evidence=(evidence("implementation", f"{project}-executor"),),
    )
    ledger.transition(
        gap.key, "VERIFIED", actor_id=f"{project}-verifier", seat="verifier",
        verifier_id=f"{project}-verifier",
        evidence=(evidence("verification", f"{project}-verifier"),
                  evidence("quality", f"{project}-verifier")),
    )
    ledger.transition(
        gap.key, "INTEGRATED", actor_id="integration-seat", seat="integration",
        evidence=(evidence("integration", "integration-seat"),),
    )
    ledger.transition(
        gap.key, "DELIVERED", actor_id=f"{project}-completion", seat="completion",
        completion_auditor_id=f"{project}-completion",
        evidence=(evidence("delivery", f"{project}-completion"),),
        installed_artifact={
            "expected_commit": commit, "installed_commit": commit,
            "sha256": "a" * 64, "match": True,
        },
        source_requery={"commit": commit, "state": "merged"},
    )


def addresses() -> tuple[AddressRegistry, FabricAddress, dict[str, FabricAddress]]:
    registry = AddressRegistry()
    sender = FabricAddress(
        "simplicio-loop", "fabric-router",
        FabricCapability("route", "1", "DEFAULT", "route-contract"), 1, "loop://router",
    )
    registry.register(sender)
    recipients = {}
    for project in PROJECTS:
        item = FabricAddress(
            project, project + "-executor",
            FabricCapability("execute", "1", "MEASURED", "execute-contract"),
            1, project + "://executor",
        )
        registry.register(item)
        recipients[project] = item
    return registry, sender, recipients


def envelope(sender, recipient, index, commit):
    return build_envelope(
        run_id="installed-765", task_id=f"task-{index}", work_item_id=f"work-{index}",
        stage="execution", attempt=1, fence="f1", plan_revision="1",
        sender=sender, recipient=recipient, payload_handle=f"mapper://page/{index}",
        payload_hash=f"payload-{index}", causal_parent="coverage", sequence=index + 1,
        scope="cross-repo", repo=recipient.project, commit=commit, worktree="/tmp/installed-worktree",
        policy_hash="policy-v1", ttl_seconds=120, expected_receipt="fabric-dispatch-receipt/v1",
        evidence_handles=["mapper://atlas", "quality://plan/mandatory"],
        reply_handle="loop://ledger", priority=1, resource_class="write",
    )


def hookwall(root: Path):
    return HookwallAdapter(
        str(root),
        lambda value: proceed_decision(value, phase="pre"),
        lambda value, receipt: proceed_decision(
            value, phase="post", receipt_hash=receipt["receipt_hash"],
        ),
    )


def e2e(root: Path, projects: tuple[str, ...]) -> dict:
    registry, sender, recipients = addresses()
    controller = FabricController(registry, max_attempts=2, max_inflight=20)
    ledger = WorkGapLedger()
    receipts = []
    commits = {
        "simplicio-loop": "677846da1ec75f4b8e7fbb70c68c81707c145b9c",
        "simplicio-mapper": "0387c3c5cf391c4cbfc1aaa4f2005db283ceb534",
        "simplicio-cli": "c" * 40,
    }
    for index, project in enumerate(projects):
        gap = WorkGap(
            "REQ-765", f"AC-{index + 1:04d}",
            expected_evidence=("implementation", "verification", "quality", "integration", "delivery"),
            delivery_target="package:" + project, expected_revision=commits[project],
        )
        ledger.register(gap)
        item = envelope(sender, recipients[project], index, commits[project])
        receipt = controller.fire(
            item, current_fence="f1", hookwall=hookwall(root),
            execute=lambda value, project=project: {
                "status": "FIXED", "project": project,
                "payload_handle": value["payload_handle"], "completion": None,
            },
        )
        receipts.append(receipt)
        complete(ledger, gap, project, commits[project])
    validation = validate_work_gap_snapshot(ledger.snapshot())
    return {
        "projects": list(projects), "fabric_receipts": [item["receipt_digest"] for item in receipts],
        "workers_materialized": registry.workers_materialized,
        "ledger_digest": ledger.digest(), "ledger_valid": validation["ok"],
        "unresolved": len(ledger.unresolved()), "three_seats": True,
        "completion_authority": controller.replay()["completion_authority"],
    }


def stress(root: Path, count: int, repetitions: int) -> dict:
    samples = []
    digests = []
    for repetition in range(repetitions):
        registry, sender, recipients = addresses()
        controller = FabricController(registry, max_attempts=2, max_inflight=20)
        cpu = time.process_time()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        started = time.perf_counter()
        for index in range(count):
            item = envelope(sender, recipients["simplicio-cli"], index, "a" * 40)
            controller.fire(
                item, current_fence="f1", hookwall=hookwall(root),
                execute=lambda value: {"status": "FIXED", "completion": None},
            )
        replay = controller.replay()
        digests.append(__import__("hashlib").sha256(
            json.dumps(replay, sort_keys=True).encode()
        ).hexdigest())
        samples.append({
            "wall_seconds": time.perf_counter() - started,
            "cpu_seconds": time.process_time() - cpu,
            "rss_kib_delta": max(0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - rss),
            "work_items": count, "receipts": len(replay["receipt_digests"]),
            "workers_materialized": registry.workers_materialized,
            "lost": count - len(replay["receipt_digests"]),
        })
    return {
        "samples": samples, "mean_wall_seconds": statistics.mean(item["wall_seconds"] for item in samples),
        "zero_loss": all(item["lost"] == 0 for item in samples),
        "replay_digests": digests,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 3:
        parser.error("at least three repetitions")
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "simplicio.agent-fabric-installed-e2e/v1",
        "classification": "MEASURED_INSTALLED_ARTIFACTS",
        "versions": {name: importlib.metadata.version(name) for name in PROJECTS},
        "module_roots": {
            name: str(Path(__import__(module).__file__).resolve())
            for name, module in PROJECTS.items()
        },
        "single_repo": e2e(root / "single", ("simplicio-loop",)),
        "cross_repo": e2e(root / "cross", ("simplicio-mapper", "simplicio-cli", "simplicio-loop")),
        "stress": {str(count): stress(root / f"stress-{count}", count, args.repetitions)
                   for count in (1, 20, 100, 600)},
        "metrics": {"tokens": None, "tokens_null_reason": "NO_LLM_USED"},
        "local_llm": False,
    }
    Path(args.output).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    if not receipt["single_repo"]["ledger_valid"] or not receipt["cross_repo"]["ledger_valid"]:
        raise SystemExit(1)
    if not all(item["zero_loss"] for item in receipt["stress"].values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
