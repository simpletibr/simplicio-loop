"""SFAST v2 golden-corpus digest and span/symbol normalization helpers.

Python is the only engine, so this module no longer runs a differential
comparison against a second implementation; it keeps the corpus-integrity
and normalization primitives that the golden-corpus contract tests rely on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "simplicio.fast.conformance/v1"


DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "conformance" / "v1"
GOLDEN_CORPUS_SCHEMA = "simplicio.fast.golden-corpus/v1"


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _corpus_digest(corpus: Path) -> str:
    root = corpus.resolve()
    manifest_path = root / "corpus.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"corpus_manifest_invalid: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != GOLDEN_CORPUS_SCHEMA:
        raise RuntimeError("corpus_schema_mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("corpus_files_missing")
    digest = hashlib.sha256()
    digest.update(b"manifest\0")
    digest.update(
        json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )
    for entry in sorted(files, key=lambda item: str(item.get("path", ""))):
        relative = entry.get("path") if isinstance(entry, dict) else None
        expected = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RuntimeError("corpus_file_entry_invalid")
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise RuntimeError(f"corpus_path_escape: {relative}")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise RuntimeError(f"corpus_file_missing: {relative}") from error
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise RuntimeError(f"corpus_digest_mismatch: {relative}")
        digest.update(b"\0" + relative.encode("utf-8") + b"\0" + raw)
    return digest.hexdigest()


def _normalize_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: value[key] for key in sorted(value)}


def _normalize_reason_codes(value: Any) -> Any:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return value
    return sorted(value)


def normalize(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_version": stats.get("format_version", stats.get("version")),
        "bytes": stats.get("bytes"),
        "files": stats.get("files"),
        "symbols": stats.get("symbols"),
        "relations": stats.get("relations"),
        "sections": sorted(stats.get("sections", [])),
        "generation": stats.get("generation"),
        "source_hashes": _normalize_mapping(stats.get("source_hashes")),
        "budgets": _normalize_mapping(stats.get("budgets")),
        "truncations": _normalize_mapping(stats.get("truncations")),
        "reason_codes": _normalize_reason_codes(stats.get("reason_codes")),
    }


def normalize_symbols(symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "name",
        "qualified_name",
        "kind",
        "file",
        "line",
        "end_line",
        "symbol_id",
        "signature",
    )
    return [{field: symbol.get(field) for field in fields} for symbol in symbols]


def normalize_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "symbol",
        "kind",
        "file",
        "start_line",
        "end_line",
        "source_sha256",
        "content",
        "symbol_id",
        "tokens",
    )
    return [{field: span.get(field) for field in fields} for span in spans]
