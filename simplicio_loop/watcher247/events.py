"""Event emission for the 24/7 watcher intake and PR stages.

Writes watcher stage events (intake, pr) to the same events.jsonl that turbo writes its stages
(orient, plan, apply, verify, done). The kanban dashboard reads both sources from one stream.

Schema: simplicio.dashboard-event/v1 (same as turbo).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .. import dashboard_events

# Track the current phase per run_dir so we can emit phase_exited
_CURRENT_PHASE: Dict[str, str] = {}


def emit_stage(
    run_dir: Any,
    stage: str,
    status: str,
    **fields: Any
) -> Optional[Dict[str, Any]]:
    """Append a watcher stage event (intake, pr) to events.jsonl.

    Returns the written event envelope, or None on failure (fail-open).
    Uses the same schema and format as turbo's emit_batch.

    Args:
        run_dir: The run directory (e.g., .simplicio-loop/orchestrator/runs/<id>).
        stage: The stage name ("intake", "pr", etc.).
        status: Status ("ok", "error", etc.) — becomes the severity if error.
        **fields: Additional fields (pr_number, etc.) for the payload.

    Example:
        emit_stage(run_dir, "intake", "ok")
        emit_stage(run_dir, "pr", "ok", pr_number=123)
    """
    try:
        run_dir_path = Path(run_dir)
        run_dir_key = str(run_dir_path.resolve())

        # Map status to severity
        if status == "error":
            severity = "error"
        else:
            severity = "info"

        specs = []
        current_phase = _CURRENT_PHASE.get(run_dir_key)

        # Emit phase_exited for the previous phase if transitioning
        if current_phase is not None and current_phase != stage:
            specs.append({
                "kind": "phase_exited",
                "source": "operator",
                "phase": current_phase,
                "severity": severity,
                "scope": "collection",
                "payload": {"to": stage, "status": status, **fields},
            })

        # Emit phase_entered for the new stage
        specs.append({
            "kind": "phase_entered",
            "source": "operator",
            "phase": stage,
            "severity": severity,
            "scope": "collection",
            "payload": {"from": current_phase, "status": status, **fields},
        })

        # Load the dashboard_events module and call emit_batch directly
        module = dashboard_events.load()
        if module is None:
            return None

        written = module.emit_batch(run_dir_path, specs)
        if written:
            _CURRENT_PHASE[run_dir_key] = stage
            return written[-1]
        return None

    except Exception:
        # Fail-open: never raise into the watcher
        return None
