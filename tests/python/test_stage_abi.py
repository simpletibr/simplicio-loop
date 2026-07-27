from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from simplicio.stage_abi import (
    MUTATION_RECEIPT_SCHEMA,
    StageAbiError,
    StageMutationEnvelopeV1,
    execute_stage_envelope,
    verify_mutation_receipt,
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _envelope(root: Path, *, operations: list[dict], source_hashes: dict[str, str], **extra):
    payload = {
        "schema": "simplicio.stage-mutation/v1",
        "effect_id": "effect-stage-test",
        "plan_node_id": "node-stage-test",
        "idempotency_key": "stage-test-key-001",
        "workspace_root": str(root.resolve()),
        "allowlist": sorted(source_hashes),
        "source_hashes": source_hashes,
        "operations": operations,
        "hookwall": {
            "decision": "allow",
            "issuer": "loop-coordinator",
            "receipt": "hookwall-receipt-001",
        },
        "policy_revision": "policy-v1",
        "context_handle": "fast:stage-test",
        "validation": [],
    }
    payload.update(extra)
    return payload


def test_dry_run_is_non_mutating_and_has_hash_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    target = tmp_path / "new.txt"
    payload = _envelope(
        tmp_path,
        operations=[{"op": "create_file", "path": "new.txt", "text": "hello\n"}],
        source_hashes={"new.txt": ""},
    )
    result = execute_stage_envelope(payload, root=tmp_path, apply=False)
    assert result["status"] == "completed"
    assert not result["applied"]
    assert result["mutation_receipt"]["before_hashes"] == {"new.txt": ""}
    assert result["mutation_receipt"]["after_hashes"] == {"new.txt": ""}
    assert not target.exists()
    assert not (tmp_path / ".simplicio" / "stage-abi").exists()


def test_source_drift_and_hookwall_are_fail_closed(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    payload = _envelope(
        tmp_path,
        operations=[{"op": "replace_range", "path": "target.txt", "start_line": 1, "end_line": 1, "text": "new\n"}],
        source_hashes={"target.txt": _digest(b"different\n")},
    )
    with pytest.raises(StageAbiError, match="source hash"):
        execute_stage_envelope(payload, root=tmp_path, apply=True)
    payload["hookwall"] = {"decision": "deny", "issuer": "loop-coordinator", "receipt": "r"}
    with pytest.raises(StageAbiError, match="Hookwall"):
        execute_stage_envelope(payload, root=tmp_path, apply=False)


def test_allowlist_and_path_escape_are_rejected(tmp_path):
    payload = _envelope(
        tmp_path,
        operations=[{"op": "create_file", "path": "outside.txt", "text": "x"}],
        source_hashes={"outside.txt": ""},
    )
    payload["allowlist"] = ["inside.txt"]
    with pytest.raises(StageAbiError, match="allowlist"):
        execute_stage_envelope(payload, root=tmp_path, apply=False)
    payload = _envelope(
        tmp_path,
        operations=[{"op": "create_file", "path": "../outside.txt", "text": "x"}],
        source_hashes={"../outside.txt": ""},
    )
    with pytest.raises(StageAbiError, match="stay inside"):
        execute_stage_envelope(payload, root=tmp_path, apply=False)


def test_apply_receipt_is_verifiable_and_retry_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DEV_CLI_NO_RUNTIME_EDIT", "1")
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    before_bytes = target.read_bytes()
    payload = _envelope(
        tmp_path,
        operations=[{"op": "replace_range", "path": "target.txt", "start_line": 1, "end_line": 1, "text": "new\n"}],
        source_hashes={"target.txt": _digest(before_bytes)},
    )
    first = execute_stage_envelope(payload, root=tmp_path, apply=True)
    receipt = first["mutation_receipt"]
    assert first["status"] == "completed"
    assert receipt["schema"] == MUTATION_RECEIPT_SCHEMA
    assert receipt["before_hashes"] == {"target.txt": _digest(before_bytes)}
    assert receipt["after_hashes"] == {"target.txt": _digest(target.read_bytes())}
    assert verify_mutation_receipt(receipt, root=tmp_path)
    second = execute_stage_envelope(payload, root=tmp_path, apply=True)
    assert second["status"] == "idempotent"
    assert second["mutation_receipt"] == receipt
    assert json.loads(next((tmp_path / ".simplicio" / "stage-abi").glob("*.receipt.json")).read_text()) == receipt


def test_llm_cannot_be_hookwall_issuer(tmp_path):
    payload = _envelope(
        tmp_path,
        operations=[{"op": "create_file", "path": "new.txt", "text": "x"}],
        source_hashes={"new.txt": ""},
        hookwall={"decision": "allow", "issuer": "llm", "receipt": "r"},
    )
    with pytest.raises(StageAbiError, match="coordinator"):
        StageMutationEnvelopeV1.from_dict(payload)
