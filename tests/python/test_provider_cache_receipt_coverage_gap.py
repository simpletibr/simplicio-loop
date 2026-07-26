"""Direct unit coverage for simplicio/provider_cache_receipt.py."""

from __future__ import annotations

from simplicio import provider_cache_receipt as pcr
from simplicio import providers


def _blank_receipt():
    return pcr._new_cache_receipt(surface="test", requested_provider_id="openrouter", requested_model="gpt-x")


def test_cache_bypass_reason_disabled(monkeypatch):
    class _Cache:
        enabled = False
        bust = False

    monkeypatch.setattr(pcr, "cache", lambda: _Cache())
    assert pcr._cache_bypass_reason() == "cache_disabled"


def test_cache_bypass_reason_busted(monkeypatch):
    class _Cache:
        enabled = True
        bust = True

    monkeypatch.setattr(pcr, "cache", lambda: _Cache())
    assert pcr._cache_bypass_reason() == "cache_busted"


def test_cache_bypass_reason_none(monkeypatch):
    class _Cache:
        enabled = True
        bust = False

    monkeypatch.setattr(pcr, "cache", lambda: _Cache())
    assert pcr._cache_bypass_reason() is None


def test_new_cache_receipt_shape_and_remembered():
    receipt = _blank_receipt()
    assert receipt["schema"] == "simplicio.providers.cache-receipt/v1"
    assert receipt["outcome"] == "pending"
    assert receipt["local_exact_lookup"]["status"] == "not_tried"
    assert providers._LAST_CACHE_RECEIPT == receipt


def test_last_cache_receipt_returns_deep_copy():
    receipt = _blank_receipt()
    fetched = pcr.last_cache_receipt()
    assert fetched == receipt
    fetched["outcome"] = "mutated"
    assert providers._LAST_CACHE_RECEIPT["outcome"] == "pending"


def test_last_cache_receipt_none_when_no_receipt():
    pcr._remember_cache_receipt(None)
    assert pcr.last_cache_receipt() is None


def test_set_cache_step_updates_and_remembers():
    receipt = _blank_receipt()
    pcr._set_cache_step(
        receipt,
        "local_exact_lookup",
        status="hit",
        provider_id="openrouter",
        model="gpt-x",
        key="abc123",
        reason="matched",
    )
    assert receipt["local_exact_lookup"]["status"] == "hit"
    assert receipt["local_exact_lookup"]["key"] == "abc123"
    assert providers._LAST_CACHE_RECEIPT["local_exact_lookup"]["status"] == "hit"


def test_finalize_cache_receipt_local_exact_reuse():
    receipt = _blank_receipt()
    receipt["local_exact_lookup"]["status"] = "hit"
    pcr._finalize_cache_receipt(receipt)
    assert receipt["outcome"] == "local_exact_reuse"


def test_finalize_cache_receipt_provider_cache_read():
    receipt = _blank_receipt()
    receipt["provider_lookup"]["status"] = "hit"
    pcr._finalize_cache_receipt(receipt)
    assert receipt["outcome"] == "provider_cache_read"


def test_finalize_cache_receipt_provider_cache_write():
    receipt = _blank_receipt()
    receipt["provider_write"]["status"] = "written"
    pcr._finalize_cache_receipt(receipt)
    assert receipt["outcome"] == "provider_cache_write"


def test_finalize_cache_receipt_bypass():
    receipt = _blank_receipt()
    receipt["provider_lookup"]["status"] = "bypass"
    pcr._finalize_cache_receipt(receipt)
    assert receipt["outcome"] == "bypass"


def test_finalize_cache_receipt_cache_miss():
    receipt = _blank_receipt()
    pcr._finalize_cache_receipt(receipt)
    assert receipt["outcome"] == "cache_miss"


def test_log_cache_receipt_noop_without_log_root(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_LOG_ROOT", raising=False)
    # Must not raise even though no log root is configured.
    pcr._log_cache_receipt(_blank_receipt())


def test_log_cache_receipt_persists_when_log_root_set(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))
    receipt = _blank_receipt()
    pcr._log_cache_receipt(receipt)
    events_file = tmp_path / ".simplicio" / "events.jsonl"
    assert events_file.is_file() or any(tmp_path.rglob("*.jsonl"))


def test_log_cache_receipt_swallows_oserror(monkeypatch, tmp_path):
    monkeypatch.setenv("SIMPLICIO_LOG_ROOT", str(tmp_path))

    def _boom(root, payload):
        raise OSError("disk full")

    from simplicio import observability

    monkeypatch.setattr(observability, "log_run", _boom)
    # Must not raise.
    pcr._log_cache_receipt(_blank_receipt())
