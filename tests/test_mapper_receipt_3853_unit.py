"""Unit tests for mapper receipt normalization (#3853)."""
from __future__ import annotations

import hashlib
import json

from simplicio_loop.mapper_receipt import normalize_mapper_index_receipt


def content_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def valid_receipt(receipt, schema: str) -> bool:
    return isinstance(receipt, dict) and receipt.get("schema") == schema


def test_flat_mapper_index_from_real_cli_shape():
    # Measured shape of simplicio-mapper index . --json (paths at top level).
    receipt = {
        "schema": "simplicio.mapper-index/v1",
        "status": "updated",
        "paths": {"project_map": "C:/repo/.simplicio-loop/project-map.json"},
        "counts": {"files": 10},
        "changed_files": ["a.rs"],
    }
    out = normalize_mapper_index_receipt(
        receipt, repo="C:/repo", content_hash=content_hash, valid_receipt=valid_receipt
    )
    assert out["verified"] is True
    assert out["receipt"]["schema"] == "simplicio.mapper-receipt/v1"
    assert out["receipt"]["verified"] is True
    assert out["receipt"]["repo"] == "C:/repo"
    assert out["generation"]


def test_nested_result_paths_still_work():
    receipt = {
        "schema": "simplicio.mapper-index/v1",
        "status": "unchanged",
        "result": {"paths": {"project_map": "/tmp/map.json"}},
    }
    out = normalize_mapper_index_receipt(
        receipt, repo="/repo", content_hash=content_hash, valid_receipt=valid_receipt
    )
    assert out["verified"] is True


def test_preverified_mapper_receipt_passthrough():
    receipt = {
        "schema": "simplicio.mapper-receipt/v1",
        "verified": True,
        "repo": "/repo",
        "generation": "gen-1",
    }
    out = normalize_mapper_index_receipt(
        receipt, repo="/repo", content_hash=content_hash, valid_receipt=valid_receipt
    )
    assert out["generation"] == "gen-1"


def test_unsupported_receipt_fails_closed():
    try:
        normalize_mapper_index_receipt(
            {"schema": "nope", "status": "updated"},
            repo="/repo",
            content_hash=content_hash,
            valid_receipt=valid_receipt,
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "verifiable standalone receipt" in str(exc)
