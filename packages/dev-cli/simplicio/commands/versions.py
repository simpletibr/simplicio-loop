"""``simplicio-cli versions`` — report installed/declared/tested/own-manifest
version state for this repo's Mapper dependency (issue #232).

This is the Dev CLI's *consuming* half of the release-train issue: it
parses/validates ``simplicio.component-release/v1`` manifests
(:mod:`simplicio.component_manifest`), checks the installed
`simplicio-mapper` against this repo's own declared compatibility range,
and reports drift — all read-only, all local.

``latest_known`` is best-effort via ``simplicio.ecosystem._pypi_latest``
(24h disk cache, optional ``--refresh``). When the registry is unreachable
and the cache is empty the field is ``null`` with
``unavailable_reason: "registry_unreachable"`` — never a fabricated version.

This read-only command deliberately does not mutate the checkout. The checked-
in release-train workflows own authenticated event receipt, deduplicated PR
updates, PyPI publication, and Loop propagation; this command reports their
local version/drift state and remains safe to run during an active task.

The workflow boundary is intentional:

- **Receiving a Mapper release event** is handled by
  `.github/workflows/release-train-reconcile.yml`.
- **Creating or merging a version-bump PR** is handled by the fixed
  `release-train/mapper-latest` branch and its gate/promote workflows.
- **Dispatching `simplicio-loop`** is handled only after the signed PyPI
  publication receipt in `.github/workflows/publish.yml`.
- **SBOM/signing/provenance** — no signing identity available in this
  environment.
"""

from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path
from typing import Any

from ..component_manifest import (
    build_own_manifest,
    check_version_against_range,
    declared_dependency_range,
    detect_drift,
    tested_dependency_artifacts,
    tested_dependency_version,
)
from ..ecosystem import _pypi_latest
from ..release_train import release_train_doctor

CLI_PROG = "simplicio-py"
MAPPER_DIST_NAME = "simplicio-mapper"


def _installed_mapper_version() -> str | None:
    try:
        return metadata.version(MAPPER_DIST_NAME)
    except metadata.PackageNotFoundError:
        return None


def _latest_mapper_version(*, refresh: bool = False) -> tuple[str | None, str | None]:
    """Best-effort PyPI latest for mapper. Returns ``(version, reason)``.

    *reason* is set only when *version* is ``None`` (honest null, never
    fabricated). When a version is returned, *reason* is ``None`` and the
    source is the ecosystem 24h cache or a live lookup after ``refresh``.
    """
    latest = _pypi_latest(MAPPER_DIST_NAME, refresh=refresh)
    if latest:
        return latest, None
    return None, "registry_unreachable"


def versions_report(
    root: str | Path | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Build the full `versions --json` payload. Read-only: every field
    comes from `importlib.metadata`, `pyproject.toml`, `uv.lock`,
    `git rev-parse`, or the ecosystem PyPI cache — no mutation, no
    lock/state touched, safe to call concurrently with a running
    `pipeline.run_task` (issue #232 item 13; see
    `tests/python/test_versions_command.py` for the concurrency
    regression test).

    *root* names the `simplicio-cli` checkout to introspect (its own
    `pyproject.toml`/`uv.lock`/git commit — NOT the user's target project
    being edited by `task`/`run`). Defaults to ``None``, which auto-detects:
    current working directory first, then this installed package's own
    parent directory (see `component_manifest._pyproject_path`). This is
    deliberately independent of `doctor`'s `--root` (the target project
    root for `.simplicio/events.jsonl`) — the two roots answer different
    questions and are never the same path in the common case of a `pip
    install`ed `simplicio-cli` used against some other project.

    *refresh* bypasses the 24h PyPI cache for ``latest_known`` (same
    semantics as `doctor --refresh`).
    """
    root = str(root) if root is not None else None
    installed = _installed_mapper_version()
    declared_range = declared_dependency_range(MAPPER_DIST_NAME, root)
    tested_against, tested_reason = tested_dependency_version(MAPPER_DIST_NAME, root)
    tested_artifact_version, tested_artifacts, tested_artifact_reason = tested_dependency_artifacts(
        MAPPER_DIST_NAME, root
    )
    latest_known, unavailable_reason = _latest_mapper_version(refresh=refresh)

    compatibility = (
        check_version_against_range(installed, declared_range, name=MAPPER_DIST_NAME) if installed else None
    )
    drift = detect_drift(
        name=MAPPER_DIST_NAME,
        installed=installed,
        declared_range=declared_range,
        tested_against=tested_against,
    )
    own_manifest = build_own_manifest(root)
    release_train = release_train_doctor(root)
    latest_compatible = (
        latest_known is not None
        and declared_range is not None
        and check_version_against_range(latest_known, declared_range, name=MAPPER_DIST_NAME).status
        == "compatible"
    )
    upgrade_available = bool(
        installed and latest_compatible and latest_known != installed and latest_known is not None
    )

    return {
        "schema": "simplicio.dev-cli.versions/v1",
        "mapper": {
            "installed": installed,
            "declared_range": declared_range,
            "required": declared_range,
            "tested_against": tested_against,
            "tested_against_reason": tested_reason,
            "tested_artifact_version": tested_artifact_version,
            "tested_artifacts": tested_artifacts,
            "tested_artifacts_reason": tested_artifact_reason,
            "latest_known": latest_known,
            "unavailable_reason": unavailable_reason,
            "compatibility": compatibility.to_dict() if compatibility else None,
            "upgrade": {
                "available": upgrade_available,
                "from": installed,
                "to": latest_known if upgrade_available else None,
                "action": "recreate environment from the updated lockfile" if upgrade_available else None,
                "safe_while_task_active": True,
            },
        },
        "drift": drift.to_dict(),
        "own_manifest": own_manifest.to_dict(),
        "release_train": release_train,
    }


def _render_human(payload: dict[str, Any]) -> None:
    mapper = payload["mapper"]
    print(f"{CLI_PROG} versions")
    print(f"  simplicio-mapper installed        {mapper['installed'] or '(not installed)'}")
    print(f"  simplicio-mapper declared_range    {mapper['declared_range'] or '(none declared)'}")
    tested_display = mapper["tested_against"] or f"null ({mapper['tested_against_reason']})"
    print(f"  simplicio-mapper tested_against    {tested_display}")
    if mapper["latest_known"]:
        print(f"  simplicio-mapper latest_known      {mapper['latest_known']}")
    else:
        reason = mapper["unavailable_reason"] or "unknown"
        print(f"  simplicio-mapper latest_known      null ({reason})")
    if mapper["compatibility"]:
        print(
            f"  compatibility                     "
            f"{mapper['compatibility']['status']} — {mapper['compatibility']['reason']}"
        )
    drift = payload["drift"]
    if drift["has_drift"]:
        print(f"  drift                              {drift['kind']}: {drift['reason']}")
    else:
        print("  drift                              none")
    own = payload["own_manifest"]
    print()
    print("own component manifest (simplicio.component-release/v1):")
    print(f"  name          {own['name']}")
    print(f"  version       {own['version']}")
    print(f"  commit        {own['commit'] or '(unknown)'}")
    print(f"  schema count  {len(own['schema_versions'])}")
    train = payload["release_train"]
    print()
    print("release train readiness:")
    print(f"  status        {train['status']}")
    print(f"  reason        {train['reason_code']}")


def run(a: argparse.Namespace) -> int:
    payload = versions_report(
        getattr(a, "root", None),
        refresh=bool(getattr(a, "refresh", False)),
    )
    if getattr(a, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_human(payload)
    return 0
