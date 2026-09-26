"""WI-466 Continuous Findings — finding-report emission.

Emits a structured finding report (schema simplicio.finding-report/v1) for every
problem detected across loop stages. Records are appended as JSONL under
.simplicio-loop/orchestrator/findings/ so they are durable, deduplicable, and auditable.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "simplicio.finding-report/v1"
SEVERITY_ENUM = ("low", "medium", "high", "critical")

_FINDINGS_DIR = Path(".simplicio-loop/orchestrator/findings")


def _fingerprint(stage: str, finding_id: str, source: str) -> str:
    raw = f"{finding_id}|{stage}|{source}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def emit_finding(
    stage: str,
    finding_id: str,
    severity: str,
    source: str,
    confirmed: bool,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    """Append one finding-report record (JSONL) and return it."""
    if severity not in SEVERITY_ENUM:
        raise ValueError(f"severity must be one of {SEVERITY_ENUM}, got {severity!r}")
    record = {
        "schema": SCHEMA,
        "ts": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "finding_id": finding_id,
        "severity": severity,
        "source": source,
        "confirmed": bool(confirmed),
        "fingerprint": _fingerprint(stage, finding_id, source),
        "detail": detail,
    }
    _FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _FINDINGS_DIR / "findings.jsonl"
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_findings(findings_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return all finding records from the JSONL store."""
    base = Path(findings_dir) if findings_dir else _FINDINGS_DIR
    path = base / "findings.jsonl"
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def fingerprint(stage: str, finding_id: str, source: str) -> str:
    """Expose deterministic fingerprint for dedup/router use."""
    return _fingerprint(stage, finding_id, source)


__all__ = ["emit_finding", "read_findings", "fingerprint", "SCHEMA", "SEVERITY_ENUM"]
