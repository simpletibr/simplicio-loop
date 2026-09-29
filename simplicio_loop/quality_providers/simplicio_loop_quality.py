"""Mandatory Loop quality provider with physical admission and owned cancellation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from simplicio_loop.quality_process import CORE_GATE_TIMEOUT_SECONDS, CommandReason, run_bounded

PROVIDER_VERSION = "1.2.0"
QUALITY_TIMEOUT_SECONDS = CORE_GATE_TIMEOUT_SECONDS
QUALITY_OUTER_TIMEOUT_SECONDS = QUALITY_TIMEOUT_SECONDS + 30.0
QUALITY_SAMPLE_INTERVAL_NS = 5_000_000_000
QUALITY_MISSING_SIGNAL_REASONS = frozenset({
    "PHYSICAL_SIGNAL_UNAVAILABLE",
    "PHYSICAL_PRESSURE_UNAVAILABLE",
    "PHYSICAL_SAMPLE_UNAVAILABLE",
})


def capability_negotiate() -> dict:
    """Declare the provider contract and the existing safety mechanisms it uses."""
    return {
        "version": PROVIDER_VERSION,
        "capabilities": {
            "structured_findings": True,
            "cancel_token": True,
            "per_run_matrix": True,
            "physical_admission_monitor": True,
            "owned_process_group": True,
            "quality_gate_outer_timeout_seconds": QUALITY_OUTER_TIMEOUT_SECONDS,
            "quality_gate_timeout_seconds": QUALITY_TIMEOUT_SECONDS,
            "quality_gate_command": "scripts/check.py --core-gate",
            "monitor_sample_interval_ns": QUALITY_SAMPLE_INTERVAL_NS,
            "physical_pressure_signals": ["memory_available_bytes", "disk_free_bytes", "pressure_percent"],
            "psi_continuous": False,
            "test_environment": {
                "capability": "test_environment_v1",
                "request_schema": "simplicio.test-environment-request/v1",
                "receipt_schema": "simplicio.test-environment-receipt/v1",
                "authority": "loop",
                "provider_may_provision": False,
            },
        },
    }


def _build_monitor(repo_path: Path):
    """Construct the shared #1228 monitor; tests replace this with a deterministic probe."""
    from simplicio_loop.local_capacity import PhysicalAdmissionMonitor, physical_monitor_kwargs

    return PhysicalAdmissionMonitor(
        str(repo_path), 1, sample_interval_ns=QUALITY_SAMPLE_INTERVAL_NS, **physical_monitor_kwargs(),
    )


def _cancel_requested(cancel_token) -> bool:
    if cancel_token is None:
        return False
    checker = getattr(cancel_token, "is_set", None)
    if callable(checker):
        return bool(checker())
    return bool(cancel_token)


def _status_is_admitted(status) -> bool:
    return isinstance(status, dict) and status.get("admitted") is True


def _finding(level: str, message: str, **details) -> dict:
    value = {"level": level, "message": message}
    value.update(details)
    return value


def _active_cancellation_reason(status) -> str:
    """Cancel active owned work only for checkpoint/terminate or missing signals."""
    if not isinstance(status, dict):
        return "PHYSICAL_ADMISSION_INVALID"
    reason = str(status.get("reason_code") or "PHYSICAL_ADMISSION_DENIED")
    action = str(status.get("action") or "suspend_new")
    if reason in QUALITY_MISSING_SIGNAL_REASONS or action in {"checkpoint_owned_stop", "terminate_owned"}:
        return "%s:%s" % (reason, action)
    # suspend_new at the no-new-work threshold does not terminate an already
    # admitted owned quality gate; it only blocks the next admission.
    return ""


