"""Optional Simplicio Fast capability negotiation and diagnostics."""

from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

FAST_DISTRIBUTION = "simplicio-fast"
FAST_MODULE = "simplicio_fast"
FAST_MIN_VERSION = (0, 1, 0)
FAST_MAX_MAJOR = 1
CAPABILITIES_SCHEMA = "simplicio.fast-capabilities/v1"
DOCTOR_SCHEMA = "simplicio.fast-doctor/v1"
RECEIPT_SCHEMA = "simplicio.fast-local-receipt/v1"
SNAPSHOT_SCHEMAS = ("simplicio.context-snapshot/v1", "simplicio.mapper-context-snapshot/v1")


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    parts: list[int] = []
    for token in value.split("+", 1)[0].split(".", 3)[:3]:
        digits = "".join(character for character in token if character.isdigit())
        if not digits:
            return None
        parts.append(int(digits))
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _installed_version(distribution: str, env_name: str) -> str | None:
    override = os.environ.get(env_name)
    if override is not None:
        return override or None
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _module_available(module: str, env_name: str) -> bool:
    override = os.environ.get(env_name)
    if override is not None:
        return override.strip().lower() in {"1", "true", "yes", "ready"}
    return importlib.util.find_spec(module) is not None


@dataclass(frozen=True)
class FastPreflight:
    status: str
    fast_version: str | None
    mapper_version: str | None
    parser_available: bool
    reason: str
    correction: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fast_version": self.fast_version,
            "mapper_version": self.mapper_version,
            "parser_available": self.parser_available,
            "reason": self.reason,
            "correction": self.correction,
        }


def fast_preflight(*, offline: bool = False) -> FastPreflight:
    fast_version = _installed_version(FAST_DISTRIBUTION, "SIMPLICIO_FAST_VERSION")
    mapper_version = _installed_version("simplicio-mapper", "SIMPLICIO_MAPPER_VERSION")
    install = "pip install 'simplicio-cli[fast]'"
    if fast_version is None:
        correction = (
            f"{install} using a local wheelhouse; offline installation cannot download packages"
            if offline
            else install
        )
        return FastPreflight("absent", None, mapper_version, False, "fast-distribution-not-found", correction)

    parsed = _version_tuple(fast_version)
    if parsed is None or parsed < FAST_MIN_VERSION or parsed[0] >= FAST_MAX_MAJOR:
        return FastPreflight(
            "incompatible",
            fast_version,
            mapper_version,
            False,
            "fast-version-outside-supported-range",
            f"install {FAST_DISTRIBUTION}>=0.1,<1",
        )

    parser_available = _module_available(f"{FAST_MODULE}.parsers", "SIMPLICIO_FAST_PARSER_AVAILABLE")
    if not parser_available:
        return FastPreflight(
            "degraded",
            fast_version,
            mapper_version,
            False,
            "fast-parser-not-found",
            "reinstall simplicio-fast with its parser artifacts, then rerun fast doctor",
        )
    return FastPreflight("ready", fast_version, mapper_version, True, "compatible", None)


def capabilities_contract(*, offline: bool = False) -> dict[str, Any]:
    preflight = fast_preflight(offline=offline)
    return {
        "schema": CAPABILITIES_SCHEMA,
        "availability": preflight.to_dict(),
        "compatibility": {
            "fast": ">=0.1,<1",
            "mapper": "installed version reported; negotiated through snapshot schema",
        },
        "schemas": list(SNAPSHOT_SCHEMAS),
        "languages": ["python", "javascript", "typescript", "json"],
        "commands": ["fast capabilities", "fast doctor"],
        "source_access": False,
    }


def validate_snapshot(path: str | None) -> dict[str, Any]:
    if path is None:
        return {"status": "not_checked", "reason": "snapshot-not-supplied"}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "reason": f"snapshot-unreadable:{type(exc).__name__}"}
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if schema not in SNAPSHOT_SCHEMAS:
        return {"status": "invalid", "reason": "snapshot-schema-unsupported"}
    return {"status": "valid", "reason": "schema-supported", "schema": schema}


def doctor_contract(*, snapshot: str | None = None, offline: bool = False) -> dict[str, Any]:
    capabilities = capabilities_contract(offline=offline)
    snapshot_status = validate_snapshot(snapshot)
    status = capabilities["availability"]["status"]
    correction = capabilities["availability"]["correction"]
    if snapshot_status["status"] == "invalid":
        status = "degraded"
        correction = "rebuild/export a canonical Mapper context snapshot and retry"
    return {
        "schema": DOCTOR_SCHEMA,
        "status": status,
        "availability": capabilities["availability"],
        "snapshot": snapshot_status,
        "correction": correction,
        "exit_codes": {"ready": 0, "absent": 2, "incompatible": 3, "degraded": 4},
    }


def write_local_receipt(path: str, *, command: str, payload: dict[str, Any]) -> None:
    """Append metadata-only evidence; source paths/content are deliberately excluded."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "command": command,
        "status": payload.get("status") or payload.get("availability", {}).get("status"),
        "fast_version": payload.get("availability", {}).get("fast_version"),
        "mapper_version": payload.get("availability", {}).get("mapper_version"),
        "source_included": False,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, sort_keys=True) + "\n")
