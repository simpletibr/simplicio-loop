#!/usr/bin/env python3
"""Compatibility entry point for ``simplicio-loop release-train check``.

The loop owns the release-train command surface, while the Mapper owns the
component manifest and its local invariants.  Keeping this adapter in the
checkout lets the latest loop package compose those two responsibilities
without importing private loop internals.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simplicio_mapper.release_manifest import (  # noqa: E402
    RELEASE_MANIFEST_SCHEMA,
    build_release_artifact_digest,
    build_release_manifest,
    check_registry_baseline,
)


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED_SCHEMAS = (
    "contracts/component-release/v1/schema.json",
    "contracts/component-release-event/v1/schema.json",
    "contracts/plugin-context-handle/v1/schema.json",
    "contracts/plugin-context-handle/v2/schema.json",
)
_REQUIRED_CAPABILITIES = {
    "simplicio.mapper-artifacts/v1",
    "simplicio.plugin.context-handle/v1",
    "simplicio.plugin.context-handle/v2",
}


def _check_version_sync(root: Path) -> tuple[bool, str]:
    script = root / "scripts" / "check-version-sync.py"
    if not script.is_file():
        return False, f"missing {script.relative_to(root)}"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    detail = (result.stdout or result.stderr).strip().splitlines()
    return result.returncode == 0, detail[-1] if detail else "version-sync returned no details"


def _check_json_schemas(root: Path) -> tuple[bool, str]:
    missing: list[str] = []
    invalid: list[str] = []
    for relative in _REQUIRED_SCHEMAS:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid.append(relative)
            continue
        if not isinstance(schema, dict) or schema.get("type") != "object" or not schema.get("required"):
            invalid.append(relative)
    if missing or invalid:
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if invalid:
            details.append("invalid=" + ",".join(invalid))
        return False, "; ".join(details)
    return True, f"{len(_REQUIRED_SCHEMAS)} release schemas parse and expose required fields"


def _check_release_manifest(root: Path) -> tuple[bool, str, dict[str, Any] | None]:
    try:
        manifest = build_release_manifest(root=str(root))
    except Exception as error:  # noqa: BLE001 - turn every local drift into a failed check
        return False, f"manifest generation failed: {error}", None

    failures: list[str] = []
    if manifest.get("schema") != RELEASE_MANIFEST_SCHEMA:
        failures.append("unexpected manifest schema")
    commit_sha = manifest.get("commit_sha")
    if not isinstance(commit_sha, str) or not _COMMIT_RE.fullmatch(commit_sha):
        failures.append("manifest commit_sha is not a full git SHA")
    if manifest.get("artifact_digest") != build_release_artifact_digest(manifest):
        failures.append("release identity digest is not reproducible")
    if not _REQUIRED_CAPABILITIES.issubset(set(manifest.get("capabilities", []))):
        failures.append("required release capabilities are missing")

    downstream = manifest.get("downstream_events")
    if not isinstance(downstream, dict):
        failures.append("downstream_events block is missing")
    else:
        expected = {
            "status": "dispatch-ready",
            "transport": "github.repository_dispatch",
            "event_type": "simplicio-component-release",
            "deduplication": "event_id",
            "authentication_secret": "RELEASE_TRAIN_DISPATCH_TOKEN",
        }
        for key, value in expected.items():
            if downstream.get(key) != value:
                failures.append(f"downstream_events.{key} is not {value!r}")

    if failures:
        return False, "; ".join(failures), manifest
    return True, f"{manifest['component']} {manifest['version']} at {commit_sha}", manifest


def release_train_check(repo: str | Path = ".") -> int:
    """Validate the Mapper release train without network side effects.

    The return code is the contract consumed by ``simplicio-loop``.  The JSON
    receipt is intentionally small and stable so CI can retain it as evidence.
    """
    root = Path(repo).resolve()
    checks: list[dict[str, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "passed" if ok else "failed", "detail": detail})

    version_ok, version_detail = _check_version_sync(root)
    record("version-sync", version_ok, version_detail)

    schemas_ok, schemas_detail = _check_json_schemas(root)
    record("release-schemas", schemas_ok, schemas_detail)

    registry_ok, registry_messages = check_registry_baseline(
        baseline_path=str(root / "scripts" / "schema_registry_baseline.json")
    )
    record("schema-registry-baseline", registry_ok, registry_messages[-1])

    manifest_ok, manifest_detail, manifest = _check_release_manifest(root)
    record("component-release-manifest", manifest_ok, manifest_detail)

    event_ok = False
    event_detail = "manifest unavailable"
    if manifest is not None and manifest_ok:
        try:
            from scripts.build_release_event import build_release_event

            event = build_release_event(manifest)
            event_ok = event["event_id"] == event["dedupe_key"]
            event_detail = (
                f"{event['event_type']} {event['event_id']} is deterministic and retry-safe"
                if event_ok
                else "event_id and dedupe_key differ"
            )
        except Exception as error:  # noqa: BLE001 - report a failed integration gate
            event_detail = f"event generation failed: {error}"
    record("release-event", event_ok, event_detail)

    payload: dict[str, Any] = {
        "schema": "simplicio.release-train-check/v1",
        "status": "passed" if all(item["status"] == "passed" for item in checks) else "failed",
        "repo": str(root),
        "checks": checks,
    }
    if manifest is not None:
        payload["release"] = {
            "component": manifest.get("component"),
            "version": manifest.get("version"),
            "commit_sha": manifest.get("commit_sha"),
            "artifact_digest": manifest.get("artifact_digest"),
        }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["status"] == "passed" else 1


__all__ = ["release_train_check"]