def run(
    *,
    run_id: str,
    tasks: list,
    attempt: int,
    repo: str,
    worktree: str,
    head: str,
    diff_hash: str,
    policy: str,
    cancel_token=None,
) -> dict:
    """Run ``scripts/check.py`` under existing physical admission and ownership."""
    del run_id, tasks, attempt, worktree, head, diff_hash, policy
    repo_path = Path(repo).resolve()
    check_script = repo_path / "scripts" / "check.py"
    receipts = [str(check_script)]
    if not check_script.exists():
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "scripts/check.py not found", reason_code="QUALITY_SCRIPT_MISSING")],
            "receipts": receipts,
            "detail": "quality provider could not locate scripts/check.py",
        }
    if _cancel_requested(cancel_token):
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "quality gate cancellation requested before spawn", reason_code="QUALITY_CANCELLED_BEFORE_ADMISSION")],
            "receipts": receipts,
            "detail": "quality gate did not spawn because STOP/cancellation was already set",
        }

    try:
        monitor = _build_monitor(repo_path)
        initial_sample = monitor.refresh(force=True)
        initial_status = monitor.admission_status()
    except Exception as exc:
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "physical admission monitor unavailable", reason_code="PHYSICAL_MONITOR_UNAVAILABLE", error=type(exc).__name__)],
            "receipts": receipts,
            "detail": "quality gate admission failed closed before spawn",
        }
    if not _status_is_admitted(initial_status):
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "quality gate denied by physical admission", reason_code=initial_status.get("reason_code", "PHYSICAL_ADMISSION_DENIED") if isinstance(initial_status, dict) else "PHYSICAL_ADMISSION_INVALID", admission=initial_status)],
            "receipts": receipts,
            "detail": "heavy quality gate was not spawned; physical admission evidence is required",
        }

    last_status = {"initial": initial_status, "sample": getattr(initial_sample, "to_dict", lambda: {})()}

    def cancel_check():
        if _cancel_requested(cancel_token):
            return "stop_requested"
        try:
            if monitor.due():
                monitor.refresh()
                status = monitor.admission_status()
                last_status["latest"] = status
                if not _status_is_admitted(status):
                    reason = _active_cancellation_reason(status)
                    if reason:
                        return reason
        except Exception as exc:
            last_status["monitor_error"] = "%s: %s" % (type(exc).__name__, exc)
            return "physical_monitor_error"
        return ""

    command = run_bounded(
        [sys.executable, str(check_script), "--core-gate"],
        phase="quality_gate", cwd=str(repo_path), capture_output=True,
        timeout_seconds=QUALITY_TIMEOUT_SECONDS, cancel_check=cancel_check,
    )
    try:
        last_status["final"] = monitor.status()
    except Exception as exc:
        last_status["final_error"] = "%s: %s" % (type(exc).__name__, exc)
    evidence = json.dumps(last_status, ensure_ascii=False, sort_keys=True, default=str)[:3000]
    output = (command.stdout or command.stderr or "quality gate produced no output").strip()[:2000]

    if command.reason == CommandReason.CANCELLED:
        reason_code = command.cancel_reason or "QUALITY_CANCELLED"
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "owned quality subprocess cancelled", reason_code=reason_code, exit_code=command.returncode, evidence=last_status)],
            "receipts": receipts,
            "detail": "quality gate stopped under owned-process cancellation (%s); output=%s; evidence=%s" % (reason_code, output, evidence),
        }
    if command.reason == CommandReason.CONTAINMENT_UNAVAILABLE:
        return {
            "status": "BLOCKED",
            "findings": [_finding("error", "quality subprocess containment unavailable", reason_code="QUALITY_PROCESS_CONTAINMENT_UNAVAILABLE", exit_code=command.returncode)],
            "receipts": receipts,
            "detail": (command.stderr or "CAPABILITY_UNAVAILABLE[process_containment]")[:2000],
        }
    if command.timed_out:
        return {
            "status": "FAIL",
            "findings": [_finding("fail", "quality subprocess timed out", reason_code="QUALITY_TIMEOUT", exit_code=command.returncode, evidence=last_status)],
            "receipts": receipts,
            "detail": "scripts/check.py --core-gate exceeded %.1fs and its owned process group was terminated; output=%s; evidence=%s" % (QUALITY_TIMEOUT_SECONDS, output, evidence),
        }
    if command.returncode == 0:
        return {
            "status": "PASS",
            "findings": [],
            "receipts": receipts,
            "detail": "scripts/check.py --core-gate passed; output=%s; evidence=%s" % (output, evidence),
        }
    return {
        "status": "FAIL",
        "findings": [_finding("fail", output or "check.py failed", reason_code="QUALITY_CHECK_FAILED", exit_code=command.returncode, evidence=last_status)],
        "receipts": receipts,
        "detail": output or "check.py failed",
    }
