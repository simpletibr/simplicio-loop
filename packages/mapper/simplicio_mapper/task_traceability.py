"""Static AC/RN traceability with explicit, receipt-gated execution state."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from typing import Any

TASK_TRACEABILITY_SCHEMA = "simplicio.task-traceability/v1"


def _text(criterion: Mapping[str, Any]) -> str:
    return " | ".join(
        str(value)
        for key in ("title", "given", "when", "then")
        for value in ([criterion.get(key)] if isinstance(criterion.get(key), str) else criterion.get(key, []))
        if value
    )


def _test_kind(path: str) -> str:
    lowered = path.casefold()
    if "playwright" in lowered or "e2e" in lowered or "visual" in lowered:
        return "e2e_visual"
    if "integration" in lowered or "contract" in lowered:
        return "integration"
    return "unit"


def _file_hash(root: str, path: str) -> str:
    try:
        with open(os.path.join(root, path), "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def build_task_traceability(
    root: str,
    intent: Mapping[str, Any],
    *,
    context_pack: Mapping[str, Any] | None = None,
    project_map: Mapping[str, Any] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    """Map AC/RN to static candidates; static mapping can never be verified."""
    files = list((context_pack or {}).get("files", []))
    project_map = project_map or {}
    rules = {str(rule.get("id")): rule for rule in intent.get("business_rules", []) if isinstance(rule, Mapping)}
    entries: list[dict[str, Any]] = []
    for criterion in intent.get("acceptance_criteria", []):
        if not isinstance(criterion, Mapping):
            continue
        rule_ids = sorted(set(str(value) for value in criterion.get("rule_ids", [])))
        candidates: list[dict[str, Any]] = []
        tests: list[dict[str, str]] = []
        for file_entry in files:
            path = str(file_entry.get("path", ""))
            if not path:
                continue
            candidates.append({
                "path": path,
                "line": 1,
                "symbols": list(file_entry.get("symbols", [])),
                "hash": _file_hash(root, path),
            })
            for test_path in file_entry.get("tests", []):
                test_path = str(test_path)
                tests.append({"path": test_path, "kind": _test_kind(test_path)})
        unique_tests = sorted({(test["path"], test["kind"]) for test in tests})
        mapping_status = "unmapped" if not candidates else ("ambiguous" if len(candidates) > 1 else "mapped")
        gaps = [] if candidates else ["no static file candidate"]
        entries.append({
            "id": str(criterion.get("id", "")),
            "text": _text(criterion),
            "rule_ids": rule_ids,
            "rules": [rules[rule_id] for rule_id in rule_ids if rule_id in rules],
            "files": candidates,
            "symbols": sorted({str(symbol) for item in candidates for symbol in item["symbols"]}),
            "flows": [],
            "tests": [{"path": path, "kind": kind} for path, kind in unique_tests],
            "mapping_status": mapping_status,
            "execution_status": "pending",
            "receipts": [],
            "gaps": gaps,
        })
    if not intent.get("prototypes"):
        prototype_gap = "no prototype declared"
    else:
        prototype_gap = ""
    mapped = sum(entry["mapping_status"] == "mapped" for entry in entries)
    total = len(entries)
    gaps = ([prototype_gap] if prototype_gap else []) + [
        f"{entry['id']}: {gap}" for entry in entries for gap in entry["gaps"]
    ]
    return {
        "schema": TASK_TRACEABILITY_SCHEMA,
        "task_id": task_id,
        "task": {"schema": intent.get("schema", ""), "fingerprint": intent.get("fingerprint", "")},
        "criteria": entries,
        "rules": [rules[key] for key in sorted(rules)],
        "coverage": {"mapped": mapped, "total": total, "ratio": round(mapped / total, 6) if total else 0.0},
        "complete": bool(total and mapped == total and not gaps),
        "gaps": gaps,
        "static_inference": True,
    }


def apply_receipts(
    traceability: dict[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    *,
    root: str,
) -> dict[str, Any]:
    """Apply only fresh, explicit verification receipts; stale evidence blocks."""
    by_id = {str(entry.get("id")): entry for entry in traceability.get("criteria", [])}
    for receipt in receipts:
        criterion_id = str(receipt.get("criterion_id", ""))
        entry = by_id.get(criterion_id)
        evidence = receipt.get("evidence", [])
        if entry is None or receipt.get("status") != "verified" or not receipt.get("command") or not evidence:
            continue
        stale = False
        for item in evidence:
            if not isinstance(item, Mapping):
                stale = True
                break
            path = str(item.get("path", ""))
            expected = str(item.get("hash", ""))
            if not path or not expected or _file_hash(root, path) != expected:
                stale = True
                break
        receipt_copy = dict(receipt)
        entry["receipts"].append(receipt_copy)
        if stale:
            entry["execution_status"] = "blocked"
            entry["gaps"].append(f"stale receipt: {receipt.get('receipt_id', '')}")
        else:
            entry["execution_status"] = "verified"
    traceability["complete"] = bool(
        traceability.get("criteria")
        and all(entry.get("execution_status") == "verified" for entry in traceability["criteria"])
        and not traceability.get("gaps")
    )
    return traceability


__all__ = ["TASK_TRACEABILITY_SCHEMA", "apply_receipts", "build_task_traceability"]
