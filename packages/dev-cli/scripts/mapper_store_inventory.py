#!/usr/bin/env python3
"""Inventory Dev CLI persistence boundaries and enforce the MapperStore cutover.

The inventory is intentionally source-based: it records every SQLite/DDL
reference in production Python, classifies the current owner, and fails closed
when a new direct connection appears outside the temporary migration allowlist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "simplicio-dev-cli.mapper-store-inventory/v2"
_MATCH = re.compile(r"sqlite3|index\.sqlite3|CREATE\s+(?:VIRTUAL\s+)?TABLE", re.IGNORECASE)
_CONNECT = re.compile(r"sqlite3\.connect\s*\(", re.IGNORECASE)
LEGACY_PATHS = (
    ".simplicio-loop/effect-transactions.sqlite3",
    ".simplicio-loop/mutation-worker.sqlite3",
    ".simplicio-loop/prism-transactions.sqlite3",
    ".simplicio-loop/write-set-locks.sqlite3",
    ".simplicio-loop/memory/index.sqlite3",
)

ALLOWLIST = {
    "simplicio/effect_transaction.py",
    "simplicio/memory_store.py",
    "simplicio/mutation_worker.py",
    "simplicio/prism_transaction.py",
    "simplicio/write_set_lock.py",
}

CLASSIFICATION = {
    "simplicio/store_adapter.py": {
        "kind": "detection",
        "owner": "Dev CLI diagnostics",
        "source_of_truth": "MapperStore capability and legacy-path presence",
        "current_path": "read-only path inventory",
        "target": "MapperStore domains; no local database writer",
    },
    "simplicio/templates/stacks/py-django/tree/config/settings.py": {
        "kind": "fixture",
        "owner": "Django template consumer",
        "source_of_truth": "generated project configuration",
        "current_path": "template-only",
        "target": "excluded from Dev CLI persistence boundary",
    },
    "simplicio/memory_store.py": {
        "kind": "derived_index",
        "owner": "DevCli legacy memory adapter",
        "source_of_truth": "memory Markdown/files",
        "current_path": ".simplicio-loop/memory/index.sqlite3",
        "target": "MapperStore memory/handoff",
    },
    "simplicio/effect_transaction.py": {
        "kind": "transaction_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "transaction receipt state",
        "current_path": ".simplicio-loop/effect-transactions.sqlite3",
        "target": "MapperStore ledger adapter; preserve Dev CLI receipt ownership",
    },
    "simplicio/mutation_worker.py": {
        "kind": "mutation_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "mutation lifecycle receipt",
        "current_path": ".simplicio-loop/mutation-worker.sqlite3",
        "target": "MapperStore transaction/ledger adapter",
    },
    "simplicio/prism_transaction.py": {
        "kind": "transaction_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "PRISM transaction receipt",
        "current_path": ".simplicio-loop/prism-transactions.sqlite3",
        "target": "MapperStore transaction adapter",
    },
    "simplicio/write_set_lock.py": {
        "kind": "lock_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "write-set fencing/lock state",
        "current_path": ".simplicio-loop/write-set-locks.sqlite3",
        "target": "MapperStore lock adapter",
    },
}

MATERIALIZED_PLANS = {
    ".simplicio-loop/mapper-store/route.json": {
        "kind": "route_receipt",
        "owner": "Dev CLI",
        "source_of_truth": "selected MapperStore route and capability gate",
        "current_path": ".simplicio-loop/mapper-store/route.json",
        "target": "durable route freeze before the first effect intent",
    },
    ".simplicio-loop/mapper-store/effect-transactions": {
        "kind": "transaction_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "transaction receipt state",
        "current_path": ".simplicio-loop/mapper-store/effect-transactions",
        "target": "MapperStore effect transaction records",
    },
    ".simplicio-loop/mapper-store/mutations": {
        "kind": "mutation_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "mutation lifecycle receipt",
        "current_path": ".simplicio-loop/mapper-store/mutations",
        "target": "MapperStore mutation records",
    },
    ".simplicio-loop/mapper-store/prism-transactions": {
        "kind": "transaction_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "PRISM transaction receipt",
        "current_path": ".simplicio-loop/mapper-store/prism-transactions",
        "target": "MapperStore PRISM transaction records",
    },
    ".simplicio-loop/mapper-store/locks": {
        "kind": "lock_ledger",
        "owner": "Dev CLI",
        "source_of_truth": "write-set fencing/lock state",
        "current_path": ".simplicio-loop/mapper-store/locks",
        "target": "MapperStore lock records",
    },
    ".simplicio-loop/mapper-store/memory-index": {
        "kind": "derived_index",
        "owner": "Dev CLI memory adapter",
        "source_of_truth": "memory Markdown/files",
        "current_path": ".simplicio-loop/mapper-store/memory-index",
        "target": "MapperStore memory index records",
    },
    ".simplicio-loop/mapper-store/memory-notes": {
        "kind": "derived_notes",
        "owner": "Dev CLI memory adapter",
        "source_of_truth": "memory Markdown/files",
        "current_path": ".simplicio-loop/mapper-store/memory-notes",
        "target": "MapperStore memory handoff records",
    },
}


def _digest(payload: Any) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def inventory(root: Path) -> dict[str, Any]:
    production_root = root / "simplicio"
    occurrences: list[dict[str, Any]] = []
    for path in sorted(production_root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not _MATCH.search(line):
                continue
            occurrences.append(
                {
                    "path": relative,
                    "line": line_number,
                    "text": line.strip(),
                    "direct_connection": bool(_CONNECT.search(line)),
                    "allowlisted": relative in ALLOWLIST,
                }
            )
    stores = []
    for path in sorted({item["path"] for item in occurrences}):
        stores.append({"path": path, **CLASSIFICATION.get(path, {"kind": "unclassified"})})
    direct_outside_allowlist = [
        item for item in occurrences if item["direct_connection"] and not item["allowlisted"]
    ]
    strict_violations = [
        item
        for item in occurrences
        if item["path"] not in ALLOWLIST
        and CLASSIFICATION.get(item["path"], {}).get("kind") not in {"fixture", "detection"}
    ]
    materialized: list[dict[str, Any]] = []
    materialized_root = root / ".simplicio-loop" / "mapper-store"
    if materialized_root.is_dir():
        for path in sorted(item for item in materialized_root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            plan_key = next(
                (key for key in MATERIALIZED_PLANS if relative == key or relative.startswith(key + "/")),
                None,
            )
            plan = MATERIALIZED_PLANS.get(plan_key or "", {})
            materialized.append(
                {
                    "path": relative,
                    **(
                        plan
                        or {
                            "kind": "unclassified",
                            "owner": "unknown",
                            "source_of_truth": "unknown",
                            "current_path": relative,
                            "target": "blocked until classified",
                        }
                    ),
                }
            )
    for legacy_path in LEGACY_PATHS:
        path = root / legacy_path
        if path.is_file():
            materialized.append(
                {
                    "path": legacy_path,
                    **CLASSIFICATION.get(
                        legacy_path,
                        {
                            "kind": "legacy",
                            "owner": "Dev CLI",
                            "source_of_truth": "legacy state",
                            "current_path": legacy_path,
                            "target": "MapperStore; read-only during cutover",
                        },
                    ),
                }
            )
    materialized_strict_violations = [row for row in materialized if row["kind"] == "unclassified"]
    store_plans = [{"path": path, **plan} for path, plan in sorted(MATERIALIZED_PLANS.items())]
    payload = {
        "schema": SCHEMA,
        "inventory_version": 2,
        "root": str(root.resolve()),
        "stores": stores,
        "store_plans": store_plans,
        "materialized_files": materialized,
        "occurrences": occurrences,
        "direct_connections_outside_allowlist": direct_outside_allowlist,
        "strict_violations": strict_violations + materialized_strict_violations,
        "strict": not strict_violations and not materialized_strict_violations,
    }
    payload["inventory_digest"] = _digest(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    payload = inventory(args.root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if (not args.strict or payload["strict"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
