#!/usr/bin/env python3
"""CLI shell for the #284 planning-receipt / mutation-authority gate.

    python3 scripts/planning_gate.py capture-source --repo owner/name --issue 284 \
        --out .simplicio-loop/loop-runs/<run>/source-snapshot.json
    python3 scripts/planning_gate.py build --run-dir <dir> --task-contract <path> \
        --plan <path> --run-id <id> --attempt <n> [--lease-id L] [--fencing-token F] \
        [--source-snapshot <path from capture-source>]
    python3 scripts/planning_gate.py check --run-dir <dir> --run-id <id> --attempt <n> \
        --task-contract <path> --plan <path> [--lease-id L] [--fencing-token F] \
        [--source-snapshot <path to a FRESH capture-source re-query>]
    python3 scripts/planning_gate.py selftest

`capture-source` at build time freezes the GitHub issue's content hash into the
planning receipt/mutation authority; re-running `capture-source` and passing
its output to `check --source-snapshot` immediately before mutation detects
source drift (the issue/comments changed since planning) and blocks fail-closed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simplicio_loop.intake_contract import build_task_intake, intake_path
from simplicio_loop.plan_contract import validate_plan
from simplicio_loop.planning_gate import (
    build_planning_receipt,
    content_hash,
    evaluate_mutation_authority,
    publish_planning_receipt,
    receipt_path,
    replan_on_drift,
)
from simplicio_loop.source_snapshot import capture_github_issue_snapshot
from simplicio_loop.traceability_matrix import build_matrix, matrix_path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_optional(path: str | None) -> dict | None:
    if not path:
        return None
    return _load(path)


def _source_snapshot_hash(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    return str((snapshot.get("source") or {}).get("snapshot_hash") or "")


def cmd_capture_source(args: argparse.Namespace) -> int:
    """#284 item 1: capture a GitHub issue source snapshot (title/body/labels/
    milestone/assignees/comments -> content hash + revision), fail-closed on any
    `gh` failure. Write it to disk so `build`/`check` can fold its hash into the
    mutation-authority identity tuple (source drift then invalidates authority)."""
    snapshot = capture_github_issue_snapshot(args.repo, args.issue)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    return 0


def _candidate_targets(plan: dict) -> list[str]:
    targets: list[str] = []
    for step in plan.get("steps") or []:
        for raw in (step or {}).get("candidate_targets") or []:
            value = str(raw).replace("\\", "/").strip()
            if value and value not in targets:
                targets.append(value)
    return targets


def _run_impact_audit(plan: dict, repo_path: str) -> dict | None:
    """#284 "impact-map.json artifact": run `scripts/impact_audit.py`'s existing
    dependency/impact audit over the plan's own `candidate_targets` and persist
    the result as part of the planning receipt. Returns ``None`` (no-op, never
    an error) when the plan declares no candidate targets to audit -- e.g. a
    scaffold-only or docs-only plan -- rather than fabricating an empty pass."""
    seeds = _candidate_targets(plan)
    if not seeds:
        return None
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    from impact_audit import audit  # local import: scripts/ has no package __init__

    return audit(Path(repo_path), seeds, seeds)


def _build_intake(args: argparse.Namespace, contract: dict, plan: dict, plan_hash: str,
                  source_snapshot: dict | None) -> dict:
    return build_task_intake(
        run_id=args.run_id, attempt=args.attempt, contract=contract, plan_hash=plan_hash,
        lease_id=args.lease_id, fencing_token=args.fencing_token,
        source_snapshot=source_snapshot, repo_state=dict(plan.get("repo_state") or {}),
    )


def cmd_build(args: argparse.Namespace) -> int:
    contract = _load(args.task_contract)
    plan = _load(args.plan)
    tasks = contract.get("tasks") or []
    plan_validation = validate_plan(
        plan, tasks, args.repo or ".",
        contract_hash=contract.get("collection_hash", ""),
    )
    source_snapshot = _load_optional(args.source_snapshot)
    plan_hash = content_hash(plan)

    intake = _build_intake(args, contract, plan, plan_hash, source_snapshot)
    matrix = build_matrix(contract, plan)
    impact_map = _run_impact_audit(plan, args.repo or ".")

    receipt = build_planning_receipt(
        run_id=args.run_id, attempt=args.attempt, contract=contract, plan=plan,
        plan_validation=plan_validation, lease_id=args.lease_id, fencing_token=args.fencing_token,
        source_snapshot=source_snapshot, intake=intake, impact_map=impact_map,
        traceability_matrix=matrix,
    )
    out = receipt_path(args.run_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    intake_path(args.run_dir).write_text(json.dumps(intake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matrix_path(args.run_dir).write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if impact_map is not None:
        (Path(args.run_dir) / "impact-map.json").write_text(
            json.dumps(impact_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if args.publish and receipt.get("source"):
        # #284: project the just-built receipt onto the #285 canonical status
        # comment (PLANNED when ready_for_mutation, BLOCKED otherwise) instead of
        # leaving that wiring as a documented-but-disconnected capability.
        from simplicio_loop.pr_evidence import publish_comment

        lifecycle_receipt = publish_planning_receipt(receipt, publish_comment_fn=publish_comment)
        if lifecycle_receipt is not None:
            print(json.dumps(lifecycle_receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["ready_for_mutation"] else 1


def cmd_check(args: argparse.Namespace) -> int:
    contract = _load(args.task_contract)
    plan = _load(args.plan)
    task_contract_hash = str(contract.get("collection_hash") or content_hash(contract))
    plan_hash = content_hash(plan)
    current_source_snapshot = _load_optional(args.source_snapshot)
    verdict = evaluate_mutation_authority(
        args.run_dir, run_id=args.run_id, attempt=args.attempt,
        task_contract_hash=task_contract_hash, plan_hash=plan_hash,
        lease_id=args.lease_id, fencing_token=args.fencing_token,
        source_snapshot_hash=_source_snapshot_hash(current_source_snapshot),
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["ok"] else 1


def cmd_replan(args: argparse.Namespace) -> int:
    """#284 Fase 6: re-run planning against a FRESH task-contract/plan (already
    re-derived by the caller for the current source/repo state) and emit a new
    receipt with a bumped `plan_revision` + a `replan.diff` block, instead of
    leaving `check`'s fail-closed BLOCKED as a dead end with no recovery path."""
    contract = _load(args.task_contract)
    plan = _load(args.plan)
    tasks = contract.get("tasks") or []
    plan_validation = validate_plan(
        plan, tasks, args.repo or ".",
        contract_hash=contract.get("collection_hash", ""),
    )
    baseline_source_snapshot = _load_optional(args.baseline_source_snapshot)
    current_source_snapshot = _load_optional(args.source_snapshot)
    plan_hash = content_hash(plan)

    intake = _build_intake(args, contract, plan, plan_hash, current_source_snapshot)
    matrix = build_matrix(contract, plan)
    impact_map = _run_impact_audit(plan, args.repo or ".")

    receipt = replan_on_drift(
        args.run_dir, run_id=args.run_id, attempt=args.attempt, contract=contract, plan=plan,
        plan_validation=plan_validation, lease_id=args.lease_id, fencing_token=args.fencing_token,
        baseline_source_snapshot=baseline_source_snapshot, current_source_snapshot=current_source_snapshot,
        intake=intake, impact_map=impact_map, traceability_matrix=matrix,
    )
    intake_path(args.run_dir).write_text(json.dumps(intake, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    matrix_path(args.run_dir).write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if impact_map is not None:
        (Path(args.run_dir) / "impact-map.json").write_text(
            json.dumps(impact_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["ready_for_mutation"] else 1


def cmd_selftest(_args: argparse.Namespace) -> int:
    import tempfile

    from simplicio_loop.planning_gate import (
        mutation_authority_token,
        verify_mutation_authority,
    )

    with tempfile.TemporaryDirectory() as tmp:
        run_dir = Path(tmp)

        contract = {"schema": "simplicio.task-contract-collection/v1", "collection_hash": "abc123",
                    "tasks": [{"id": "T1", "scenarios": [], "rules": []}]}
        plan = {
            "schema": "simplicio.plan/v1",
            "task_contract_hash": "abc123",
            "mapper_pack_hash": "mp1",
            "context_pack_hash": "mp1",
            "repo_state": {"head": "h1", "tree_hash": "t1"},
            "freshness": {"verified": True, "current_state": {"head": "h1", "tree_hash": "t1"}},
            "steps": [{"candidate_targets": ["a.py"], "to_create": ["a.py"], "steps": []}],
        }
        plan_validation = validate_plan(plan, contract["tasks"], str(run_dir),
                                        contract_hash=contract["collection_hash"],
                                        current_state={"head": "h1", "tree_hash": "t1"})
        assert plan_validation["valid"], plan_validation["errors"]

        receipt = build_planning_receipt(run_id="run-1", attempt=1, contract=contract, plan=plan,
                                         plan_validation=plan_validation, lease_id="lease-1",
                                         fencing_token="7")
        assert receipt["ready_for_mutation"] is True
        assert receipt["mutation_authority"]

        (run_dir / "planning-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

        task_contract_hash = receipt["task_contract_hash"]
        plan_hash = receipt["plan_hash"]

        ok = evaluate_mutation_authority(run_dir, run_id="run-1", attempt=1,
                                         task_contract_hash=task_contract_hash, plan_hash=plan_hash,
                                         lease_id="lease-1", fencing_token="7")
        assert ok["ok"] is True, ok

        # a stale plan hash (repo/plan changed after planning) invalidates the authority
        stale = evaluate_mutation_authority(run_dir, run_id="run-1", attempt=1,
                                            task_contract_hash=task_contract_hash, plan_hash="different",
                                            lease_id="lease-1", fencing_token="7")
        assert stale["ok"] is False and stale["reason_code"] == "mutation_authority_invalid", stale

        # a rotated lease/fence (lost lease, new attempt owner) invalidates the authority
        # with a distinct verdict (LEASE_LOST / lease_or_fence_mismatch) so callers can
        # tell a stale plan hash apart from a lost lease — see #284 verdict codes.
        rotated = evaluate_mutation_authority(run_dir, run_id="run-1", attempt=1,
                                              task_contract_hash=task_contract_hash, plan_hash=plan_hash,
                                              lease_id="lease-2", fencing_token="8")
        assert rotated["ok"] is False and rotated["verdict"] == "LEASE_LOST" \
            and rotated["reason_code"] == "lease_or_fence_mismatch", rotated

        # missing receipt fails closed
        missing = evaluate_mutation_authority(Path(tmp) / "nope", run_id="run-1", attempt=1,
                                              task_contract_hash=task_contract_hash, plan_hash=plan_hash)
        assert missing["ok"] is False and missing["reason_code"] == "planning_receipt_missing", missing

        # #284 item 1: a GitHub source snapshot folded into the receipt at build time,
        # then a DIFFERENT snapshot captured just before mutation, must block on drift.
        source_snapshot_a = {"schema": "simplicio.source-snapshot/v1",
                              "source": {"provider": "github", "repo": "acme/repo", "item_id": "284",
                                         "revision": "2026-01-01T00:00:00Z#comments=0",
                                         "snapshot_hash": "hash-a", "observed_at": "2026-01-01T00:00:00Z"}}
        source_snapshot_b = {"schema": "simplicio.source-snapshot/v1",
                              "source": {"provider": "github", "repo": "acme/repo", "item_id": "284",
                                         "revision": "2026-01-02T00:00:00Z#comments=1",
                                         "snapshot_hash": "hash-b", "observed_at": "2026-01-02T00:00:00Z"}}
        receipt_with_source = build_planning_receipt(
            run_id="run-src", attempt=1, contract=contract, plan=plan,
            plan_validation=plan_validation, source_snapshot=source_snapshot_a,
        )
        assert receipt_with_source["ready_for_mutation"] is True
        assert receipt_with_source["source"]["snapshot_hash"] == "hash-a"
        (run_dir / "planning-receipt.json").write_text(json.dumps(receipt_with_source), encoding="utf-8")

        unchanged = evaluate_mutation_authority(
            run_dir, run_id="run-src", attempt=1,
            task_contract_hash=receipt_with_source["task_contract_hash"],
            plan_hash=receipt_with_source["plan_hash"], source_snapshot_hash="hash-a",
        )
        assert unchanged["ok"] is True, unchanged

        drifted = evaluate_mutation_authority(
            run_dir, run_id="run-src", attempt=1,
            task_contract_hash=receipt_with_source["task_contract_hash"],
            plan_hash=receipt_with_source["plan_hash"], source_snapshot_hash="hash-b",
        )
        assert drifted["ok"] is False and drifted["reason_code"] == "source_drift", drifted
        assert source_snapshot_b["source"]["snapshot_hash"] != source_snapshot_a["source"]["snapshot_hash"]

        # restore the no-source receipt for the remaining assertions below
        (run_dir / "planning-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

        # an unready plan (validation failed) never mints an authority
        bad_plan_validation = dict(plan_validation, valid=False, errors=["task_step_count_mismatch"])
        bad_receipt = build_planning_receipt(run_id="run-1", attempt=1, contract=contract, plan=plan,
                                             plan_validation=bad_plan_validation)
        assert bad_receipt["ready_for_mutation"] is False
        assert bad_receipt["mutation_authority"] == ""

        # token determinism sanity
        t1 = mutation_authority_token(run_id="r", attempt=1, task_contract_hash="c", plan_hash="p")
        t2 = mutation_authority_token(run_id="r", attempt=1, task_contract_hash="c", plan_hash="p")
        assert t1 == t2
        assert verify_mutation_authority(t1, run_id="r", attempt=1, task_contract_hash="c", plan_hash="p")
        assert not verify_mutation_authority(t1, run_id="r", attempt=2, task_contract_hash="c", plan_hash="p")

        # -- #284 follow-up gaps: task-intake envelope, AC-matrix, impact-map, replan --
        scn_contract = {
            "schema": "simplicio.task-contract-collection/v1", "collection_hash": "scn1",
            "tasks": [{
                "id": "T1",
                "scenarios": [{"id": "SCN1", "title": "Faz X", "given": [], "when": [], "then": [],
                               "rule_refs": ["RN1"]}],
                "rules": [{"id": "RN1", "text": "regra", "scenario_refs": ["SCN1"]}],
            }],
        }
        scn_plan_covered = {
            "schema": "simplicio.plan/v1", "task_contract_hash": "scn1",
            "mapper_pack_hash": "mp1", "context_pack_hash": "mp1",
            "repo_state": {"head": "h1", "tree_hash": "t1"},
            "freshness": {"verified": True, "current_state": {"head": "h1", "tree_hash": "t1"}},
            "steps": [{
                "id": "T1", "candidate_targets": ["a.py"], "to_create": ["a.py"], "rule_ids": ["RN1"],
                "steps": [{"scenario_id": "SCN1", "rule_ids": ["RN1"],
                          "plan": {"read_paths": ["a.py"], "change_paths": ["a.py"],
                                   "test_commands": ["pytest tests/test_a.py"]}}],
            }],
        }

        from simplicio_loop.intake_contract import build_task_intake, lint_task_intake
        from simplicio_loop.traceability_matrix import build_matrix

        intake = build_task_intake(run_id="run-2", attempt=1, contract=scn_contract,
                                   plan_hash=content_hash(scn_plan_covered), lease_id="lease-9",
                                   fencing_token="1", delivery_target="verified")
        assert intake["schema"] == "simplicio.task-intake/v1"
        assert [ac["id"] for ac in intake["acceptance_criteria"]] == ["SCN1"]
        lint = lint_task_intake(intake)
        assert lint["valid"] is True, lint
        empty_intake = dict(intake, acceptance_criteria=[])
        empty_lint = lint_task_intake(empty_intake)
        assert empty_lint["valid"] is False and "no_acceptance_criteria" in empty_lint["errors"], empty_lint

        matrix_covered = build_matrix(scn_contract, scn_plan_covered)
        assert matrix_covered["coverage_ok"] is True, matrix_covered
        assert matrix_covered["rows"][0]["ac_id"] == "SCN1"
        assert matrix_covered["rows"][0]["test_commands"] == ["pytest tests/test_a.py"]

        scn_plan_gap = json.loads(json.dumps(scn_plan_covered))
        scn_plan_gap["steps"][0]["steps"][0]["plan"]["test_commands"] = []
        matrix_gap = build_matrix(scn_contract, scn_plan_gap)
        assert matrix_gap["coverage_ok"] is False and matrix_gap["gaps"] == ["SCN1"], matrix_gap

        scn_plan_validation = validate_plan(scn_plan_covered, scn_contract["tasks"], str(run_dir),
                                            contract_hash=scn_contract["collection_hash"],
                                            current_state={"head": "h1", "tree_hash": "t1"})
        assert scn_plan_validation["valid"], scn_plan_validation["errors"]

        # a receipt built with a GAPPED matrix is NOT ready for mutation even
        # though plan_validation itself passed -- the matrix is an independent gate.
        gapped_receipt = build_planning_receipt(run_id="run-2", attempt=1, contract=scn_contract,
                                                plan=scn_plan_covered, plan_validation=scn_plan_validation,
                                                traceability_matrix=matrix_gap)
        assert gapped_receipt["ready_for_mutation"] is False, gapped_receipt
        assert gapped_receipt["traceability_summary"]["gaps"] == ["SCN1"]

        # a receipt built with a COVERED matrix stays ready
        covered_receipt = build_planning_receipt(run_id="run-2", attempt=1, contract=scn_contract,
                                                 plan=scn_plan_covered, plan_validation=scn_plan_validation,
                                                 traceability_matrix=matrix_covered, intake=intake)
        assert covered_receipt["ready_for_mutation"] is True, covered_receipt
        assert covered_receipt["intake_hash"] == intake["intake_hash"]

        # -- genuine replan-on-drift: previous receipt on disk, source drifted --
        replan_dir = Path(tmp) / "replan"
        replan_dir.mkdir()
        first_receipt = build_planning_receipt(
            run_id="run-replan", attempt=1, contract=scn_contract, plan=scn_plan_covered,
            plan_validation=scn_plan_validation, source_snapshot=source_snapshot_a,
        )
        receipt_path(replan_dir).write_text(json.dumps(first_receipt), encoding="utf-8")
        assert first_receipt.get("plan_revision", 0) == 0

        replanned = replan_on_drift(
            replan_dir, run_id="run-replan", attempt=2, contract=scn_contract, plan=scn_plan_covered,
            plan_validation=scn_plan_validation, baseline_source_snapshot=source_snapshot_a,
            current_source_snapshot=source_snapshot_b,
        )
        assert replanned["plan_revision"] == 1, replanned
        assert replanned["replan"]["replanned"] is True
        assert replanned["replan"]["drift_detected"] is True
        assert replanned["replan"]["diff"]["source_snapshot_before"] == "hash-a"
        assert replanned["replan"]["diff"]["source_snapshot_after"] == "hash-b"
        assert replanned["ready_for_mutation"] is True
        on_disk = json.loads(receipt_path(replan_dir).read_text(encoding="utf-8"))
        assert on_disk["plan_revision"] == 1

        # a second replan against the SAME unchanged source keeps bumping the
        # revision but reports no drift
        stable = replan_on_drift(
            replan_dir, run_id="run-replan", attempt=3, contract=scn_contract, plan=scn_plan_covered,
            plan_validation=scn_plan_validation, baseline_source_snapshot=source_snapshot_b,
            current_source_snapshot=source_snapshot_b,
        )
        assert stable["plan_revision"] == 2, stable
        assert stable["replan"]["drift_detected"] is False, stable

    print("selftest: PASS planning-gate")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planning_gate")
    sub = parser.add_subparsers(dest="verb", required=True)

    p_capture = sub.add_parser("capture-source")
    p_capture.add_argument("--repo", required=True, help="owner/name")
    p_capture.add_argument("--issue", required=True)
    p_capture.add_argument("--out", required=True, help="path to write the source-snapshot JSON")
    p_capture.set_defaults(func=cmd_capture_source)

    p_build = sub.add_parser("build")
    p_build.add_argument("--run-dir", required=True)
    p_build.add_argument("--task-contract", required=True)
    p_build.add_argument("--plan", required=True)
    p_build.add_argument("--repo", default=".")
    p_build.add_argument("--run-id", required=True)
    p_build.add_argument("--attempt", type=int, required=True)
    p_build.add_argument("--lease-id", default="")
    p_build.add_argument("--fencing-token", default="")
    p_build.add_argument("--source-snapshot", default="", help="path to a source-snapshot JSON from capture-source")
    p_build.add_argument("--publish", action="store_true",
                         help="also publish the receipt verdict (PLANNED/BLOCKED) to the canonical "
                              "GitHub status comment via github_lifecycle.publish_lifecycle_state()")
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("check")
    p_check.add_argument("--run-dir", required=True)
    p_check.add_argument("--task-contract", required=True)
    p_check.add_argument("--plan", required=True)
    p_check.add_argument("--run-id", required=True)
    p_check.add_argument("--attempt", type=int, required=True)
    p_check.add_argument("--lease-id", default="")
    p_check.add_argument("--fencing-token", default="")
    p_check.add_argument("--source-snapshot", default="", help="path to a FRESH source-snapshot JSON to detect drift")
    p_check.set_defaults(func=cmd_check)

    p_replan = sub.add_parser("replan")
    p_replan.add_argument("--run-dir", required=True)
    p_replan.add_argument("--task-contract", required=True, help="FRESH task contract, re-derived for current source/repo state")
    p_replan.add_argument("--plan", required=True, help="FRESH plan, re-derived for current source/repo state")
    p_replan.add_argument("--repo", default=".")
    p_replan.add_argument("--run-id", required=True)
    p_replan.add_argument("--attempt", type=int, required=True)
    p_replan.add_argument("--lease-id", default="")
    p_replan.add_argument("--fencing-token", default="")
    p_replan.add_argument("--baseline-source-snapshot", default="", help="the source-snapshot the PREVIOUS receipt was built from")
    p_replan.add_argument("--source-snapshot", default="", help="a FRESH source-snapshot capture, to compute the drift diff")
    p_replan.set_defaults(func=cmd_replan)

    p_self = sub.add_parser("selftest")
    p_self.set_defaults(func=cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
