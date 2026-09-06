#!/usr/bin/env python3
"""Build and validate the versioned Mapper capability matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "simplicio.mapper-capability-matrix/v1"
CONTRACT_VERSION = "v1"
STATUSES = frozenset({"MISSING", "SHADOW", "NATIVE_PARITY", "NATIVE_EVOLVED"})
LANGUAGES = ("python", "javascript", "typescript", "csharp", "razor", "go")
CAPABILITIES = (
    "files",
    "symbols",
    "imports",
    "calls",
    "architecture",
    "precedents",
    "endpoints",
    "business-rules",
    "flows",
    "docs",
    "retrieval",
    "batch",
)
BEHAVIOR_SOURCES = (
    "simplicio_mapper/_native.py",
    "simplicio_mapper/mapper/parse.py",
    "simplicio_mapper/mapper/async_inventory.py",
    "simplicio_mapper/mapper/graph.py",
    "simplicio_mapper/context_snapshot.py",
    "rust/mapper-core/src/lib.rs",
    "rust/src/lib.rs",
    "rust/runtime-adapter/src/lib.rs",
)
PARITY_PAIRS = frozenset(
    (language, capability)
    for language in LANGUAGES
    for capability in ("files", "imports", "batch")
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def mapper_version() -> str:
    from simplicio_mapper import __version__

    return __version__


def behavior_fingerprint(root: Path, sources: tuple[str, ...] = BEHAVIOR_SOURCES) -> str:
    entries = []
    for relative in sources:
        path = root / relative
        entries.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return digest(entries)


def load_matrix(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("capability matrix must be an object")
    return value


def _report_path(root: Path, matrix: dict[str, Any]) -> Path | None:
    relative = matrix.get("differential_report")
    return root / relative if isinstance(relative, str) else None


def validate_matrix(matrix: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    if matrix.get("schema") != SCHEMA:
        errors.append("schema_unsupported")
    if matrix.get("version") != 1:
        errors.append("matrix_version_unsupported")
    if matrix.get("contract_version") != CONTRACT_VERSION:
        errors.append("contract_version_unsupported")
    if matrix.get("mapper_version") != mapper_version():
        errors.append("mapper_version_stale")
    if matrix.get("behavior_sources") != list(BEHAVIOR_SOURCES):
        errors.append("behavior_sources_invalid")
    elif matrix.get("behavior_fingerprint") != behavior_fingerprint(root):
        errors.append("behavior_fingerprint_stale")
    rows = matrix.get("capabilities")
    if not isinstance(rows, list):
        return [*errors, "capabilities_not_array"]
    seen: set[tuple[str, str, str]] = set()
    parity_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            errors.append("capability_row_invalid")
            continue
        key = (str(row.get("language")), str(row.get("capability")), str(row.get("contract_version")))
        if key in seen:
            errors.append(f"capability_row_duplicate:{key[0]}@{key[1]}@{key[2]}")
        seen.add(key)
        if key[0] not in LANGUAGES or key[1] not in CAPABILITIES or key[2] != CONTRACT_VERSION:
            errors.append(f"capability_row_key_invalid:{key[0]}@{key[1]}@{key[2]}")
        status = row.get("status")
        if status not in STATUSES:
            errors.append(f"capability_status_invalid:{key[0]}@{key[1]}")
        if row.get("native_default") and status != "NATIVE_PARITY":
            errors.append(f"native_default_without_parity:{key[0]}@{key[1]}")
        if status == "NATIVE_PARITY":
            parity_rows.append(row)
    expected = {(language, capability, CONTRACT_VERSION) for language in LANGUAGES for capability in CAPABILITIES}
    if seen != expected:
        errors.append("capability_matrix_incomplete")
    report = _report_path(root, matrix)
    if parity_rows:
        if report is None or not report.is_file():
            errors.append("differential_evidence_missing")
        else:
            try:
                evidence = load_matrix(report)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append("differential_evidence_invalid")
            else:
                evidence_body = {
                    key: value for key, value in evidence.items() if key != "report_digest"
                }
                if evidence.get("report_digest") != digest(evidence_body):
                    errors.append("differential_evidence_digest_invalid")
                if evidence.get("schema") != "simplicio.mapper-differential/v1" or evidence.get("status") != "match":
                    errors.append("differential_evidence_not_green")
                elif evidence.get("mapper_version") != mapper_version():
                    errors.append("differential_evidence_mapper_version_stale")
                elif evidence.get("behavior_fingerprint") != behavior_fingerprint(root):
                    errors.append("differential_evidence_behavior_fingerprint_stale")
                elif matrix.get("differential_report_digest") != evidence.get("report_digest"):
                    errors.append("differential_evidence_digest_mismatch")
                else:
                    green = {
                        (item.get("language"), item.get("capability"), item.get("contract_version"))
                        for item in evidence.get("results", [])
                        if (
                            isinstance(item, dict)
                            and item.get("status") == "match"
                            and item.get("native_default") is True
                        )
                    }
                    for row in parity_rows:
                        key = (row.get("language"), row.get("capability"), row.get("contract_version"))
                        if key not in green:
                            errors.append(f"parity_without_green_fixture:{key[0]}@{key[1]}")
    return errors


def build_matrix(root: Path, report: dict[str, Any] | None = None) -> dict[str, Any]:
    green = {
        (item.get("language"), item.get("capability"), item.get("contract_version"))
        for item in (report or {}).get("results", [])
        if (
            isinstance(item, dict)
            and item.get("status") == "match"
            and item.get("native_default") is True
        )
    }
    rows = []
    for language in LANGUAGES:
        for capability in CAPABILITIES:
            key = (language, capability, CONTRACT_VERSION)
            status = "NATIVE_PARITY" if key in green and key[:2] in PARITY_PAIRS else (
                "SHADOW" if capability == "symbols" else "MISSING"
            )
            rows.append(
                {
                    "language": language,
                    "capability": capability,
                    "contract_version": CONTRACT_VERSION,
                    "status": status,
                    "native_default": status == "NATIVE_PARITY",
                    "evidence_id": "mapper-core-differential" if status == "NATIVE_PARITY" else None,
                }
            )
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "version": 1,
        "mapper_version": mapper_version(),
        "contract_version": CONTRACT_VERSION,
        "behavior_sources": list(BEHAVIOR_SOURCES),
        "behavior_fingerprint": behavior_fingerprint(root),
        "differential_report": "artifacts/mapper-differential.json",
        "differential_report_digest": (report or {}).get("report_digest"),
        "capabilities": rows,
    }
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--path", default="contracts/mapper-core/v1/capability-matrix.json")
    parser.add_argument("--report", default="artifacts/mapper-differential.json")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    path = root / args.path
    if args.write:
        report = load_matrix(root / args.report) if (root / args.report).is_file() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(build_matrix(root, report)) + "\n", encoding="utf-8")
    matrix = load_matrix(path)
    errors = validate_matrix(matrix, root)
    print(canonical_json({"schema": "simplicio.mapper-capability-matrix-check/v1", "valid": not errors, "errors": errors}))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
