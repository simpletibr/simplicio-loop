"""Build an offline, fail-closed Python parser parity receipt for #244.

The frozen corpus is already the source of truth for language coverage.  This
receipt adds the missing Python-specific proof: the parser-adapter payload is
compared with the legacy ``snapshot._parse_file`` facts, while native parser
availability for the other languages remains explicit and unclaimed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from simplicio_fast.parser_adapter import SCHEMA as PARSER_SCHEMA
from simplicio_fast.parser_adapter import build_payload
from simplicio_fast.snapshot import _parse_file

SCHEMA = "simplicio.fast.parser-parity-receipt/v1"
CORPUS_SCHEMA = "simplicio.fast.golden-corpus/v1"
NATIVE_UNAVAILABLE = "native_parser_unavailable"


class ParserParityError(ValueError):
    """Raised when the offline corpus or parity receipt is not trustworthy."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as error:
        raise ParserParityError("receipt_value_not_json") from error


def _digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: Any) -> str:
    return _digest_bytes(_canonical(value))


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\0" in value or ":" in value:
        raise ParserParityError("corpus_path_invalid")
    normalized = value.replace("\\", "/")
    parts = normalized.split("/")
    candidate = PurePosixPath(normalized)
    if (
        candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or normalized.startswith("/")
    ):
        raise ParserParityError("corpus_path_invalid")
    return candidate.as_posix()


