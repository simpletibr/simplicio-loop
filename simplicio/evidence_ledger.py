"""Append-only acceptance-criteria evidence ledger for governed task runs."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_SCHEMA = "simplicio.dev-cli.evidence-ledger/v1"
MEASURED = "MEASURED"
UNVERIFIED = "UNVERIFIED"


class LedgerError(ValueError):
    """Base error for invalid evidence ledger operations."""


class StaleEvidenceError(LedgerError):
    """Raised when a receipt does not match the frozen execution identity."""


class ArtifactMismatchError(LedgerError):
    """Raised when an artifact is missing or its digest has changed."""


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def artifact_digest(path: str | Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


class EvidenceLedger:
    """Persist one immutable JSON record per AC/RN evidence claim.

    The ledger refuses stale base/plan identities and verifies artifact hashes before
    a MEASURED claim is appended. Missing claims remain UNVERIFIED in ``matrix``.
    """

    def __init__(
        self, path: str | Path, *, base_sha: str, plan_hash: str, environment: Mapping[str, str] | None = None
    ):
        self.path = Path(path)
        self.base_sha = str(base_sha)
        self.plan_hash = str(plan_hash)
        self.environment = dict(environment or {"platform": platform.platform()})

    def append(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(receipt)
        row.setdefault("schema", LEDGER_SCHEMA)
        row.setdefault("timestamp", _now())
        row.setdefault("environment", dict(self.environment))
        if row.get("schema") != LEDGER_SCHEMA:
            raise LedgerError("unsupported evidence ledger schema")
        criterion_id = str(row.get("criterion_id", "")).strip()
        if not criterion_id:
            raise LedgerError("criterion_id is required")
        if str(row.get("base_sha", "")) != self.base_sha or str(row.get("plan_hash", "")) != self.plan_hash:
            raise StaleEvidenceError("receipt base_sha/plan_hash does not match the frozen ledger")
        status = str(row.get("status", UNVERIFIED)).upper()
        if status not in {MEASURED, UNVERIFIED}:
            raise LedgerError("status must be MEASURED or UNVERIFIED")
        artifact = row.get("artifact")
        if status == MEASURED:
            if not row.get("command") or row.get("exit_code") != 0:
                raise LedgerError("MEASURED receipts require command and exit_code=0")
            if not artifact:
                raise LedgerError("MEASURED receipts require an artifact")
            artifact_path = Path(str(artifact))
            if not artifact_path.is_absolute():
                artifact_path = self.path.parent / artifact_path
            try:
                actual = artifact_digest(artifact_path)
            except OSError as exc:
                raise ArtifactMismatchError(f"artifact is unavailable: {artifact}") from exc
            expected = str(row.get("artifact_hash", ""))
            if expected and expected != actual:
                raise ArtifactMismatchError(f"artifact hash mismatch for {artifact}")
            row["artifact_hash"] = actual
        row["status"] = status
        encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + chr(10)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline=chr(10)) as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        return row

    def record(
        self,
        *,
        criterion_id: str,
        command: str,
        exit_code: int,
        artifact: str | Path,
        base_sha: str | None = None,
        plan_hash: str | None = None,
        kind: str = "test-output",
        status: str = MEASURED,
        environment: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        artifact_path = Path(artifact)
        return self.append(
            {
                "criterion_id": criterion_id,
                "kind": kind,
                "command": command,
                "exit_code": exit_code,
                "artifact": str(artifact_path),
                "base_sha": self.base_sha if base_sha is None else base_sha,
                "plan_hash": self.plan_hash if plan_hash is None else plan_hash,
                "environment": dict(environment or self.environment),
                "status": status,
            }
        )

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                result.append(json.loads(line))
        return result

    def matrix(self, criterion_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        rows = self.rows()
        by_id: dict[str, list[dict[str, Any]]] = {str(item): [] for item in criterion_ids}
        for row in rows:
            if row.get("criterion_id") in by_id:
                by_id[row["criterion_id"]].append(row)
        claims = {
            criterion: {
                "status": MEASURED if any(item.get("status") == MEASURED for item in items) else UNVERIFIED,
                "receipts": items,
            }
            for criterion, items in by_id.items()
        }
        return {
            "schema": LEDGER_SCHEMA,
            "base_sha": self.base_sha,
            "plan_hash": self.plan_hash,
            "claims": claims,
        }
