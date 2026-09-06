#!/usr/bin/env python3
"""Reconcile one authenticated Mapper release event into this checkout.

The script is the mutation boundary used by the release-train workflow. It
accepts a direct event or a GitHub ``repository_dispatch`` envelope, verifies
the immutable release identity, updates only the Mapper lower bound, resolves
the exact candidate into ``uv.lock``, and records the event/digest identity in
``config/release-train-lock.json``. A fixed workflow branch consumes the
receipt, so retries update one PR rather than creating a PR storm.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from simplicio.component_manifest import (
    COMPATIBLE,
    check_version_against_range,
    compare_versions,
    declared_dependency_range,
    tested_dependency_artifacts,
    tested_dependency_version,
)
from simplicio.release_train import (
    EVENT_SCHEMA,
    MAPPER_COMPONENT,
    ReleaseTrainError,
    canonical_digest,
    extract_release_event,
    validate_release_event,
)

LOCK_SCHEMA = "simplicio.dev-cli.release-train-lock/v1"
DEFAULT_LOCK = Path("config/release-train-lock.json")
_MAPPER_DEPENDENCY = re.compile(
    r'(?P<prefix>"simplicio-mapper)(?P<floor>>=)(?P<version>[0-9][^,\"]*)(?P<rest>,<[^\"]+)(?P<suffix>")'
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseTrainError(f"cannot read JSON {path}: {exc}") from exc


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _event_artifact_digests(event: Mapping[str, Any]) -> set[str]:
    artifacts = event.get("artifact_digests")
    if not isinstance(artifacts, Mapping):
        return set()
    return {
        artifact.get("digest")
        for artifact in artifacts.values()
        if isinstance(artifact, Mapping) and isinstance(artifact.get("digest"), str)
    }


def _locked_artifact_digests(artifacts: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    sdist = artifacts.get("sdist")
    if isinstance(sdist, Mapping) and isinstance(sdist.get("digest"), str):
        values.add(sdist["digest"])
    for wheel in artifacts.get("wheels", []) or []:
        if isinstance(wheel, Mapping) and isinstance(wheel.get("digest"), str):
            values.add(wheel["digest"])
    return values


def _preflight(event: Mapping[str, Any], declared_range: str | None) -> None:
    errors = validate_release_event(event)
    if errors:
        raise ReleaseTrainError("invalid release event: " + "; ".join(errors))
    if event.get("delivery", {}).get("authenticated") is False:
        raise ReleaseTrainError("release event delivery is not authenticated")
    status = str(event.get("status", event.get("release_status", ""))).lower()
    if event.get("revoked") is True or status in {"revoked", "recalled"}:
        raise ReleaseTrainError("revoked release cannot be reconciled")
    if event.get("yanked") is True or status in {"yanked", "withdrawn"}:
        raise ReleaseTrainError("yanked release cannot be reconciled")
    version = event.get("version")
    if not isinstance(version, str):
        raise ReleaseTrainError("release event version is missing")
    compatibility = check_version_against_range(version, declared_range, name=MAPPER_COMPONENT)
    if compatibility.status != COMPATIBLE:
        raise ReleaseTrainError(compatibility.reason)
    channel = event["delivery"]["channel"]
    if channel == "stable" and event.get("attestation") != "ed25519-signed":
        raise ReleaseTrainError("stable release requires an Ed25519-signed manifest")


def _update_dependency(root: Path, version: str) -> bool:
    path = root / "pyproject.toml"
    original = path.read_text(encoding="utf-8")
    matches = list(_MAPPER_DEPENDENCY.finditer(original))
    if len(matches) != 1:
        raise ReleaseTrainError("pyproject.toml must contain exactly one bounded Mapper dependency")
    current = matches[0].group("version")
    if compare_versions(version, current) < 0:
        raise ReleaseTrainError(f"candidate {version} would downgrade the declared Mapper floor {current}")
    updated = _MAPPER_DEPENDENCY.sub(
        lambda match: match.group(0).replace(match.group("version"), version, 1),
        original,
        count=1,
    )
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def _resolve_lock(root: Path, version: str) -> None:
    uv = shutil.which("uv")
    if uv is None:
        raise ReleaseTrainError("uv is required to resolve the candidate into uv.lock")
    lock_path = root / "uv.lock"
    original = lock_path.read_text(encoding="utf-8") if lock_path.is_file() else None
    result = subprocess.run(
        [uv, "lock", "--upgrade-package", f"{MAPPER_COMPONENT}=={version}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise ReleaseTrainError(f"uv lock failed: {detail}")
    if original is None:
        return
    resolved = lock_path.read_text(encoding="utf-8")
    package_pattern = re.compile(
        r'(?ms)^\[\[package\]\]\nname = "simplicio-mapper"\n.*?(?=^\[\[package\]\]\n|\Z)'
    )
    resolved_package = package_pattern.search(resolved)
    original_package = package_pattern.search(original)
    dependency_pattern = re.compile(
        r'^\s*\{ name = "simplicio-mapper", specifier = "[^"]+" \},$', re.MULTILINE
    )
    resolved_dependency = dependency_pattern.search(resolved)
    original_dependency = dependency_pattern.search(original)
    if not resolved_package or not original_package or not resolved_dependency or not original_dependency:
        raise ReleaseTrainError("uv.lock shape changed; refusing to rewrite unrelated lock entries")
    merged = (
        original[: original_package.start()] + resolved_package.group(0) + original[original_package.end() :]
    )
    merged = (
        merged[: original_dependency.start()]
        + resolved_dependency.group(0)
        + merged[original_dependency.end() :]
    )
    lock_path.write_text(merged, encoding="utf-8")


def _update_registry(root: Path, event: Mapping[str, Any], declared_range: str, lock_version: str) -> None:
    path = root / "config" / "release-train-mapper.json"
    if not path.is_file():
        return
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ReleaseTrainError("config/release-train-mapper.json must be an object")
    dependency = payload.setdefault("dependency", {})
    release = dependency.setdefault("release", {})
    dependency.update({"declared_range": declared_range, "tested_against": lock_version})
    dependency["tested_against_source"] = "uv.lock"
    release.update(
        {
            "version": event["version"],
            "tag": f"v{event['version']}",
            "commit_sha": event["commit_sha"],
            "artifact_digests": event["artifact_digests"],
            "source": "Mapper component-release event and immutable PyPI artifacts",
        }
    )
    payload["current_release_status"] = "UNVERIFIED"
    payload["blocked_reason"] = (
        "Candidate lock identity is reconciled; stable promotion still requires "
        "installed N/N-1 conformance and release evidence."
    )
    _write_json(path, payload)


def reconcile(root: Path, event_value: Any, *, lock_path: Path = DEFAULT_LOCK) -> dict[str, Any]:
    """Apply one candidate and return a deterministic reconciliation receipt."""
    event = extract_release_event(event_value)
    if not isinstance(event, Mapping):
        raise ReleaseTrainError("release event must be an object")
    declared = declared_dependency_range(MAPPER_COMPONENT, root)
    _preflight(event, declared)
    version = str(event["version"])
    had_release_lock = (root / lock_path).is_file()
    current, current_reason = tested_dependency_version(MAPPER_COMPONENT, root)
    if current is not None:
        relation = compare_versions(version, current)
        if relation < 0:
            raise ReleaseTrainError(f"candidate {version} is older than locked Mapper {current}")
        if relation == 0:
            existing_lock = root / lock_path
            if existing_lock.is_file():
                prior = _read_json(existing_lock)
                if isinstance(prior, Mapping) and prior.get("event_id") not in {None, event["event_id"]}:
                    raise ReleaseTrainError("same Mapper version has a different release event identity")
                if isinstance(prior, Mapping) and prior.get("event_id") == event["event_id"]:
                    return dict(prior)

    changed = _update_dependency(root, version)
    _resolve_lock(root, version)
    locked_version, artifacts, lock_reason = tested_dependency_artifacts(MAPPER_COMPONENT, root)
    if locked_version != version or lock_reason != "locked_in_uv.lock":
        raise ReleaseTrainError(
            f"uv.lock did not resolve {MAPPER_COMPONENT} to {version}: {locked_version!r} ({lock_reason})"
        )
    event_digests = _event_artifact_digests(event)
    lock_digests = _locked_artifact_digests(artifacts)
    if event_digests != lock_digests:
        raise ReleaseTrainError(
            "uv.lock artifact digests do not match event: "
            f"event={sorted(event_digests)} lock={sorted(lock_digests)}"
        )
    declared_after = declared_dependency_range(MAPPER_COMPONENT, root)
    if declared_after is None or not declared_after.startswith(f">={version}"):
        raise ReleaseTrainError("pyproject.toml did not advance the Mapper lower bound")
    _update_registry(root, event, declared_after, locked_version)
    uv_lock = root / "uv.lock"
    receipt = {
        "schema": LOCK_SCHEMA,
        "status": "reconciled",
        "event_id": event["event_id"],
        "event_schema": EVENT_SCHEMA,
        "release_event": dict(event),
        "component": MAPPER_COMPONENT,
        "version": version,
        "commit_sha": event["commit_sha"],
        "artifact_digests": event["artifact_digests"],
        "declared_range": declared_after,
        "tested_against": locked_version,
        "tested_against_reason": lock_reason,
        "lockfile": "uv.lock",
        "lockfile_digest": _sha256(uv_lock),
        "conformance": {
            "required": ["n", "n_minus_1", "clean_installed_entrypoint", "map_retrieve_edit_test_receipt"],
            "status": "pending_gate",
        },
        "downstream": {
            "repository": "wesleysimplicio/simplicio-loop",
            "event_type": EVENT_SCHEMA,
            "status": "pending_dev_cli_pypi_publication",
        },
        "previous_locked_version": current,
        "previous_locked_reason": current_reason,
        "changed": changed or current != version or not had_release_lock,
        "plan_digest": canonical_digest(
            {
                "event_id": event["event_id"],
                "version": version,
                "commit_sha": event["commit_sha"],
                "artifact_digests": event["artifact_digests"],
            }
        ),
    }
    _write_json(root / lock_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reconcile", choices=["reconcile"])
    parser.add_argument("--root", type=Path, default=Path("."), help="Dev CLI checkout")
    parser.add_argument("--event", type=Path, required=True, help="release event or GitHub event JSON")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK, help="tracked release-train lock receipt")
    parser.add_argument("--json", action="store_true", help="emit the reconciliation receipt as JSON")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        event = _read_json(args.event.resolve())
        receipt = reconcile(root, event, lock_path=args.lock)
        print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ReleaseTrainError, TypeError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"schema": LOCK_SCHEMA, "status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
