"""`oracle`, `checkpoint`, `maintenance-deferred`, `deliver`, `decide` and `sync-source`.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
import json

from ._base import impl

from ..checkpoint_lifecycle import CheckpointLifecycle
from ..checkpoint_lifecycle import LifecycleError

def checkpoint_lifecycle(args) -> int:
    root = Path(args.repo).resolve()
    lifecycle = CheckpointLifecycle(
        root / ".simplicio-loop" / "loop-runs",
        task_id=args.task_id,
        attempt_id=args.attempt_id,
        source_commit=args.source_commit,
        mapper_generation=args.mapper_generation,
        base_path=args.base_path or root,
    )
    try:
        if args.lifecycle_action == "inspect":
            payload = lifecycle.load(args.candidate_id, args.shard_id)
        elif args.lifecycle_action == "cancel":
            payload = lifecycle.cancel(args.candidate_id, reason=args.reason)
        elif args.lifecycle_action == "gc":
            payload = lifecycle.gc(
                retention_ns=max(0, args.retention_seconds) * 1_000_000_000,
                apply=args.apply,
            )
        else:
            raise LifecycleError("unsupported lifecycle action")
    except (LifecycleError, OSError, ValueError) as exc:
        payload = {"schema": "simplicio.loop.checkpoint-lifecycle/v1",
                   "status": "HELD", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def oracle(loop_dir: str, run_dir: str, response_text: str, flow_gap: str,
           write_receipt: bool) -> int:
    """Evaluate the shared completion oracle and its cross-runtime parity."""
    payload = impl().evaluate_matrix(loop_dir, run_dir, response_text=response_text, flow_gap=flow_gap)
    if write_receipt:
        # Persist the canonical verdict once; the matrix is only the parity proof.
        from ..oracle import evaluate_completion
        verdict = evaluate_completion(loop_dir, run_dir, response_text=response_text,
                                      flow_gap=flow_gap)
        payload["receipt_path"] = impl().persist_completion_receipt(verdict, loop_dir, run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("parity") and payload.get("signature", [False])[0] else 1


def maintenance_deferred(repo: str, run_id: str, mode: str, disposition: str,
                         correction_summary: str, deferral_reason: str,
                         resume_instructions: list[str], evidence_status: str) -> int:
    if mode != "maintenance_deferred" or disposition != "backlog_only":
        print(json.dumps({
            "ready": False,
            "reason_code": "maintenance_mode_invalid",
            "tag": "UNVERIFIED",
        }, ensure_ascii=False, sort_keys=True))
        return 2
    payload = impl().defer_maintenance_backlog_only(
        repo,
        run_id,
        correction_summary=correction_summary,
        deferral_reason=deferral_reason,
        resume_instructions=resume_instructions,
        evidence_status=evidence_status,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def deliver(repo: str, run_id: str, state: str, source_kind: str, payload_file: str) -> int:
    source_payload = {}
    if payload_file:
        source_payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
    payload = impl().reconcile_delivery(repo, run_id, state, source_kind=source_kind, source_payload=source_payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def decide(repo: str, run_id: str, decision_id: str, answer: str, impact: str) -> int:
    payload = impl().apply_human_decision(repo, run_id, decision_id, answer, impact=impact)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def sync_source(repo: str, run_id: str, source: str, external_repo: str, pr: int, tag: str) -> int:
    payload = impl().sync_source_state(repo, run_id, source, external_repo=external_repo, pr=pr or None, tag=tag)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def add_oracle(sub):
    p_oracle = sub.add_parser("oracle", help="evaluate completion and cross-runtime parity")
    p_oracle.add_argument("--loop-dir", default=impl().os.path.join(".simplicio-loop/orchestrator", "loop"))
    p_oracle.add_argument("--run-dir", default=impl().os.environ.get("SIMPLICIO_RUN_DIR", ""))
    p_oracle.add_argument("--response-text", default="")
    p_oracle.add_argument("--flow-gap", default="")
    p_oracle.add_argument("--write-receipt", action="store_true")


def add_checkpoint(sub):
    p_checkpoint = sub.add_parser(
        "checkpoint", help="inspect, cancel, or garbage-collect candidate checkpoints")
    p_checkpoint.add_argument("lifecycle_action", choices=("inspect", "cancel", "gc"))
    p_checkpoint.add_argument("--repo", default=".")
    p_checkpoint.add_argument("--task-id", required=True)
    p_checkpoint.add_argument("--attempt-id", required=True)
    p_checkpoint.add_argument("--source-commit", required=True)
    p_checkpoint.add_argument("--mapper-generation", required=True)
    p_checkpoint.add_argument("--base-path", default="")
    p_checkpoint.add_argument("--candidate-id", action="append", default=[])
    p_checkpoint.add_argument("--shard-id", default="candidate")
    p_checkpoint.add_argument("--reason", default="operator_cancelled")
    p_checkpoint.add_argument("--retention-seconds", type=int, default=86400)
    p_checkpoint.add_argument("--apply", action="store_true")


def add_maintenance(sub):
    p_maintenance = sub.add_parser(
        "maintenance-deferred",
        aliases=["defer-maintenance"],
        help="record a maintenance-deferred backlog-only transition",
    )
    p_maintenance.add_argument("--repo", default=".", help="repository root")
    p_maintenance.add_argument("run_id", help="run id to update")
    p_maintenance.add_argument(
        "--mode", choices=("active", "maintenance_deferred"), required=True,
        help="explicit runner mode",
    )
    p_maintenance.add_argument(
        "--disposition", choices=("operator", "backlog_only"), required=True,
        help="explicit runner disposition",
    )
    p_maintenance.add_argument("--correction-summary", required=True)
    p_maintenance.add_argument("--deferral-reason", required=True)
    p_maintenance.add_argument("--resume-instruction", action="append", default=[])
    p_maintenance.add_argument("--evidence-status", default="UNVERIFIED")


def add_deliver(sub):
    p_deliver = sub.add_parser("deliver", help="reconcile delivery state against local/external source evidence")
    p_deliver.add_argument("--repo", default=".", help="repository root")
    p_deliver.add_argument("run_id", help="run id to reconcile")
    p_deliver.add_argument("--state", required=True, help="delivery state reached")
    p_deliver.add_argument("--source-kind", default="local", help="source kind for this reconciliation")
    p_deliver.add_argument("--payload-file", default="", help="JSON file with source evidence payload")


def add_decide(sub):
    p_decide = sub.add_parser("decide", help="apply a human decision and invalidate dependent artifacts")
    p_decide.add_argument("--repo", default=".", help="repository root")
    p_decide.add_argument("run_id", help="run id to update")
    p_decide.add_argument("--decision-id", required=True, help="decision/question identifier")
    p_decide.add_argument("--answer", required=True, help="human answer")
    p_decide.add_argument("--impact", default="behavior-change", help="impact classification")


def add_sync_source(sub):
    p_sync = sub.add_parser("sync-source", help="requery external source state and reconcile delivery")
    p_sync.add_argument("--repo", default=".", help="repository root")
    p_sync.add_argument("run_id", help="run id to update")
    p_sync.add_argument("--source", required=True, help="external source kind")
    p_sync.add_argument("--external-repo", default="", help="external repo identifier, ex owner/name")
    p_sync.add_argument("--pr", type=int, default=0, help="pull request number")
    p_sync.add_argument("--tag", default="", help="release tag")
