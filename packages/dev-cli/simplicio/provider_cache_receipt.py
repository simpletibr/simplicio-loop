"""Provider cache-receipt bookkeeping (issue #149 / #152).

Extracted from ``simplicio/providers.py`` as part of issue #141's coordinator
refactor: the ``simplicio.providers.cache-receipt/v1`` structured-receipt
lifecycle (create → set steps → finalize → remember → persist) is a
self-contained feature that #149/#152 added *after* the token-budget baseline
was frozen at #147, which is exactly the kind of module bloat the gate exists
to catch.  Moving it into its own module keeps ``providers.py`` at a
sustainable size and makes the cache-receipt concern easier to reason about.

The live ``_LAST_CACHE_RECEIPT`` global stays in ``providers.py`` (it is read
by ``test_providers_cache_receipt.py`` via ``providers._LAST_CACHE_RECEIPT``),
so the functions here read/write it through the ``providers`` module object
rather than owning their own copy.
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from ._cache import cache


def _cache_bypass_reason() -> str | None:
    current_cache = cache()
    if not current_cache.enabled:
        return "cache_disabled"
    if current_cache.bust:
        return "cache_busted"
    return None


def _remember_cache_receipt(receipt: dict[str, Any] | None) -> None:
    from . import providers

    providers._LAST_CACHE_RECEIPT = None if receipt is None else deepcopy(receipt)


def last_cache_receipt() -> dict[str, Any] | None:
    from . import providers

    if providers._LAST_CACHE_RECEIPT is None:
        return None
    return deepcopy(providers._LAST_CACHE_RECEIPT)


def _new_cache_receipt(*, surface: str, requested_provider_id: str, requested_model: str) -> dict[str, Any]:
    receipt = {
        "schema": "simplicio.providers.cache-receipt/v1",
        "surface": surface,
        "requested_provider_id": requested_provider_id,
        "requested_model": requested_model,
        "outcome": "pending",
        "local_exact_lookup": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
        "provider_lookup": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
        "provider_write": {
            "status": "not_tried",
            "reason": None,
            "provider_id": None,
            "model": None,
            "key": None,
        },
    }
    _remember_cache_receipt(receipt)
    return receipt


def _set_cache_step(
    receipt: dict[str, Any],
    step: str,
    *,
    status: str,
    provider_id: str,
    model: str,
    key: str,
    reason: str | None = None,
) -> None:
    receipt[step] = {
        "status": status,
        "reason": reason,
        "provider_id": provider_id,
        "model": model,
        "key": key,
    }
    _remember_cache_receipt(receipt)


def _finalize_cache_receipt(receipt: dict[str, Any]) -> None:
    if receipt["local_exact_lookup"]["status"] == "hit":
        outcome = "local_exact_reuse"
    elif receipt["provider_lookup"]["status"] == "hit":
        outcome = "provider_cache_read"
    elif receipt["provider_write"]["status"] == "written":
        outcome = "provider_cache_write"
    elif any(
        receipt[name]["status"] == "bypass"
        for name in ("local_exact_lookup", "provider_lookup", "provider_write")
    ):
        outcome = "bypass"
    else:
        outcome = "cache_miss"
    receipt["outcome"] = outcome
    _remember_cache_receipt(receipt)
    _log_cache_receipt(receipt)


def _log_cache_receipt(receipt: dict[str, Any]) -> None:
    """Persist the structured cache decision without ever logging the prompt.

    Provider receipts contain cache keys and routing metadata, but not prompt or
    completion content.  Keep persistence opt-in and fail-open like usage
    logging so observability cannot break a provider call.
    """
    root = os.environ.get("SIMPLICIO_LOG_ROOT")
    if not root:
        return
    from .observability import log_run

    try:
        log_run(root, {"mode": "provider_cache_receipt", "receipt": deepcopy(receipt)})
    except OSError:
        pass
