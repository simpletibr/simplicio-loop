"""Governed installed-manifest advisory receipt for issue #346."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from simplicio_fast.capability_ranking import (
    CapabilityCandidate,
    candidates_from_manifest,
    rank_capabilities,
)


SCHEMA = "simplicio.fast.capability-rank-receipt/v1"
POLICY_SCHEMA = "simplicio.fast.capability-policy-receipt/v1"
HEALTH_SCHEMA = "simplicio.fast.capability-health-receipt/v1"
_HEALTH_VALUES = {"unknown", "healthy", "degraded", "unhealthy"}
_FORBIDDEN_MARKERS = ("secret", "token", "password", "credential", "private_key")


class GovernedReceiptError(ValueError):
    """A policy/health input is not a verified owner receipt."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: object, reason: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GovernedReceiptError(reason)
    return value.strip()


def _verified_entries(
    receipt: Mapping[str, Any], schema: str, key: str
) -> tuple[str, str, list[Mapping[str, Any]]]:
    if not isinstance(receipt, Mapping) or receipt.get("schema") != schema:
        raise GovernedReceiptError("receipt_schema_invalid")
    if receipt.get("status") != "verified":
        raise GovernedReceiptError("receipt_not_verified")
    owner = _text(receipt.get("owner"), "receipt_owner_invalid")
    authority = _text(receipt.get("authority"), "receipt_authority_invalid")
    if owner.lower() == "simplicio-fast" or authority == "fast":
        raise GovernedReceiptError("receipt_owner_invalid")
    entries = receipt.get(key)
    if not isinstance(entries, list):
        raise GovernedReceiptError("receipt_entries_invalid")
    normalized: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise GovernedReceiptError("receipt_entry_invalid")
        normalized.append(entry)
    return owner, authority, normalized


def _apply_governed_facts(
    candidates: Sequence[CapabilityCandidate],
    policy_receipt: Mapping[str, Any],
    health_receipt: Mapping[str, Any],
) -> tuple[tuple[CapabilityCandidate, ...], dict[str, int]]:
    policy_owner, policy_authority, policy_entries = _verified_entries(
        policy_receipt, POLICY_SCHEMA, "decisions"
    )
    health_owner, health_authority, health_entries = _verified_entries(
        health_receipt, HEALTH_SCHEMA, "observations"
    )
    if policy_owner != health_owner or policy_authority != health_authority:
        raise GovernedReceiptError("receipt_owner_mismatch")

    decisions: dict[tuple[str, str], bool] = {}
    for entry in policy_entries:
        handle = _text(entry.get("handle"), "policy_entry_invalid")
        scope = _text(entry.get("scope", "*"), "policy_entry_invalid")
        eligible = entry.get("eligible")
        if not isinstance(eligible, bool):
            raise GovernedReceiptError("policy_entry_invalid")
        decisions[(handle, scope)] = eligible

    health: dict[tuple[str, str], tuple[str, int]] = {}
    for entry in health_entries:
        handle = _text(entry.get("handle"), "health_entry_invalid")
        scope = _text(entry.get("scope", "*"), "health_entry_invalid")
        value = entry.get("health")
        freshness = entry.get("freshness_seconds")
        if (
            not isinstance(value, str)
            or value not in _HEALTH_VALUES
            or isinstance(freshness, bool)
            or not isinstance(freshness, int)
            or freshness < 0
        ):
            raise GovernedReceiptError("health_entry_invalid")
        health[(handle, scope)] = (value, freshness)

    updated: list[CapabilityCandidate] = []
    applied_policy = 0
    applied_health = 0
    for candidate in candidates:
        policy_value = decisions.get((candidate.handle, candidate.scope))
        if policy_value is None:
            policy_value = decisions.get((candidate.handle, "*"))
        health_value = health.get((candidate.handle, candidate.scope))
        if health_value is None:
            health_value = health.get((candidate.handle, "*"))
        changes: dict[str, Any] = {}
        if policy_value is not None:
            changes["policy_eligible"] = policy_value
            applied_policy += 1
        if health_value is not None:
            changes["health"], changes["freshness_seconds"] = health_value
            applied_health += 1
        updated.append(replace(candidate, **changes) if changes else candidate)
    return tuple(updated), {"policy": applied_policy, "health": applied_health}


