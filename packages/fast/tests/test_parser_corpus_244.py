from __future__ import annotations

import hashlib
import json
from pathlib import Path

from simplicio_fast.parser_adapter import build_payload


ROOT = Path(__file__).parents[1] / "fixtures" / "conformance" / "v1"


def _facts_digest(payload: dict) -> str:
    facts = [
        {
            key: item["file"] if key == "path" else item[key]
            for key in ("path", "language", "name", "qualified_name", "kind", "line", "end_line")
        }
        for item in payload["symbols"]
    ]
    return hashlib.sha256(
        json.dumps(facts, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_frozen_conformance_corpus_is_deterministic_and_overload_safe() -> None:
    manifest = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
    first = build_payload(ROOT)
    second = build_payload(ROOT)
    assert first == second
    assert [item["path"] for item in first["files"]] == [
        item["path"] for item in manifest["files"]
    ]
    assert {item["language"] for item in first["files"]} == set(manifest["languages"])
    assert len(first["symbols"]) == 25
    assert len({item["id"] for item in first["symbols"]}) == len(first["symbols"])
    assert _facts_digest(first) == "d400b7f9cc0fffc51f7b979fabf579831a05884e82d053a397312f830fa15b2c"
    assert first["completeness"] == "partial"
    assert {
        item["path"] for item in first["diagnostics"] if item["code"] == "native_parser_unavailable"
    } == {"csharp/Service.cs", "rust/service.rs", "typescript/service.ts"}


def test_frozen_corpus_file_hashes_match_manifest() -> None:
    manifest = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
    for item in manifest["files"]:
        assert hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
