#!/usr/bin/env python3
"""check_schema_registry_sync.py -- schema-version-registry drift gate (issue #280).

Sibling to `scripts/check-version-sync.js`: that script keeps the three
*package*-version sources of truth (`package.json`, `pyproject.toml`,
`simplicio_mapper/__init__.py`) aligned. It does NOT cover the many
independent schema-version constants this package publishes (e.g.
`ARTIFACT_VERSION`, `CANONICAL_MAP_SCHEMA_VERSION`, `CONTRACT_VERSION` --
see `simplicio_mapper/release_manifest.py::SCHEMA_VERSION_REGISTRY` for the
full inventory). This script closes that gap without inventing PyPI/npm
registry-divergence detection (which would need real registry API calls --
explicitly out of scope for this Phase-0 slice, see
`.specs/architecture/ADR-010-release-manifest-phase0.md`).

It compares the live value of every registered schema-version constant
against the committed baseline (`scripts/schema_registry_baseline.json`) and
fails when they disagree -- catching an *unintentional* schema-version bump
(or an accidentally stale/renamed registry entry) the same way
`check-version-sync.js` catches a partial package-version bump.

Usage:
    python3 scripts/check_schema_registry_sync.py                     # check against baseline (CI)
    python3 scripts/check_schema_registry_sync.py --update-baseline    # regenerate baseline after
                                                                         a deliberate, reviewed bump

Exit codes: 0 = registry matches baseline (or baseline updated), 1 = drift
detected / registry entry broken.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, REPO_ROOT)

from simplicio_mapper.release_manifest import (  # noqa: E402
    ReleaseManifestError,
    check_registry_baseline,
    write_registry_baseline,
)


def main(argv: list[str]) -> int:
    if "--update-baseline" in argv:
        try:
            doc = write_registry_baseline()
        except ReleaseManifestError as error:
            print(f"[err] {error}", file=sys.stderr)
            return 1
        print(f"[ok] wrote {len(doc['entries'])} entries to scripts/schema_registry_baseline.json")
        return 0

    try:
        ok, messages = check_registry_baseline()
    except ReleaseManifestError as error:
        print(f"[err] {error}", file=sys.stderr)
        return 1
    for message in messages:
        print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