def load_corpus(corpus_root: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Load and hash every manifest-declared corpus byte exactly once."""

    root = corpus_root.resolve()
    manifest_path = root / "corpus.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ParserParityError("corpus_manifest_invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != CORPUS_SCHEMA:
        raise ParserParityError("corpus_schema_mismatch")
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ParserParityError("corpus_files_missing")

    digest = hashlib.sha256()
    digest.update(b"manifest\0")
    digest.update(_canonical(manifest))
    checked: list[dict[str, Any]] = []
    for entry in sorted(raw_files, key=lambda item: str(item.get("path", ""))):
        if not isinstance(entry, Mapping):
            raise ParserParityError("corpus_file_entry_invalid")
        relative = _safe_relative(entry.get("path"))
        expected = entry.get("sha256")
        if (
            not isinstance(expected, str)
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise ParserParityError("corpus_file_entry_invalid")
        path = (root / relative).resolve()
        if not path.is_file() or not path.is_relative_to(root):
            raise ParserParityError("corpus_file_missing")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ParserParityError("corpus_file_missing") from error
        actual = _digest_bytes(raw)
        if actual != expected:
            raise ParserParityError(f"corpus_digest_mismatch:{relative}")
        digest.update(b"\0" + relative.encode("utf-8") + b"\0" + raw)
        checked.append(
            {
                "path": relative,
                "language": entry.get("language"),
                "sha256": actual,
                "bytes": len(raw),
            }
        )
    return manifest, digest.hexdigest(), checked


def _source_commit(root: Path) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD^{commit}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
        )
    except OSError:
        return None, "git_unavailable"
    value = result.stdout.strip()
    if result.returncode or len(value) != 40:
        return None, "source_commit_unavailable"
    return value, None


def _legacy_python_facts(root: Path, relative: str) -> dict[str, list[dict[str, Any]]]:
    symbols, relations = _parse_file(root / relative, relative, str(root))
    symbol_ids = {
        item.qualified_name: item.symbol_id for item in symbols if item.symbol_id
    }
    symbol_rows = [
        {
            "id": item.symbol_id,
            "name": item.name,
            "qualified_name": item.qualified_name,
            "kind": item.kind,
            "language": "python",
            "file": relative,
            "line": item.line,
            "end_line": item.end_line,
            "signature": item.signature,
        }
        for item in symbols
    ]
    relation_rows = [
        {
            "origin": item.origin,
            "destination": item.destination,
            "kind": item.kind,
            "confidence": item.confidence,
            "origin_id": item.origin_id,
            "destination_id": item.destination_id
            or symbol_ids.get(item.destination, ""),
            "file": relative,
        }
        for item in relations
    ]
    return {
        "symbols": sorted(symbol_rows, key=lambda item: (item["line"], item["id"])),
        "relations": sorted(
            relation_rows,
            key=lambda item: (
                item["kind"],
                item["origin"],
                item["destination"],
            ),
        ),
    }


def _adapter_facts(
    payload: Mapping[str, Any], relative: str
) -> dict[str, list[dict[str, Any]]]:
    return {
        "symbols": sorted(
            [item for item in payload["symbols"] if item["file"] == relative],
            key=lambda item: (item["line"], item["id"]),
        ),
        "relations": sorted(
            [item for item in payload["relations"] if item["file"] == relative],
            key=lambda item: (
                item["kind"],
                item["origin"],
                item["destination"],
            ),
        ),
    }


def build_receipt(
    corpus_root: Path, *, source_root: Path | None = None
) -> dict[str, Any]:
    """Run the bounded parity check twice and return a deterministic receipt."""

    root = corpus_root.resolve()
    manifest, corpus_sha256, checked_files = load_corpus(root)
    first = build_payload(root)
    second = build_payload(root)
    first_bytes = _canonical(first)
    second_bytes = _canonical(second)
    deterministic = first_bytes == second_bytes
    if not deterministic:
        raise ParserParityError("adapter_nondeterministic")

    python_paths = [
        item["path"] for item in checked_files if item.get("language") == "python"
    ]
    parity_files: list[dict[str, Any]] = []
    combined_facts: dict[str, list[dict[str, Any]]] = {"symbols": [], "relations": []}
    for relative in python_paths:
        expected = _legacy_python_facts(root, relative)
        actual = _adapter_facts(first, relative)
        match = expected == actual
        for key, values in combined_facts.items():
            values.extend(actual[key])
        parity_files.append(
            {
                "path": relative,
                "status": "pass" if match else "fail",
                "legacy_symbols": len(expected["symbols"]),
                "adapter_symbols": len(actual["symbols"]),
                "legacy_relations": len(expected["relations"]),
                "adapter_relations": len(actual["relations"]),
                "legacy_facts_sha256": _digest(expected),
                "adapter_facts_sha256": _digest(actual),
            }
        )

    native_pending = sorted(
        {
            item["path"]
            for item in first["diagnostics"]
            if item.get("code") == NATIVE_UNAVAILABLE
        }
    )
    source_commit, source_commit_reason = _source_commit(source_root or root)
    parity_status = (
        "pass" if all(item["status"] == "pass" for item in parity_files) else "fail"
    )
    return {
        "schema": SCHEMA,
        "status": "complete"
        if not native_pending and parity_status == "pass"
        else "partial",
        "adapter": {
            "schema": PARSER_SCHEMA,
            "producer": first.get("producer"),
            "version": first.get("adapter_version"),
        },
        "source": {
            "commit": source_commit,
            "commit_reason": source_commit_reason,
        },
        "corpus": {
            "schema": manifest["schema"],
            "corpus_id": manifest.get("corpus_id"),
            "sha256": corpus_sha256,
            "files": checked_files,
            "languages": sorted(set(manifest.get("languages", []))),
        },
        "determinism": {
            "status": "pass",
            "runs": 2,
            "canonical_bytes_identical": deterministic,
            "adapter_payload_sha256": _digest_bytes(first_bytes),
            "declared_payload_sha256": first.get("payload_sha256"),
        },
        "python_legacy_parity": {
            "status": parity_status,
            "files": parity_files,
            "symbols": len(combined_facts["symbols"]),
            "relations": len(combined_facts["relations"]),
            "facts_sha256": _digest(combined_facts),
        },
        "native_pending": {
            "status": "none" if not native_pending else "blocked",
            "reason_code": None if not native_pending else NATIVE_UNAVAILABLE,
            "paths": native_pending,
        },
        "claims": {
            "python_legacy_parity": parity_status,
            "native_csharp_typescript_rust_parity": "unverified",
            "full_issue_244": "unverified",
        },
    }


def validate_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the receipt's public shape without rerunning the corpus."""

    if not isinstance(value, Mapping) or value.get("schema") != SCHEMA:
        raise ParserParityError("receipt_schema_invalid")
    if value.get("status") not in {"partial", "complete"}:
        raise ParserParityError("receipt_status_invalid")
    deterministic = value.get("determinism")
    if not isinstance(deterministic, Mapping) or deterministic.get("status") != "pass":
        raise ParserParityError("receipt_determinism_invalid")
    parity = value.get("python_legacy_parity")
    if not isinstance(parity, Mapping) or parity.get("status") != "pass":
        raise ParserParityError("receipt_parity_invalid")
    native = value.get("native_pending")
    if (
        not isinstance(native, Mapping)
        or native.get("status") not in {"none", "blocked"}
        or not isinstance(native.get("paths"), list)
    ):
        raise ParserParityError("receipt_native_status_invalid")
    return {"status": "valid", "full_issue": "unverified"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).parents[1] / "fixtures" / "conformance" / "v1"
    parser.add_argument("--corpus", type=Path, default=default)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    receipt = build_receipt(args.corpus, source_root=args.source_root)
    rendered = json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.json_out:
        args.json_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    # A partial receipt is evidence of an incomplete contract, not a successful gate.
    return 0 if receipt["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
