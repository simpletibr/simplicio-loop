"""Pure real-cost computation for the LLM A/B benchmark: OpenRouter pricing
parsing, per-generation stats parsing, and cache-aware cost breakdowns.

No network I/O here (that lives in ``llm_client.py``: ``fetch_model_pricing``
and ``fetch_generation_stats``) -- every function below takes plain
dicts/numbers already parsed from an OpenRouter response, or from
``agent.summarize``'s per-task ``totals``, and returns plain data. This
keeps the cost math itself fully unit-testable with no live API calls.
"""
from __future__ import annotations

import datetime

# Optional pricing fields on an OpenRouter /models entry. ``prompt`` and
# ``completion`` are always present for a chat model; the cache fields are
# absent for models that don't support prompt caching (e.g. no
# ``input_cache_read``) -- those come back as ``None``, never fabricated.
PRICING_FIELDS = (
    "prompt",
    "completion",
    "input_cache_read",
    "input_cache_write",
    "internal_reasoning",
)

# Raw subset of an OpenRouter GET /generation?id=... response worth keeping
# per README's "keep raw subset" instruction -- anything else on that
# response is dropped rather than stored.
GENERATION_FIELDS = (
    "native_tokens_prompt",
    "native_tokens_completion",
    "native_tokens_reasoning",
    "native_tokens_cached",
    "total_cost",
    "cache_discount",
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_pricing(models_response: dict | None, model: str, fetched_at: str | None = None) -> dict:
    """Extract normalized float pricing for ``model`` from a GET
    ``/api/v1/models`` response body (already JSON-decoded).

    Returns ``{"available": False, "error": "model_not_found"}`` (plus
    ``model``/``fetched_at``) when the model isn't in the response, and
    ``None`` for any pricing field the model's entry doesn't carry --
    never a fabricated number.
    """
    fetched_at = fetched_at or _now_iso()
    entries = (models_response or {}).get("data") or []
    for entry in entries:
        if entry.get("id") == model:
            raw = entry.get("pricing") or {}
            out: dict = {"model": model, "fetched_at": fetched_at, "available": True}
            for field in PRICING_FIELDS:
                val = raw.get(field)
                out[field] = float(val) if val is not None else None
            return out
    return {"model": model, "fetched_at": fetched_at, "available": False, "error": "model_not_found"}


def parse_generation_response(status: int | None, parsed: object) -> dict:
    """Normalize a GET ``/api/v1/generation?id=...`` response.

    ``status`` is the HTTP status already observed by the caller (after any
    retry); a non-200 status or a body that isn't a dict marks the stats as
    unavailable rather than guessing. A 200 body may wrap the real fields
    under ``data`` (the documented OpenRouter shape) or return them flat;
    both are accepted. Only ``GENERATION_FIELDS`` present on the body are
    kept -- an absent field is simply omitted, never defaulted to 0.
    """
    if status != 200 or not isinstance(parsed, dict):
        return {"available": False}
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else parsed
    out: dict = {"available": True}
    for field in GENERATION_FIELDS:
        if field in data:
            out[field] = data[field]
    return out


def cost_breakdown(prompt_tokens: int, cached_tokens: int, completion_tokens: int, pricing: dict) -> dict:
    """Cache-aware cost breakdown for one arm/task/call's token totals.

    ``completion_tokens`` is the TOTAL completion tokens (already includes
    any reasoning tokens, matching OpenRouter's ``usage.completion_tokens``
    semantics) -- callers must not add reasoning tokens on top of it.

    ``cached_tokens`` is clamped to ``prompt_tokens`` so a malformed/over
    reported cache count can never push the uncached count negative. When
    the pricing has no ``input_cache_read`` price (model doesn't support
    caching, or pricing fetch failed to carry it), cached tokens are priced
    at the plain prompt rate and ``cache_savings_usd`` is 0 -- never a
    fabricated discount.
    """
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    cached_tokens = min(max(cached_tokens or 0, 0), prompt_tokens)
    uncached_input = prompt_tokens - cached_tokens

    prompt_price = pricing.get("prompt") or 0.0
    completion_price = pricing.get("completion") or 0.0
    cache_read_price = pricing.get("input_cache_read")
    cache_read_price_eff = cache_read_price if cache_read_price is not None else prompt_price

    uncached_input_usd = uncached_input * prompt_price
    cached_input_usd = cached_tokens * cache_read_price_eff
    output_usd = completion_tokens * completion_price
    computed_cost_usd = uncached_input_usd + cached_input_usd + output_usd
    cache_savings_usd = cached_tokens * (prompt_price - cache_read_price_eff)
    cache_hit_pct = (cached_tokens / prompt_tokens * 100.0) if prompt_tokens else 0.0

    return {
        "uncached_input_tokens": uncached_input,
        "cached_input_tokens": cached_tokens,
        "output_tokens": completion_tokens,
        "uncached_input_usd": round(uncached_input_usd, 8),
        "cached_input_usd": round(cached_input_usd, 8),
        "output_usd": round(output_usd, 8),
        "computed_cost_usd": round(computed_cost_usd, 8),
        "cache_savings_usd": round(cache_savings_usd, 8),
        "cache_hit_pct": round(cache_hit_pct, 4),
    }


def compare_reported_vs_computed(reported_cost: float | None, computed_cost: float) -> dict:
    """``{"reported_cost_usd", "computed_cost_usd", "diff_usd"}``.

    ``diff_usd`` is ``None`` when there's no reported figure to compare
    against (rather than treating a missing report as a $0 report).
    """
    reported = reported_cost if isinstance(reported_cost, (int, float)) else None
    diff = round(reported - computed_cost, 8) if reported is not None else None
    return {
        "reported_cost_usd": reported,
        "computed_cost_usd": round(computed_cost, 8),
        "diff_usd": diff,
    }


def cost_table(results: dict, pricing: dict) -> list[dict]:
    """One row per (arm, task kind): reported vs computed cost breakdown,
    aggregated over every task of that kind in that arm.

    Reads straight from the same ``totals`` each task already carries
    (``agent.summarize``'s output) -- no re-derivation from raw llm_calls
    needed since totals are already the per-task token sums.
    """
    rows: list[dict] = []
    arms = (results or {}).get("arms") or {}
    for arm_name, arm_data in arms.items():
        by_kind: dict[str, dict] = {}
        for task in arm_data.get("tasks") or []:
            kind = task.get("kind", "unknown")
            totals = task.get("totals") or {}
            bucket = by_kind.setdefault(
                kind, {"prompt_tokens": 0, "cached_tokens": 0, "completion_tokens": 0, "reported_cost": 0.0}
            )
            bucket["prompt_tokens"] += totals.get("prompt_tokens") or 0
            bucket["cached_tokens"] += totals.get("cached_tokens") or 0
            bucket["completion_tokens"] += totals.get("completion_tokens") or 0
            bucket["reported_cost"] += totals.get("cost_usd") or 0
        for kind, bucket in by_kind.items():
            breakdown = cost_breakdown(
                bucket["prompt_tokens"], bucket["cached_tokens"], bucket["completion_tokens"], pricing
            )
            comparison = compare_reported_vs_computed(bucket["reported_cost"], breakdown["computed_cost_usd"])
            rows.append({"arm": arm_name, "kind": kind, **breakdown, **comparison})
    return rows


def pricing_table(pricing: dict | None) -> list[dict]:
    """One-row table of the fetched pricing, for the report -- empty when
    the pricing fetch failed rather than showing a row of zeros."""
    if not pricing or not pricing.get("available"):
        return []
    return [
        {
            "model": pricing.get("model"),
            "prompt": pricing.get("prompt"),
            "completion": pricing.get("completion"),
            "input_cache_read": pricing.get("input_cache_read"),
            "input_cache_write": pricing.get("input_cache_write"),
            "internal_reasoning": pricing.get("internal_reasoning"),
            "fetched_at": pricing.get("fetched_at"),
        }
    ]
