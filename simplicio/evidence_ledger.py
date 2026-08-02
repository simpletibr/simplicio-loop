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


def _resolve_path(ledger_path: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ledger_path.parent / path


def _attachment_path(item: Mapping[str, Any]) -> str | None:
    for key in ("path", "artifact", "file"):
        value = item.get(key)
        if value:
            return str(value)
    return None


class EvidenceLedger:
    """Persist one immutable JSON record per AC/RN evidence claim.

    The ledger refuses stale base/plan identities and verifies artifact hashes before
    a MEASURED claim is appended. Missing claims remain UNVERIFIED in ``matrix``.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        base_sha: str,
        plan_hash: str,
        commit_sha: str = "unknown",
        environment: Mapping[str, str] | None = None,
    ):
        self.path = Path(path)
        self.base_sha = str(base_sha)
        self.plan_hash = str(plan_hash)
        self.commit_sha = str(commit_sha)
        self.environment = dict(environment or {"platform": platform.platform()})

    def append(self, receipt: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(receipt)
        row.setdefault("schema", LEDGER_SCHEMA)
        row.setdefault("timestamp", _now())
        row.setdefault("environment", dict(self.environment))
        row.setdefault("commit_sha", self.commit_sha)
        if row.get("schema") != LEDGER_SCHEMA:
            raise LedgerError("unsupported evidence ledger schema")
        criterion_id = str(row.get("criterion_id", "")).strip()
        if not criterion_id:
            raise LedgerError("criterion_id is required")
        if str(row.get("base_sha", "")) != self.base_sha or str(row.get("plan_hash", "")) != self.plan_hash:
            raise StaleEvidenceError("receipt base_sha/plan_hash does not match the frozen ledger")
        if str(row.get("commit_sha", "")) != self.commit_sha:
            raise StaleEvidenceError("receipt commit_sha does not match the frozen ledger")
        status = str(row.get("status", UNVERIFIED)).upper()
        if status not in {MEASURED, UNVERIFIED}:
            raise LedgerError("status must be MEASURED or UNVERIFIED")
        artifact = row.get("artifact")
        if status == MEASURED:
            if not row.get("command") or row.get("exit_code") != 0:
                raise LedgerError("MEASURED receipts require command and exit_code=0")
            if not artifact:
                raise LedgerError("MEASURED receipts require an artifact")
            artifact_path = _resolve_path(self.path, str(artifact))
            try:
                actual = artifact_digest(artifact_path)
            except OSError as exc:
                raise ArtifactMismatchError(f"artifact is unavailable: {artifact}") from exc
            expected = str(row.get("artifact_hash", ""))
            if expected and expected != actual:
                raise ArtifactMismatchError(f"artifact hash mismatch for {artifact}")
            row["artifact_hash"] = actual
            attachments = row.get("attachments", [])
            if not isinstance(attachments, list):
                raise LedgerError("attachments must be a list")
            verified_attachments: list[dict[str, Any]] = []
            for attachment in attachments:
                if not isinstance(attachment, Mapping):
                    raise LedgerError("each attachment must be an object")
                item = dict(attachment)
                attachment_value = _attachment_path(item)
                if not attachment_value:
                    raise LedgerError("each attachment requires path, artifact, or file")
                try:
                    attachment_actual = artifact_digest(_resolve_path(self.path, attachment_value))
                except OSError as exc:
                    raise ArtifactMismatchError(f"attachment is unavailable: {attachment_value}") from exc
                expected_attachment = str(item.get("sha256", item.get("artifact_hash", ""))).strip()
                if expected_attachment and expected_attachment != attachment_actual:
                    raise ArtifactMismatchError(f"attachment hash mismatch for {attachment_value}")
                item["sha256"] = attachment_actual
                verified_attachments.append(item)
            if attachments:
                row["attachments"] = verified_attachments
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
        commit_sha: str | None = None,
        kind: str = "test-output",
        status: str = MEASURED,
        environment: Mapping[str, str] | None = None,
        attachments: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...] | None = None,
        prototype: str | Path | None = None,
    ) -> dict[str, Any]:
        artifact_path = Path(artifact)
        if attachments is not None:
            if not isinstance(attachments, (list, tuple)):
                raise LedgerError("attachments must be a list")
            if any(not isinstance(item, Mapping) for item in attachments):
                raise LedgerError("each attachment must be an object")
        return self.append(
            {
                "criterion_id": criterion_id,
                "kind": kind,
                "command": command,
                "exit_code": exit_code,
                "artifact": str(artifact_path),
                "base_sha": self.base_sha if base_sha is None else base_sha,
                "plan_hash": self.plan_hash if plan_hash is None else plan_hash,
                "commit_sha": self.commit_sha if commit_sha is None else commit_sha,
                "environment": dict(environment or self.environment),
                "status": status,
                **({"attachments": [dict(item) for item in attachments]} if attachments else {}),
                **({"prototype": str(prototype)} if prototype is not None else {}),
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

    def _receipt_artifact_state(self, row: Mapping[str, Any]) -> tuple[bool, str | None]:
        status = str(row.get("status", UNVERIFIED)).upper()
        if status != MEASURED:
            return False, None
        artifact = row.get("artifact")
        if not artifact:
            return False, "missing-artifact-path"
        if (
            str(row.get("base_sha", "")) != self.base_sha
            or str(row.get("plan_hash", "")) != self.plan_hash
            or str(row.get("commit_sha", "")) != self.commit_sha
        ):
            return False, "stale-identity"
        artifact_path = _resolve_path(self.path, str(artifact))
        try:
            actual = artifact_digest(artifact_path)
        except OSError:
            return False, "artifact-missing"
        expected = str(row.get("artifact_hash", "")).strip()
        if not expected:
            return False, "missing-artifact-hash"
        if expected != actual:
            return False, "artifact-hash-mismatch"
        attachments = row.get("attachments", [])
        if not isinstance(attachments, list):
            return False, "invalid-attachments"
        for attachment in attachments:
            if not isinstance(attachment, Mapping):
                return False, "invalid-attachments"
            attachment_value = _attachment_path(attachment)
            if not attachment_value:
                return False, "missing-attachment-path"
            try:
                attachment_actual = artifact_digest(_resolve_path(self.path, attachment_value))
            except OSError:
                return False, "attachment-missing"
            attachment_expected = str(attachment.get("sha256", attachment.get("artifact_hash", ""))).strip()
            if not attachment_expected:
                return False, "missing-attachment-hash"
            if attachment_expected != attachment_actual:
                return False, "attachment-hash-mismatch"
        return True, None

    def matrix(self, criterion_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        rows = self.rows()
        by_id: dict[str, list[dict[str, Any]]] = {str(item): [] for item in criterion_ids}
        for row in rows:
            if row.get("criterion_id") in by_id:
                by_id[row["criterion_id"]].append(row)
        claims = {}
        watcher_failures: list[dict[str, Any]] = []
        for criterion, items in by_id.items():
            measured_receipts: list[dict[str, Any]] = []
            invalid_receipts: list[dict[str, Any]] = []
            for item in items:
                valid, reason = self._receipt_artifact_state(item)
                if valid:
                    measured_receipts.append(item)
                    continue
                if str(item.get("status", UNVERIFIED)).upper() == MEASURED:
                    invalid = dict(item)
                    invalid["watcher_reason"] = reason
                    invalid_receipts.append(invalid)
                    watcher_failures.append(
                        {
                            "criterion_id": criterion,
                            "artifact": invalid.get("artifact"),
                            "reason": reason,
                        }
                    )
            claims[criterion] = {
                "status": MEASURED if measured_receipts else UNVERIFIED,
                "receipts": measured_receipts,
                "invalid_receipts": invalid_receipts,
            }
        return {
            "schema": LEDGER_SCHEMA,
            "base_sha": self.base_sha,
            "plan_hash": self.plan_hash,
            "commit_sha": self.commit_sha,
            "claims": claims,
            "watcher": {
                "revalidated": True,
                "ok": not watcher_failures,
                "failures": watcher_failures,
            },
        }

    def watch(self, criterion_ids: list[str] | tuple[str, ...]) -> dict[str, Any]:
        """Reread and rehash the ledger as an independent final success gate."""
        return self.matrix(criterion_ids)
