from __future__ import annotations

import pytest

from benchmarks.bench_tokenizer_matrix_240 import PROVIDERS, TASKS, run


@pytest.fixture(autouse=True)
def _hermetic_tiktoken_cache(tmp_path, monkeypatch) -> None:
    """Force a guaranteed local-cache miss for every tiktoken encoding.

    ``resolve_tokenizer`` (see ``simplicio_fast.tokenizers``) never reaches
    the network: it blocks tiktoken's fetch primitive for the duration of a
    resolve call, so an encoding that is not already cached resolves to an
    explicit "unavailable" instead of attempting a download. Pointing
    ``TIKTOKEN_CACHE_DIR`` at a fresh, empty directory makes that outcome
    deterministic regardless of what happens to be cached on the machine
    running the test, so this test never depends on network access or on
    ambient cache state.
    """
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path / "empty-tiktoken-cache"))


def test_tokenizer_matrix_is_bounded_and_explicit() -> None:
    receipt = run()
    assert receipt["schema"] == "simplicio.fast.tokenizer-matrix/v1"
    assert len(receipt["providers"]) == len(PROVIDERS)
    for provider in receipt["providers"]:
        assert provider["provider"] in PROVIDERS
        if provider["status"] == "exact":
            assert len(provider["tasks"]) == len(TASKS)
            assert all(item["tokens"] >= 0 for item in provider["tasks"])
        else:
            assert provider["status"] == "unavailable"
            assert provider["reason_code"] == "provider_tokenizer_unavailable"
            assert provider["tasks"] == []


def test_tokenizer_matrix_reports_unavailable_without_a_local_cache() -> None:
    """Without a populated tiktoken cache, every provider fails closed and explicit.

    This is the hermetic case that used to require a network fetch: it now
    proves the bounded, explicit "unavailable" shape end-to-end with no
    network dependency at all.
    """
    receipt = run()
    assert receipt["status"] == "partial"
    assert receipt["environment"]["exact_provider_count"] == 0
    for provider in receipt["providers"]:
        assert provider["status"] == "unavailable"
        assert provider["reason_code"] == "provider_tokenizer_unavailable"
        assert provider["tasks"] == []
