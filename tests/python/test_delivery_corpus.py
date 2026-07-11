from __future__ import annotations

from bench.run_delivery_corpus import run_corpus


def test_delivery_corpus_is_deterministic_and_fail_closed() -> None:
    result = run_corpus()

    assert result["schema"] == "simplicio.dev-cli.delivery-corpus/v1"
    assert result["proof_kind"] == "deterministic-provider-free"
    assert result["release_gates"]["deterministic_corpus_complete"] is True
    assert result["release_gates"]["runtime_identity_verified"] is False
    assert result["release_gates"]["release_ready"] is False
    assert result["metrics"]["cases_passed"] == result["metrics"]["cases_total"]
