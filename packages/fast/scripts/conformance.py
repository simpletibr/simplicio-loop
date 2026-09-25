"""Run the bounded Python/Rust SFAST v2 differential conformance gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
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


def _json_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        close_fds=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "reason": "engine_command_failed",
                    "command": command,
                    "returncode": completed.returncode,
                    "stderr": completed.stderr.strip(),
                },
                sort_keys=True,
            )
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"engine_output_invalid_json: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("engine_output_not_object")
    return value


def _require_envelope(
    payload: dict[str, Any], *, schema: str, engine: str | None = None
) -> dict[str, Any]:
    actual_schema = payload.get("schema")
    if actual_schema != schema:
        raise RuntimeError(
            f"engine_schema_mismatch: expected={schema} actual={actual_schema!r}"
        )
    actual_engine = payload.get("engine")
    if engine is not None and actual_engine != engine:
        raise RuntimeError(
            f"engine_identity_mismatch: expected={engine} actual={actual_engine!r}"
        )
    if engine is None and actual_engine == "rust":
        raise RuntimeError("python_engine_identity_mismatch")
    return payload


def _python_stats(snapshot: Path) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "simplicio_fast.cli",
        "stats",
        "--snapshot",
        str(snapshot),
        "--fast-engine",
        "python",
    ]
    payload = _require_envelope(
        _json_command(command), schema="simplicio.fast.stats/v1"
    )
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise RuntimeError("python_stats_missing")
    return stats


def _rust_stats(rust: Path, snapshot: Path) -> dict[str, Any]:
    payload = _require_envelope(
        _json_command([str(rust), "--stats", str(snapshot), "--json"]),
        schema="simplicio.fast.stats/v1",
        engine="rust",
    )
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise RuntimeError("rust_stats_missing")
    return stats


def _python_query(snapshot: Path, term: str) -> list[dict[str, Any]]:
    payload = _require_envelope(
        _json_command(
            [
                sys.executable,
                "-m",
                "simplicio_fast.cli",
                "query",
                term,
                "--snapshot",
                str(snapshot),
                "--limit",
                "50",
                "--fast-engine",
                "python",
            ]
        ),
        schema="simplicio.fast.query/v1",
    )
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise RuntimeError("python_query_missing")
    return matches


def _rust_query(rust: Path, snapshot: Path, term: str) -> list[dict[str, Any]]:
    payload = _require_envelope(
        _json_command(
            [str(rust), "--query", str(snapshot), term, "--limit", "50", "--json"]
        ),
        schema="simplicio.fast.query/v1",
        engine="rust",
    )
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise RuntimeError("rust_query_missing")
    return matches


def _python_context(snapshot: Path, root: Path, term: str) -> list[dict[str, Any]]:
    payload = _require_envelope(
        _json_command(
            [
                sys.executable,
                "-m",
                "simplicio_fast.cli",
                "context",
                term,
                "--root",
                str(root),
                "--snapshot",
                str(snapshot),
                "--max-results",
                "3",
                "--max-bytes",
                "24_000",
                "--fast-engine",
                "python",
            ]
        ),
        schema="simplicio.fast.context/v1",
    )
    spans = payload.get("spans")
    if not isinstance(spans, list):
        raise RuntimeError("python_context_missing")
    return spans


def _rust_context(
    rust: Path, snapshot: Path, root: Path, term: str
) -> list[dict[str, Any]]:
    payload = _require_envelope(
        _json_command(
            [
                str(rust),
                "--context",
                str(snapshot),
                str(root),
                term,
                "--limit",
                "3",
                "--max-bytes",
                "24000",
                "--json",
            ]
        ),
        schema="simplicio.fast.context/v1",
        engine="rust",
    )
    spans = payload.get("spans")
    if not isinstance(spans, list):
        raise RuntimeError("rust_context_missing")
    return spans


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


def run(
    snapshot: Path,
    rust: Path,
    term: str | None = None,
    root: Path | None = None,
    context_term: str | None = None,
    corpus: Path | None = None,
) -> dict[str, Any]:
    snapshot_digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    corpus_root = corpus or DEFAULT_CORPUS
    corpus_digest = _corpus_digest(corpus_root)
    python = _python_stats(snapshot)
    rust_stats = _rust_stats(rust, snapshot)
    python_normalized = normalize(python)
    rust_normalized = normalize(rust_stats)
    mismatches = {
        key: {"python": python_normalized[key], "rust": rust_normalized[key]}
        for key in python_normalized
        if python_normalized[key] != rust_normalized[key]
    }
    queries: dict[str, Any] = {}
    if term:
        python_symbols = normalize_symbols(_python_query(snapshot, term))
        rust_symbols = normalize_symbols(_rust_query(rust, snapshot, term))
        queries = {
            "term": term,
            "python": python_symbols,
            "rust": rust_symbols,
            "match": python_symbols == rust_symbols,
        }
    query_mismatch = bool(queries and not queries["match"])
    contexts: dict[str, Any] = {}
    if context_term:
        if root is None:
            raise RuntimeError("context_root_required")
        python_spans = normalize_spans(_python_context(snapshot, root, context_term))
        rust_spans = normalize_spans(_rust_context(rust, snapshot, root, context_term))
        contexts = {
            "term": context_term,
            "python": python_spans,
            "rust": rust_spans,
            "match": python_spans == rust_spans,
        }
    context_mismatch = bool(contexts and not contexts["match"])
    raw_engines = {"python": python, "rust": rust_stats}
    return {
        "schema": SCHEMA,
        "status": "pass"
        if not mismatches and not query_mismatch and not context_mismatch
        else "fail",
        "snapshot": str(snapshot.resolve()),
        "snapshot_sha256": snapshot_digest,
        "corpus": str(corpus_root.resolve()),
        "corpus_sha256": corpus_digest,
        "engines": {"python": python_normalized, "rust": rust_normalized},
        "engine_raw": raw_engines,
        "engine_sha256": {
            name: _canonical_digest(payload) for name, payload in raw_engines.items()
        },
        "mismatches": mismatches,
        "queries": queries,
        "query_mismatch": query_mismatch,
        "contexts": contexts,
        "context_mismatch": context_mismatch,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--rust", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--term", help="also compare a public symbol query")
    parser.add_argument("--context-term", help="also compare bounded source context")
    parser.add_argument(
        "--root", type=Path, help="source repository root for context comparison"
    )
    args = parser.parse_args()
    try:
        receipt = run(
            args.snapshot,
            args.rust,
            args.term,
            args.root,
            args.context_term,
            args.corpus,
        )
    except (OSError, RuntimeError) as error:
        receipt = {
            "schema": SCHEMA,
            "status": "error",
            "snapshot": str(args.snapshot.resolve()),
            "reason": str(error),
        }
    output = json.dumps(receipt, indent=2, sort_keys=True)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if receipt["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
