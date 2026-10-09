"""Event emission for the 24/7 watcher intake and PR stages.

Writes watcher stage events (intake, pr) to the same events.jsonl that turbo writes its stages
(orient, plan, apply, verify, done). The kanban dashboard reads both sources from one stream.

Schema: simplicio.dashboard-event/v1 (same as turbo).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .. import dashboard_events


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
        run_dir = Path(run_dir)

        # Map status to severity
        if status == "error":
            severity = "error"
        else:
            severity = "info"

        # Build the spec for emit_batch
        # Use namespaced kinds (watcher.intake, watcher.pr) and operator source
        spec = {
            "kind": f"watcher.{stage}",
            "source": "operator",
            "phase": stage,
            "severity": severity,
            "scope": "collection",
            "payload": dict(fields) if fields else {},
        }

        # Load the dashboard_events module and call emit_batch directly
        module = dashboard_events.load()
        if module is None:
            return None

        written = module.emit_batch(run_dir, [spec])
        return written[0] if written else None

    except Exception:
        # Fail-open: never raise into the watcher
        return None
