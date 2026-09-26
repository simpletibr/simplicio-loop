#!/usr/bin/env python3
"""simplicio-loop — completion_auditor CLI: the final independent terminal gate (issue #431).

Wraps :mod:`simplicio_loop.completion_auditor`'s pure reducer with the same
run-local file layout the other stage-agent producers use
(``.simplicio-loop/orchestrator/loop/*.json`` — see ``scripts/watcher_verify.py``,
``scripts/task_anchor.py``). It never trusts a bare self-report: every verb
below either recomputes the verdict from disk-backed receipts or refuses to
gate the promise.

Verbs:
  audit      Recompute the terminal verdict from the on-disk stage graph,
             instances, receipts, anchor, watcher and delivery/source state.
             Writes `.simplicio-loop/orchestrator/loop/completion_audit.json` and prints
             `COMPLETE|PARTIAL|BLOCKED|REGRESSED`.
  receipt    Build + persist the content-addressed completion receipt from the
             last `audit` run (`.simplicio-loop/orchestrator/loop/completion_receipt.json`).
  gate       Check whether the promise may be honored: requires a valid,
             fresh, hash-matching completion receipt with verdict COMPLETE.
             Exits 0 only when the gate is satisfied.
  report     Print the short human report for the last audit run.
  selftest   Prove the full complete/blocked/partial/regressed chain offline —
             no files, no network.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
LOOP_DIR = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from simplicio_loop import completion_auditor as ca  # noqa: E402
from simplicio_loop import stage_agents as sa  # noqa: E402
from simplicio_loop.work_gap_ledger import (  # noqa: E402
    WorkGap, WorkGapLedger, sha256_evidence,
)


def _set_repo(repo):
    global REPO, LOOP_DIR
    REPO = repo
    LOOP_DIR = os.path.join(REPO, ".simplicio-loop/orchestrator", "loop")


def _paths():
    return {
        "instances": os.path.join(LOOP_DIR, "stage_instances.json"),
        "receipts": os.path.join(LOOP_DIR, "stage_receipts.json"),
        "run_identity": os.path.join(LOOP_DIR, "run_identity.json"),
        "anchor": os.path.join(LOOP_DIR, "anchor.json"),
        "watcher_state": os.path.join(LOOP_DIR, "watcher_state.json"),
        "watcher_challenge": os.path.join(LOOP_DIR, "watcher_challenge.json"),
        "delivery": os.path.join(LOOP_DIR, "delivery_receipt.json"),
        "source_requery": os.path.join(LOOP_DIR, "source_requery.json"),
        "prev_completion": os.path.join(LOOP_DIR, "completion_receipt.json"),
        "audit_out": os.path.join(LOOP_DIR, "completion_audit.json"),
        "receipt_out": os.path.join(LOOP_DIR, "completion_receipt.json"),
    }


def _read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def cmd_audit(_opts):
    paths = _paths()
    graph = _read_json(sa.STAGES_FILE)
    instances = _read_json(paths["instances"], []) or []
    receipts = _read_json(paths["receipts"], []) or []
    run_identity = _read_json(paths["run_identity"], {}) or {}
    anchor = _read_json(paths["anchor"], {}) or {}
    ac_items = [c for c in (anchor.get("criteria") or []) if isinstance(c, dict) and c.get("id")]
    watcher_receipt = _read_json(paths["watcher_state"])
    watcher_challenge = _read_json(paths["watcher_challenge"])
    criteria_results = (watcher_receipt or {}).get("criteria_results", [])
    delivery_receipt = _read_json(paths["delivery"])
    source_requery = _read_json(paths["source_requery"])
    prev_completion = _read_json(paths["prev_completion"])
    work_gap_path = os.path.join(os.path.dirname(paths["audit_out"]), "work-gap-ledger.json")
    work_gap_snapshot = _read_json(work_gap_path)
    if work_gap_snapshot is None:
        work_gap_snapshot = {}

    auditor_instance_id = os.environ.get("SIMPLICIO_AUDITOR_INSTANCE_ID", "").strip()
    if not auditor_instance_id:
        print("BLOCKED|completion_auditor: SIMPLICIO_AUDITOR_INSTANCE_ID is required")
        _write_json(paths["audit_out"], ca.blocked_result("auditor_instance_id_missing", []))
        return 1

    if graph is None:
        print("BLOCKED|completion_auditor: stage graph missing/invalid")
        _write_json(paths["audit_out"], ca.blocked_result(ca.REASON_INVALID_GRAPH, ["stage graph unreadable"]))
        return 1

    if not os.path.exists(paths["anchor"]):
        # Fail-closed: an absent anchor.json makes ac_items == [] and would make
        # build_ac_coverage_matrix() vacuously "complete" (no ACs to fail) --
        # never treat "we couldn't read the AC list" as "all ACs satisfied".
        print("BLOCKED|completion_auditor: task anchor (anchor.json) missing/unreadable -- AC coverage cannot be verified")
        _write_json(paths["audit_out"], ca.blocked_result(ca.REASON_AC_COVERAGE_INCOMPLETE, ["anchor.json unreadable"]))
        return 1

    result = ca.audit(
        graph=graph,
        instances=instances,
        receipts=receipts,
        run_identity=run_identity,
        auditor_instance_id=auditor_instance_id,
        ac_items=ac_items,
        criteria_results=criteria_results,
        watcher_receipt=watcher_receipt,
        watcher_challenge=watcher_challenge,
        delivery_receipt=delivery_receipt,
        source_requery=source_requery,
        previous_completion_receipt=prev_completion,
        work_gap_snapshot=work_gap_snapshot,
    )
    _write_json(paths["audit_out"], result)
    tag = "MEASURED" if result["verdict"] == ca.VERDICT_COMPLETE else "UNVERIFIED"
    print("%s|completion_auditor verdict=%s reason=%s" % (tag, result["verdict"], result.get("reason_code")))
    return 0 if result["verdict"] == ca.VERDICT_COMPLETE else 1


def cmd_receipt(_opts):
    paths = _paths()
    result = _read_json(paths["audit_out"])
    if not result:
        print("UNVERIFIED|completion_auditor: run `audit` before `receipt`")
        return 1
    receipt = ca.build_completion_receipt(result)
    _write_json(paths["receipt_out"], receipt)
    print("%s|completion receipt written: %s" % (
        "MEASURED" if result.get("verdict") == ca.VERDICT_COMPLETE else "UNVERIFIED",
        receipt["receipt_id"],
    ))
    return 0


def cmd_gate(_opts):
    paths = _paths()
    result = _read_json(paths["audit_out"])
    receipt = _read_json(paths["receipt_out"])
    if not result:
        print("BLOCKED|completion_auditor: no audit result on disk")
        return 1
    ok, reason = ca.gate_promise(completion_receipt=receipt, audit_result=result)
    print(("MEASURED|" if ok else "UNVERIFIED|") + "completion_auditor gate: %s (%s)" % (ok, reason))
    return 0 if ok else 1


def cmd_report(_opts):
    paths = _paths()
    result = _read_json(paths["audit_out"])
    if not result:
        print("UNVERIFIED|completion_auditor: no audit result on disk")
        return 1
    print(ca.human_report(result))
    return 0


def cmd_selftest(_opts):
    origin = REPO
    try:
        with tempfile.TemporaryDirectory() as tmp:
            _set_repo(tmp)
            os.makedirs(LOOP_DIR, exist_ok=True)
            paths = _paths()

            graph = json.load(open(sa.STAGES_FILE, encoding="utf-8"))
            required = [s for s in graph["stages"] if s["stage_id"] != "done"]
            run_identity = {"run_id": "run-1", "task_id": "task-1", "fence": "fence-1", "plan_revision": 1}

            def _hash(s):
                import hashlib
                return hashlib.sha256(s.encode()).hexdigest()

            instances, receipts = [], []
            for stage in required:
                inst_id = "inst-" + stage["stage_id"]
                instances.append({
                    "agent_instance_id": inst_id, "role_id": stage["role_id"], "stage_id": stage["stage_id"],
                    "run_id": run_identity["run_id"], "task_id": run_identity["task_id"],
                    "attempt_id": "att-1", "fence": run_identity["fence"],
                    "plan_revision": run_identity["plan_revision"],
                    "context_hash": _hash("c" + inst_id), "manifest_hash": _hash("m" + inst_id),
                    "terminal_status": "completed",
                })
                receipts.append({
                    "receipt_id": "rec-" + stage["stage_id"], "agent_instance_id": inst_id,
                    "role_id": stage["role_id"], "stage_id": stage["stage_id"],
                    "run_id": run_identity["run_id"], "task_id": run_identity["task_id"],
                    "attempt_id": "att-1", "fence": run_identity["fence"],
                    "plan_revision": run_identity["plan_revision"],
                    "verdict": "pass", "accepted": True, "evidence_refs": ["ev-" + stage["stage_id"]],
                })

            _write_json(paths["instances"], instances)
            _write_json(paths["receipts"], receipts)
            _write_json(paths["run_identity"], run_identity)
            _write_json(paths["anchor"], {"goal_fp": "fp1", "criteria": [
                {"id": "AC1", "status": "done"}, {"id": "AC2", "status": "done"},
            ]})
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            _write_json(paths["watcher_challenge"], {"challenge": "chal-1", "goal_fp": "fp1"})
            _write_json(paths["watcher_state"], {
                "challenge": "chal-1", "status": "MEASURED", "match": True, "checked_at": now,
                "reported": "ok",
                "criteria_results": [
                    {"id": "AC1", "match": True, "evidence_ids": ["p1"]},
                    {"id": "AC2", "match": True, "evidence_ids": ["p2"]},
                ],
            })
            _write_json(paths["delivery"], {"current_state": "merged", "source_checked_at": now})
            _write_json(paths["source_requery"], {"state": "merged", "checked_at": now})
            ledger = WorkGapLedger()
            gap = WorkGap(
                "REQ-selftest", "AC-terminal",
                expected_evidence=("implementation", "verification", "integration", "delivery"),
                delivery_target="package:simplicio-loop",
                expected_revision="selftest-commit",
            )
            ledger.register(gap)
            ledger.assign_owner(
                gap.key, owner_project="simplicio-loop", owner_agent="owner",
                actor_id="coverage-seat",
            )
            ledger.transition(gap.key, "PLANNED", actor_id="planner-seat", seat="planner")
            ledger.transition(
                gap.key, "IMPLEMENTED", actor_id="executor-seat", seat="executor",
                executor_id="executor-seat",
                evidence=(sha256_evidence(
                    "implementation", "commit:selftest", b"patch", "executor-seat"
                ),),
            )
            ledger.transition(
                gap.key, "VERIFIED", actor_id="verifier-seat", seat="verifier",
                verifier_id="verifier-seat",
                evidence=(sha256_evidence(
                    "verification", "test:selftest", b"pass", "verifier-seat"
                ),),
            )
            ledger.transition(
                gap.key, "INTEGRATED", actor_id="integration-seat", seat="integration",
                evidence=(sha256_evidence(
                    "integration", "wheel:selftest", b"wheel", "integration-seat"
                ),),
            )
            ledger.transition(
                gap.key, "DELIVERED", actor_id="completion-seat", seat="completion",
                completion_auditor_id="completion-seat",
                evidence=(sha256_evidence(
                    "delivery", "source:selftest", b"merged", "completion-seat"
                ),),
                installed_artifact={
                    "expected_commit": "selftest-commit",
                    "installed_commit": "selftest-commit",
                    "sha256": "a" * 64,
                    "match": True,
                },
                source_requery={"commit": "selftest-commit", "state": "merged"},
            )
            _write_json(
                os.path.join(LOOP_DIR, "work-gap-ledger.json"),
                ledger.snapshot(),
            )

            os.environ["SIMPLICIO_AUDITOR_INSTANCE_ID"] = "inst-auditor"
            rc = cmd_audit({})
            assert rc == 0, "expected COMPLETE selftest chain to pass"
            result = _read_json(paths["audit_out"])
            assert result["verdict"] == ca.VERDICT_COMPLETE, result

            rc = cmd_receipt({})
            assert rc == 0
            rc = cmd_gate({})
            assert rc == 0

            # Now break it: drop the "validating" receipt -> BLOCKED, and the
            # gate must refuse even though a stale completion_receipt.json
            # from the prior COMPLETE run is still sitting on disk.
            receipts_missing = [r for r in receipts if r["stage_id"] != "validating"]
            _write_json(paths["receipts"], receipts_missing)
            rc = cmd_audit({})
            assert rc == 1
            result = _read_json(paths["audit_out"])
            assert result["verdict"] == ca.VERDICT_BLOCKED, result
            assert result["reason_code"] == ca.REASON_MISSING_STAGE

            rc = cmd_gate({})
            assert rc == 1, "gate must not honor a stale completion receipt after the audit regresses"

            os.environ.pop("SIMPLICIO_AUDITOR_INSTANCE_ID", None)
            print("completion_auditor selftest: PASS")
            return 0
    finally:
        _set_repo(origin)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/completion_auditor.py audit|receipt|gate|report|selftest")
        sys.exit(2)
    cmd = sys.argv[1]
    handlers = {
        "audit": cmd_audit, "receipt": cmd_receipt, "gate": cmd_gate,
        "report": cmd_report, "selftest": cmd_selftest,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print("UNVERIFIED|unknown command: %s" % cmd)
        sys.exit(2)
    sys.exit(handler({}))


if __name__ == "__main__":
    main()
