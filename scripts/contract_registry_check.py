#!/usr/bin/env python3
"""Portable conformance check for the #802 contract registry.

The script is intentionally stdlib-only at the command boundary.  It can be
copied with ``contracts/registry/v1`` into Mapper or Dev CLI and run
there without contacting GitHub or a provider.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow the checker to run directly from a source checkout without requiring
# an editable install; the same layout is used when copied to another repo.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simplicio_loop.contract_registry import ContractRegistry, ContractValidationError, REGISTRY_ID


def check(registry_path: Path, fixtures_path: Path) -> Dict[str, Any]:
    registry = ContractRegistry(registry_path)
    valid: List[str] = []
    invalid: List[Dict[str, str]] = []
    failures: List[Dict[str, str]] = []
    for fixture in sorted(fixtures_path.glob("*.json")):
        data = json.loads(fixture.read_text(encoding="utf-8"))
        expected_invalid = fixture.name.startswith("invalid-")
        try:
            registry.validate(data)
        except ContractValidationError as exc:
            if expected_invalid:
                invalid.append({"fixture": fixture.name, "reason_code": exc.reason_code})
            else:
                failures.append({"fixture": fixture.name, "error": exc.reason_code})
        else:
            if expected_invalid:
                failures.append({"fixture": fixture.name, "error": "expected rejection"})
            else:
                valid.append(fixture.name)
    return {
        "schema": REGISTRY_ID,
        "registry_version": registry.document.get("version"),
        "contracts": len(registry.all()),
        "valid_fixtures": valid,
        "invalid_fixtures": invalid,
        "failures": failures,
        "verdict": "PASS" if not failures and valid and invalid else "FAIL",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=None, help="registry.json path")
    parser.add_argument("--fixtures", type=Path, default=None, help="fixture directory")
    parser.add_argument("--json", action="store_true", help="emit a JSON receipt")
    args = parser.parse_args(argv)
    registry_path = args.registry or (Path(__file__).resolve().parent.parent / "contracts" / "registry" / "v1" / "registry.json")
    fixtures_path = args.fixtures or registry_path.parent / "fixtures"
    try:
        result = check(registry_path, fixtures_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"schema": REGISTRY_ID, "verdict": "ERROR", "error": str(exc)}
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("contract registry: %s (%d contracts, %d valid, %d invalid)" % (
            result.get("verdict"), result.get("contracts", 0),
            len(result.get("valid_fixtures", [])), len(result.get("invalid_fixtures", [])),
        ))
    return 0 if result.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
