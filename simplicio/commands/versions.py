"""``simplicio-cli versions`` — report installed/declared/tested/own-manifest
version state for this repo's Mapper dependency (issue #232).

This is the Dev CLI's *consuming* half of the release-train issue: it
parses/validates ``simplicio.component-release/v1`` manifests
(:mod:`simplicio.component_manifest`), checks the installed
`simplicio-mapper` against this repo's own declared compatibility range,
and reports drift — all read-only, all local.

Explicitly NOT implemented here, and why:

- **``latest_known`` via live PyPI/npm query** — no network registry
  access in this environment. Reporting a fabricated "latest" would be
  worse than reporting none, so this field is always ``null`` with an
  explicit ``unavailable_reason: "no_registry_access"``. (Note:
  `simplicio.ecosystem` *does* do a live PyPI lookup for its own
  freshness check with a 24h cache; this command deliberately does not
  reuse that here, to keep `versions --json`'s claims strictly limited to
  what can be verified from files already on disk, per the issue's
  "never fabricate a version number" instruction. A future revision could
  wire `ecosystem._pypi_latest` in as a *best-effort, clearly labeled*
  addition, but that's a separate, deliberate decision, not folded in.)
- **Receiving a Mapper release event over a real transport** — no event
  bus/webhook receiver exists in this repo or session.
  `component_manifest.parse_component_manifest` is ready to validate a
  manifest the moment one arrives (see its docstring), but nothing
  delivers one today.
- **Auto-creating/merging a version-bump PR** — this session does have
  GitHub tooling available, but auto-merging a dependency bump without
  human review directly contradicts this repo's own AGENTS.md rules
  ("Adicionar dependência sem perguntar" is on the forbidden list, and the
  DoD requires human review). Declared out of scope, not a capability gap.
- **SBOM/signing/provenance** — no signing identity available in this
  environment.
- **Triggering `simplicio-loop`** — that repo is not in this session's
  scope.
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
    tested_dependency_version,
)

CLI_PROG = "simplicio-py"
MAPPER_DIST_NAME = "simplicio-mapper"


def _installed_mapper_version() -> str | None:
    try:
        return metadata.version(MAPPER_DIST_NAME)
    except metadata.PackageNotFoundError:
        return None


def versions_report(root: str | Path | None = None) -> dict[str, Any]:
    """Build the full `versions --json` payload. Pure read path: every
    field comes from `importlib.metadata`, `pyproject.toml`, `uv.lock`, or
    `git rev-parse` — no mutation, no lock/state touched, safe to call
    concurrently with a running `pipeline.run_task` (issue #232 item 13;
    see `tests/python/test_versions_command.py` for the concurrency
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
    """
    root = str(root) if root is not None else None
    installed = _installed_mapper_version()
    declared_range = declared_dependency_range(MAPPER_DIST_NAME, root)
    tested_against, tested_reason = tested_dependency_version(MAPPER_DIST_NAME, root)

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

    return {
        "schema": "simplicio.dev-cli.versions/v1",
        "mapper": {
            "installed": installed,
            "declared_range": declared_range,
            "tested_against": tested_against,
            "tested_against_reason": tested_reason,
            "latest_known": None,
            "unavailable_reason": "no_registry_access",
            "compatibility": compatibility.to_dict() if compatibility else None,
        },
        "drift": drift.to_dict(),
        "own_manifest": own_manifest.to_dict(),
    }


def _render_human(payload: dict[str, Any]) -> None:
    mapper = payload["mapper"]
    print(f"{CLI_PROG} versions")
    print(f"  simplicio-mapper installed        {mapper['installed'] or '(not installed)'}")
    print(f"  simplicio-mapper declared_range    {mapper['declared_range'] or '(none declared)'}")
    tested_display = mapper["tested_against"] or f"null ({mapper['tested_against_reason']})"
    print(f"  simplicio-mapper tested_against    {tested_display}")
    print(f"  simplicio-mapper latest_known      null ({mapper['unavailable_reason']})")
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


def run(a: argparse.Namespace) -> int:
    payload = versions_report(getattr(a, "root", None))
    if getattr(a, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_human(payload)
    return 0
