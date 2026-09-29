from __future__ import annotations

import json

import pytest

from simplicio_loop.cli_impl import main
from simplicio_loop.source_contract import (
    CursorStore,
    DemandEnvelope,
    FixtureSourceAdapter,
    ItemIdentity,
    SourceContractError,
    SourceCursor,
    SourceIdentity,
    SourceRevision,
    SourceStatus,
    redact,
)


def _envelope(source: SourceIdentity, external_id: str, *, title: str = "Work", revision: str = "1"):
    return DemandEnvelope(
        ItemIdentity(source, external_id),
        SourceRevision("2026-01-01T00:00:00Z", revision),
        title,
        body="body",
    )


def test_revision_changes_preserve_envelope_identity_and_cursor_is_round_trip():
    source = SourceIdentity("local", "tenant-a", "project-a")
    first = _envelope(source, "item-1", revision="1")
    second = DemandEnvelope(first.identity, SourceRevision("2026-01-02T00:00:00Z", "2"), "Work v2")
    assert first.envelope_id == second.envelope_id
    assert first.revision_id != second.revision_id
    assert first.idempotency_key != second.idempotency_key

    cursor = SourceCursor("2026-01-02T00:00:00Z", "2", opaque="continuation")
    assert SourceCursor.from_token(cursor.token()) == cursor


def test_cursor_only_advances_with_durable_receipt_and_recovery_is_idempotent(tmp_path):
    source = SourceIdentity("local", "tenant-a", "project-a")
    adapter = FixtureSourceAdapter(source, [_envelope(source, "item-1")])
    store = CursorStore(tmp_path / "cursor.json")
    persisted = []

    def persist(item):
        persisted.append(item.envelope_id)

    receipt = adapter.ingest(store, persist, operation_id="op-1")
    assert receipt.durable is True
    assert store.get(source.source_key) is not None
    assert persisted == [persisted[0]]

    adapter.injected_status = SourceStatus.RATE_LIMITED
    failed = adapter.ingest(store, persist, operation_id="op-2")
    assert failed.status == SourceStatus.RATE_LIMITED
    assert failed.durable is False
    assert store.get(source.source_key).token() == receipt.cursor_after

    with pytest.raises(SourceContractError, match="durable receipt"):
        store.commit(source.source_key, store.get(source.source_key), failed)


def test_redaction_never_emits_credentials():
    value = redact({
        "authorization": "Bearer secret-token",
        "nested": {"api_key": "abc", "message": "https://example.test?a=1&token=secret"},
        "safe_id": "item-1",
    })
    encoded = json.dumps(value)
    assert "secret-token" not in encoded
    assert "abc" not in encoded
    assert "safe_id" in encoded


def test_source_and_resource_doctors_are_read_only(tmp_path, capsys):
    assert main(["doctor", "source", "--provider", "jira-cloud", "--json"]) == 0
    source = json.loads(capsys.readouterr().out)
    assert source["status"] == "READY"
    assert source["real_provider_auth"] == "UNVERIFIED"
    assert source["effects_attempted"] is False

    assert main(["doctor", "resource", "--root", str(tmp_path), "--json"]) == 2
    missing = json.loads(capsys.readouterr().out)
    assert missing["reason_code"] == "RESOURCE_FABRIC_NOT_STARTED"
    assert not (tmp_path / "resource-fabric.sqlite").exists()

    state = tmp_path / "resource-fabric.json"
    state.write_text(json.dumps({"schema": "simplicio.resource-fabric/v1", "draining": False}), encoding="utf-8")
    assert main(["doctor", "resource", "--root", str(tmp_path), "--json"]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["status"] == "OBSERVED"


