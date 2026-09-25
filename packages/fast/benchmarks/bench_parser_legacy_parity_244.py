"""Frozen Python parser-adapter versus legacy extractor parity receipt (#244)."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
from typing import Any

from simplicio_fast.parser_adapter import build_payload
from simplicio_fast.snapshot import _parse_file


SCHEMA = "simplicio.fast.parser-legacy-parity-receipt/v1"
CORPUS_SCHEMA = "simplicio.fast.golden-corpus/v1"
DEFAULT_ROOT = Path("fixtures/conformance/v1")


def _digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _legacy_symbols(parsed: list[Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (item.name, item.qualified_name, item.kind, item.file, item.line, item.end_line)
        for item in parsed
    )


def _adapter_symbols(payload: dict[str, Any], path: str) -> list[tuple[Any, ...]]:
    return sorted(
        (
            item["name"],
            item["qualified_name"],
            item["kind"],
            item["file"],
            item["line"],
            item["end_line"],
        )
        for item in payload["symbols"]
        if item["file"] == path
    )


def _legacy_relations(parsed: list[Any]) -> Counter[tuple[Any, ...]]:
    return Counter((item.origin, item.destination, item.kind) for item in parsed)


def _adapter_relations(payload: dict[str, Any], path: str) -> Counter[tuple[Any, ...]]:
    return Counter(
        (item["origin"], item["destination"], item["kind"])
        for item in payload["relations"]
        if item["file"] == path
    )


def run(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    corpus = json.loads((root / "corpus.json").read_text(encoding="utf-8"))
    if corpus.get("schema") != CORPUS_SCHEMA:
        raise ValueError("parser_corpus_schema_invalid")
    first = build_payload(root)
    second = build_payload(root)
    python_files = [item for item in first["files"] if item["language"] == "python"]
    cases: list[dict[str, Any]] = []
    all_symbols_match = True
    all_relations_match = True
    source_hashes_match = True
    for file_item in python_files:
        relative = str(file_item["path"])
        parsed, legacy_relations = _parse_file(root / relative, relative, str(root))
        adapter_symbols = _adapter_symbols(first, relative)
        legacy_symbols = _legacy_symbols(parsed)
        adapter_relations = _adapter_relations(first, relative)
        legacy_relation_counts = _legacy_relations(legacy_relations)
        symbol_match = adapter_symbols == legacy_symbols
        relation_match = adapter_relations == legacy_relation_counts
        actual_hash = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        hash_match = actual_hash == file_item["sha256"]
        all_symbols_match = all_symbols_match and symbol_match
        all_relations_match = all_relations_match and relation_match
        source_hashes_match = source_hashes_match and hash_match
        cases.append(
            {
                "path": relative,
                "symbols": len(adapter_symbols),
                "relations": sum(adapter_relations.values()),
                "symbol_parity": symbol_match,
                "relation_parity": relation_match,
                "source_hash_match": hash_match,
                "adapter_symbol_digest": _digest(adapter_symbols),
                "legacy_symbol_digest": _digest(legacy_symbols),
                "adapter_relation_digest": _digest(sorted(adapter_relations.elements())),
                "legacy_relation_digest": _digest(sorted(legacy_relation_counts.elements())),
            }
        )
    return {
        "schema": SCHEMA,
        "status": "pass" if first == second and all_symbols_match and all_relations_match and source_hashes_match else "fail",
        "corpus": {
            "schema": CORPUS_SCHEMA,
            "id": corpus.get("corpus_id"),
            "manifest_digest": _digest(corpus),
            "root": str(root),
        },
        "adapter": {
            "payload_sha256": first["payload_sha256"],
            "byte_identical_rebuild": first == second,
            "mode": first["mode"],
            "completeness": first["completeness"],
            "files": len(first["files"]),
            "symbols": len(first["symbols"]),
            "relations": len(first["relations"]),
        },
        "python_cases": cases,
        "parity": {
            "symbols": all_symbols_match,
            "relations": all_relations_match,
            "source_hashes": source_hashes_match,
        },
        "authority": "derived_read_only",
        "native_languages": {
            "status": "partial",
            "reason": "native_csharp_typescript_rust_adapters_are_separate_gates",
        },
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.root)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


__all__ = ["CORPUS_SCHEMA", "SCHEMA", "run"]


if __name__ == "__main__":
    main()
