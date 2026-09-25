from concurrent.futures import ThreadPoolExecutor
import pytest
from simplicio_fast.generation_receipts import (
    GenerationReceiptError,
    ReceiptJournal,
    seal_receipt,
    verify_chain,
    verify_receipt,
)


def receipt(**overrides):
    args = dict(
        kind="context",
        repo="org/repo",
        commit="a" * 40,
        snapshot_digest="b" * 64,
        generation="g1",
        source_hashes={"src/a.py": "c" * 64},
        backend="python",
        fallback_reason="RUST_UNAVAILABLE",
        ancestor_context_packet_hash="d" * 64,
        downstream_changeset_hash="e" * 64,
    )
    args.update(overrides)
    return seal_receipt(**args)


def test_offline_verifier_detects_tamper_stale_and_cross_generation():
    value = receipt()
    assert verify_receipt(value, expected_repo="org/repo", expected_generation="g1")
    with pytest.raises(GenerationReceiptError) as stale:
        verify_receipt(value, expected_source_hashes={"src/a.py": "0" * 64})
    assert stale.value.reason_code == "receipt_source_stale"
    value["commit"] = "f" * 40
    with pytest.raises(GenerationReceiptError) as corrupt:
        verify_receipt(value)
    assert corrupt.value.reason_code == "receipt_corrupt"


def test_chain_binds_ancestor_packet_and_downstream_changeset():
    first = receipt(
        kind="build", ancestor_context_packet_hash=None, downstream_changeset_hash=None
    )
    second = receipt(kind="rollout", ancestor_receipt_hash=first["receipt_hash"])
    assert verify_chain([first, second])[-1]["downstream_changeset_hash"] == "e" * 64


@pytest.mark.parametrize("workers", [1, 5, 20])
def test_identical_retry_is_idempotent_under_slot_concurrency(workers):
    journal = ReceiptJournal()
    value = receipt()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: journal.append(value), range(workers)))
    assert all(item[0] == value for item in results)
    assert sum(item[1] for item in results) == max(0, workers - 1)


def test_backend_and_fallback_are_explicit_and_offsets_private():
    python = receipt()
    rust = receipt(backend="rust", backend_artifact_hash="f" * 64, fallback_reason=None)
    assert python["fallback_reason"] == "RUST_UNAVAILABLE"
    assert rust["backend_artifact_hash"] == "f" * 64
    assert rust["public_offsets"] is None
