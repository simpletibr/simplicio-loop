from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simplicio_loop.runner import change_phase, defer_maintenance_backlog_only

TASK = (Path(__file__).with_name("task.md")).read_text(encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="simplicio-maintenance-example-") as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "repo"
        run_id = "demo-maintenance-run"
        run_dir = repo / ".simplicio-loop" / "loop-runs" / run_id
        (repo / "src").mkdir(parents=True)
        (repo / "src" / "app.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
        (run_dir / "loop").mkdir(parents=True, exist_ok=True)
        task = tmp_path / "task.md"
        task.write_text(TASK, encoding="utf-8")

        manifest = {
            "schema": "simplicio.loop.run/v1",
            "run_id": run_id,
            "repo": str(repo),
            "task_path": str(task),
            "delivery_target": "verified",
            "max_iterations": 3,
            "completion_promise": f"run-{run_id}-verified",
            "created_at": "2026-07-13T00:00:00Z",
            "task_count": 1,
            "collection_hash": "demo-collection",
        }
        state = {
            "schema": "simplicio.loop.state/v1",
            "run_id": run_id,
            "phase": "awaiting_decision",
            "delivery_target": "verified",
            "created_at": "2026-07-13T00:00:00Z",
            "updated_at": "2026-07-13T00:00:00Z",
            "task_count": 1,
            "coverage": {"scenarios": {"total": 1}, "rules": {"total": 2}},
            "validation": {"errors": [], "warnings": []},
            "current_action": "operator_proposed",
            "next_action": "await_operator_decision",
            "delivery": {"target": "verified", "current_state": "implemented", "ready": False, "receipt": ""},
            "completion": {
                "ready": False,
                "receipt": "",
                "verdict": "DELIVERY_PENDING",
                "reason_code": "oracle_incomplete",
                "tag": "UNVERIFIED",
            },
            "maintenance": {
                "mode": "active",
                "disposition": "operator",
                "receipt": "",
                "correction_summary": "",
                "deferral_reason": "",
                "evidence_status": "UNVERIFIED",
            },
            "mapper": {"ready": True, "receipt": str(run_dir / "mapper-context.json"), "targets": ["src/app.py"]},
            "operator": {
                "ready": True,
                "receipt": str(run_dir / "operator-receipt.json"),
                "target": "src/app.py",
                "execution_state": "dry_run",
            },
            "evidence": {"ready": False, "receipt": "", "status": "UNVERIFIED"},
            "blockers": [],
            "attempts": 0,
            "history": [],
            "events": [],
            "task_ids": ["T1"],
            "ac_ids": ["AC01"],
        }

        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "task-contract.json").write_text(json.dumps({"tasks": 1}, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "mapper-context.json").write_text(json.dumps({"context_pack": {"files": ["src/app.py"]}}, ensure_ascii=False, indent=2), encoding="utf-8")
        operator_receipt = run_dir / "operator-receipt.json"
        operator_receipt.write_text(json.dumps({
            "execution_state": "dry_run",
            "target": "src/app.py",
            "stdout": {"kind": "operator-proposal", "ok": True},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        operator_before = operator_receipt.read_text(encoding="utf-8")

        deferred_payload = defer_maintenance_backlog_only(
            str(repo),
            run_id,
            correction_summary="Backlog-only capture for the frozen control-plane correction.",
            deferral_reason="The active run found a correction but the maintenance window owns mutation.",
            resume_instructions=[
                "Inspect .simplicio-loop/orchestrator/runs/<run-id>/maintenance-receipt.json.",
                "Resume the run after the maintenance window and rerun mapper/operator.",
            ],
            evidence_status="UNVERIFIED",
        )
        receipt_path = run_dir / "maintenance-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        assert receipt["mode"] == "maintenance_deferred"
        assert receipt["disposition"] == "backlog_only"
        assert receipt["completion_ready"] is False
        assert deferred_payload["state"]["completion"]["ready"] is False
        assert deferred_payload["state"]["completion"]["reason_code"] == "maintenance_deferred"
        assert deferred_payload["state"]["maintenance"]["mode"] == "maintenance_deferred"
        assert deferred_payload["state"]["maintenance"]["disposition"] == "backlog_only"
        assert deferred_payload["state"]["next_action"] == "resume_from_maintenance_receipt"
        assert operator_receipt.read_text(encoding="utf-8") == operator_before

        resumed_payload = change_phase(str(repo), run_id, "awaiting_decision", "Maintenance window reopened.")

        assert resumed_payload["state"]["phase"] == "awaiting_decision"
        assert resumed_payload["state"]["maintenance"]["mode"] == "active"
        assert resumed_payload["state"]["maintenance"]["disposition"] == "operator"
        assert resumed_payload["state"]["operator"]["execution_state"] == "invalidated"
        assert resumed_payload["state"]["operator"]["ready"] is False
        assert resumed_payload["state"]["evidence"]["status"] == "INVALIDATED"
        assert resumed_payload["state"]["next_action"] == "mapper_scan_required"

        print(json.dumps({
            "run_id": run_id,
            "maintenance_receipt": str(receipt_path),
            "resume_next_action": resumed_payload["state"]["next_action"],
            "resume_instructions": receipt["resume_instructions"],
        }, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