def _manifest_identity(manifest: Mapping[str, Any]) -> dict[str, Any]:
    schema = _text(manifest.get("schema"), "manifest_schema_invalid")
    return {"schema": schema, "sha256": _digest(manifest)}


def build_receipt(
    manifests: Iterable[Mapping[str, Any]],
    *,
    policy_receipt: Mapping[str, Any],
    health_receipt: Mapping[str, Any],
    required: Sequence[str],
    required_scope: str = "*",
    max_freshness_seconds: int = 60,
) -> dict[str, Any]:
    manifest_list = list(manifests)
    candidates = tuple(
        candidate
        for manifest in manifest_list
        for candidate in candidates_from_manifest(manifest)
    )
    governed, applied = _apply_governed_facts(
        candidates, policy_receipt, health_receipt
    )
    ranking = rank_capabilities(
        governed,
        required,
        required_scope=required_scope,
        max_freshness_seconds=max_freshness_seconds,
        max_results=len(governed) or 1,
    )
    receipt = {
        "schema": SCHEMA,
        "status": "pass",
        "authority": "advisory_only",
        "dispatch": {"performed": False, "owner": "agent-loop-runtime"},
        "request": {
            "required_capabilities": sorted(required),
            "required_scope": required_scope,
            "max_freshness_seconds": max_freshness_seconds,
        },
        "sources": [_manifest_identity(manifest) for manifest in manifest_list],
        "catalog": {
            "schema": "simplicio.fast.capability-catalog-projection/v1",
            "generation": _digest([_manifest_identity(manifest) for manifest in manifest_list]),
            "candidate_count": len(governed),
        },
        "governed_inputs": {
            "policy": {
                "schema": POLICY_SCHEMA,
                "status": "verified",
                "accepted_entries": applied["policy"],
            },
            "health": {
                "schema": HEALTH_SCHEMA,
                "status": "verified",
                "accepted_entries": applied["health"],
            },
            "feedback": "only_verified_receipts",
        },
        "ranking": ranking,
        "redaction": {"status": "excluded", "field_classes": ["sensitive_credentials"]},
    }

    def has_forbidden_key(value: object) -> bool:
        if isinstance(value, Mapping):
            return any(
                any(marker in str(key).lower() for marker in _FORBIDDEN_MARKERS)
                or has_forbidden_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(has_forbidden_key(item) for item in value)
        return False

    if has_forbidden_key(receipt):
        raise GovernedReceiptError("secrets_projection_invalid")
    return receipt


def _run_json(command: Sequence[str]) -> Mapping[str, Any]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {completed.stderr}")
    value = json.loads(completed.stdout)
    if not isinstance(value, Mapping):
        raise RuntimeError("installed command did not return a JSON object")
    return value


def run(
    *,
    repo: Path,
    runtime_command: Sequence[str],
    policy_receipt: Mapping[str, Any],
    health_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    manifests = [
        _run_json(["simplicio-loop", "preflight", "--repo", str(repo), "--json"]),
        _run_json(["simplicio-py", "fast", "capabilities", "--json"]),
        _run_json([*runtime_command, "contracts", "smoke", "--json", "--repo", str(repo)]),
    ]
    receipt = build_receipt(
        manifests,
        policy_receipt=policy_receipt,
        health_receipt=health_receipt,
        required=("runtime:runtime:simplicio-runtime",),
        required_scope="*",
        max_freshness_seconds=60,
    )
    receipt["environment"] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "runtime_command": list(runtime_command),
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--runtime", nargs="+", default=["simplicio-runtime"])
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--health", type=Path, required=True)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    health = json.loads(args.health.read_text(encoding="utf-8"))
    if isinstance(policy, Mapping) and "policy" in policy:
        policy = policy["policy"]
    if isinstance(health, Mapping) and "health" in health:
        health = health["health"]
    receipt = run(
        repo=args.repo,
        runtime_command=args.runtime,
        policy_receipt=policy,
        health_receipt=health,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


__all__ = ["HEALTH_SCHEMA", "POLICY_SCHEMA", "SCHEMA", "GovernedReceiptError", "build_receipt", "run"]


if __name__ == "__main__":
    main()
