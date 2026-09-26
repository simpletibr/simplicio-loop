"""TDD unit tests for bench/llm_ab/cost.py (pure pricing/cost functions).

No network calls here: pricing/generation payloads are handed in as plain
dicts, exactly as ``llm_client.fetch_model_pricing``/``fetch_generation_stats``
would parse them from a real OpenRouter response.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "bench", "llm_ab"))

import cost  # noqa: E402

MODELS_RESPONSE = {
    "data": [
        {"id": "some/other-model", "pricing": {"prompt": "0.000001", "completion": "0.000002"}},
        {
            "id": "deepseek/deepseek-v4.1-flash",
            "pricing": {
                "prompt": "0.00000014",
                "completion": "0.00000042",
                "input_cache_read": "0.0000000042",
            },
        },
    ]
}


def test_parse_pricing_finds_model_and_converts_to_float():
    pricing = cost.parse_pricing(MODELS_RESPONSE, "deepseek/deepseek-v4.1-flash", fetched_at="2026-09-26T00:00:00Z")
    assert pricing["available"] is True
    assert pricing["model"] == "deepseek/deepseek-v4.1-flash"
    assert pricing["prompt"] == 0.00000014
    assert pricing["completion"] == 0.00000042
    assert pricing["input_cache_read"] == 0.0000000042
    assert pricing["fetched_at"] == "2026-09-26T00:00:00Z"


def test_parse_pricing_missing_optional_fields_are_none():
    pricing = cost.parse_pricing(MODELS_RESPONSE, "deepseek/deepseek-v4.1-flash", fetched_at="x")
    assert pricing["input_cache_write"] is None
    assert pricing["internal_reasoning"] is None


def test_parse_pricing_model_not_found():
    pricing = cost.parse_pricing(MODELS_RESPONSE, "nope/not-there", fetched_at="x")
    assert pricing["available"] is False
    assert pricing["error"] == "model_not_found"


def test_parse_pricing_defaults_fetched_at_when_omitted():
    pricing = cost.parse_pricing(MODELS_RESPONSE, "deepseek/deepseek-v4.1-flash")
    assert pricing["fetched_at"]  # non-empty ISO-ish string


def test_parse_pricing_handles_empty_or_malformed_response():
    assert cost.parse_pricing({}, "x", fetched_at="t")["available"] is False
    assert cost.parse_pricing(None, "x", fetched_at="t")["available"] is False


PRICING = {
    "model": "deepseek/deepseek-v4.1-flash",
    "available": True,
    "prompt": 0.00000014,
    "completion": 0.00000042,
    "input_cache_read": 0.0000000042,
    "input_cache_write": None,
    "internal_reasoning": None,
}


def test_cost_breakdown_uncached_only():
    b = cost.cost_breakdown(prompt_tokens=1000, cached_tokens=0, completion_tokens=500, pricing=PRICING)
    assert b["uncached_input_tokens"] == 1000
    assert b["cached_input_tokens"] == 0
    assert b["output_tokens"] == 500
    assert round(b["uncached_input_usd"], 10) == round(1000 * 0.00000014, 10)
    assert round(b["output_usd"], 10) == round(500 * 0.00000042, 10)
    assert b["cached_input_usd"] == 0
    assert b["cache_hit_pct"] == 0.0


def test_cost_breakdown_with_cache_hits_computes_savings():
    b = cost.cost_breakdown(prompt_tokens=1000, cached_tokens=400, completion_tokens=200, pricing=PRICING)
    assert b["uncached_input_tokens"] == 600
    assert b["cached_input_tokens"] == 400
    expected_savings = 400 * (0.00000014 - 0.0000000042)
    assert round(b["cache_savings_usd"], 10) == round(expected_savings, 10)
    assert b["cache_hit_pct"] == 40.0
    total = b["uncached_input_usd"] + b["cached_input_usd"] + b["output_usd"]
    assert round(b["computed_cost_usd"], 10) == round(total, 10)


def test_cost_breakdown_cached_tokens_clamped_to_prompt_tokens():
    # A malformed/over-reported cached count never goes negative on uncached.
    b = cost.cost_breakdown(prompt_tokens=100, cached_tokens=500, completion_tokens=0, pricing=PRICING)
    assert b["uncached_input_tokens"] == 0
    assert b["cached_input_tokens"] == 100


def test_cost_breakdown_missing_cache_read_price_falls_back_to_prompt_price():
    pricing_no_cache = dict(PRICING, input_cache_read=None)
    b = cost.cost_breakdown(prompt_tokens=100, cached_tokens=50, completion_tokens=0, pricing=pricing_no_cache)
    assert b["cache_savings_usd"] == 0.0
    assert round(b["cached_input_usd"], 10) == round(50 * pricing_no_cache["prompt"], 10)


def test_cost_breakdown_zero_prompt_tokens_no_division_error():
    b = cost.cost_breakdown(prompt_tokens=0, cached_tokens=0, completion_tokens=0, pricing=PRICING)
    assert b["cache_hit_pct"] == 0.0
    assert b["computed_cost_usd"] == 0.0


def test_compare_reported_vs_computed_with_reported_value():
    result = cost.compare_reported_vs_computed(0.001, 0.0009)
    assert result["reported_cost_usd"] == 0.001
    assert result["computed_cost_usd"] == 0.0009
    assert round(result["diff_usd"], 10) == round(0.0001, 10)


def test_compare_reported_vs_computed_missing_reported_is_none():
    result = cost.compare_reported_vs_computed(None, 0.0009)
    assert result["reported_cost_usd"] is None
    assert result["diff_usd"] is None


RESULTS = {
    "arms": {
        "normal": {
            "tasks": [
                {
                    "kind": "create",
                    "totals": {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200, "cost_usd": 0.0002},
                },
                {
                    "kind": "edit",
                    "totals": {"prompt_tokens": 1500, "cached_tokens": 800, "completion_tokens": 300, "cost_usd": 0.0003},
                },
            ]
        }
    }
}


def test_cost_table_groups_by_arm_and_kind():
    rows = cost.cost_table(RESULTS, PRICING)
    assert len(rows) == 2
    by_kind = {r["kind"]: r for r in rows}
    assert set(by_kind) == {"create", "edit"}
    assert by_kind["create"]["arm"] == "normal"
    assert by_kind["create"]["uncached_input_tokens"] == 1000
    assert by_kind["edit"]["cached_input_tokens"] == 800


def test_cost_table_empty_results_is_empty_list():
    assert cost.cost_table({}, PRICING) == []
    assert cost.cost_table({"arms": {}}, PRICING) == []


def test_pricing_table_returns_one_row_when_available():
    rows = cost.pricing_table(PRICING)
    assert len(rows) == 1
    assert rows[0]["model"] == "deepseek/deepseek-v4.1-flash"
    assert rows[0]["prompt"] == 0.00000014


def test_pricing_table_empty_when_unavailable():
    assert cost.pricing_table({"available": False}) == []
    assert cost.pricing_table(None) == []


GENERATION_FIELDS = {
    "id": "gen-abc",
    "total_cost": 0.00021,
    "cache_discount": -0.0000042,
    "native_tokens_prompt": 1000,
    "native_tokens_completion": 200,
    "native_tokens_reasoning": 50,
    "native_tokens_cached": 400,
    "unused_field": "ignored",
}


def test_parse_generation_response_ok_wraps_data_key():
    parsed = cost.parse_generation_response(200, {"data": GENERATION_FIELDS})
    assert parsed["available"] is True
    assert parsed["total_cost"] == 0.00021
    assert parsed["cache_discount"] == -0.0000042
    assert parsed["native_tokens_prompt"] == 1000
    assert parsed["native_tokens_completion"] == 200
    assert parsed["native_tokens_reasoning"] == 50
    assert parsed["native_tokens_cached"] == 400
    assert "unused_field" not in parsed


def test_parse_generation_response_ok_flat_body_without_data_key():
    parsed = cost.parse_generation_response(200, GENERATION_FIELDS)
    assert parsed["available"] is True
    assert parsed["total_cost"] == 0.00021


def test_parse_generation_response_missing_fields_are_omitted_not_fabricated():
    parsed = cost.parse_generation_response(200, {"data": {"total_cost": 0.001}})
    assert parsed["available"] is True
    assert parsed["total_cost"] == 0.001
    assert "cache_discount" not in parsed
    assert "native_tokens_cached" not in parsed


def test_parse_generation_response_404_marks_unavailable():
    parsed = cost.parse_generation_response(404, {"error": {"message": "not found", "code": 404}})
    assert parsed == {"available": False}


def test_parse_generation_response_non_dict_body_marks_unavailable():
    assert cost.parse_generation_response(200, None) == {"available": False}
    assert cost.parse_generation_response(200, "not a dict") == {"available": False}


# -- finalize_task_cost: settled-billed vs token-computed cross-check (#1335) -

def test_finalize_task_cost_computes_from_tokens_matching_cost_breakdown():
    totals = {"prompt_tokens": 1000, "cached_tokens": 400, "completion_tokens": 200}
    out = cost.finalize_task_cost(totals, PRICING)
    breakdown = cost.cost_breakdown(1000, 400, 200, PRICING)
    assert out["computed_cost_usd"] == breakdown["computed_cost_usd"]


def test_finalize_task_cost_no_billed_falls_back_to_computed_source():
    totals = {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200,
              "cost_usd": 0.0, "cost_source": "opencode-reported"}
    out = cost.finalize_task_cost(totals, PRICING)
    assert out["cost_source"] == "computed-from-tokens"
    assert out["cost_usd"] == out["computed_cost_usd"]
    assert out["cost_flag"] is False
    assert out["cost_divergence_pct"] is None


def test_finalize_task_cost_billed_close_to_computed_is_not_flagged():
    totals = {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200,
              "billed_cost_usd": 0.000224, "cost_source": "billed-settled"}
    out = cost.finalize_task_cost(totals, PRICING)
    assert out["cost_usd"] == 0.000224
    assert out["cost_flag"] is False
    assert out["cost_divergence_pct"] is not None
    assert abs(out["cost_divergence_pct"]) < 1.0


def test_finalize_task_cost_billed_far_from_computed_is_flagged():
    # billed ~4x under the token-computed price -- issue #1335's own example.
    totals = {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200,
              "billed_cost_usd": 0.00005, "cost_source": "billed-settled"}
    out = cost.finalize_task_cost(totals, PRICING)
    assert out["cost_usd"] == 0.00005
    assert out["cost_flag"] is True
    assert out["cost_divergence_pct"] > 10.0


def test_finalize_task_cost_backfills_billed_from_legacy_billed_delta_field():
    # Pre-#1335 results carry no `billed_cost_usd`; `cost_usd` under
    # `cost_source == "billed-delta"` WAS the billed figure -- backfill it
    # so a --reports-only render of old results still cross-checks.
    totals = {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200,
              "cost_usd": 0.00005, "cost_source": "billed-delta"}
    out = cost.finalize_task_cost(totals, PRICING)
    assert out["billed_cost_usd"] == 0.00005
    assert out["cost_flag"] is True


def test_finalize_task_cost_does_not_mutate_input():
    totals = {"prompt_tokens": 1000, "cached_tokens": 0, "completion_tokens": 200}
    cost.finalize_task_cost(totals, PRICING)
    assert "computed_cost_usd" not in totals
