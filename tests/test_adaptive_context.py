from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from simplicio_loop.adaptive_context import (
    AdaptiveContextController, BudgetLimits, BudgetScope, ContextSpan,
    ExpansionReason, HardBudgetExceeded, InvalidExpansion, RegexTokenCounter,
    StaleSpan, TokenCountUnavailable,
)


def controller(*, soft=8, hard=16, counter=None):
    return AdaptiveContextController(
        BudgetScope(
            run=BudgetLimits(soft, hard),
            stages={"plan": BudgetLimits(soft, hard)},
            tasks={"issue-810": BudgetLimits(soft, hard)},
            providers={"test": BudgetLimits(soft, hard)},
        ),
        stage="plan", task="issue-810", provider="test",
        expected_revision="abc123", counter=counter or RegexTokenCounter(),
    )


def span(content, *, provenance="mapper:signature", revision="abc123",
         priority=10, handle=""):
    return ContextSpan(content, provenance, revision, priority=priority, handle=handle)


def test_hierarchical_boundary_never_silently_exceeds_hard_budget():
    scoped = AdaptiveContextController(
        BudgetScope(
            run=BudgetLimits(20, 30),
            stages={"plan": BudgetLimits(10, 12)},
            providers={"test": BudgetLimits(8, 10)},
        ),
        stage="plan", task="x", provider="test",
        expected_revision="abc123", counter=RegexTokenCounter(),
    )
    scoped.seed([span("one two three four five six seven eight")])
    assert scoped.prompt()["token_count"] == 8
    with pytest.raises(HardBudgetExceeded) as error:
        scoped.expand([span("nine"), span("ten eleven")],
                      reason=ExpansionReason.MISSING_SYMBOL,
                      evidence="NameError: symbol")
    assert error.value.reason_code == "HARD_BUDGET_EXCEEDED"
    assert scoped.prompt()["token_count"] == 8


def test_dedup_provenance_hash_and_receipt_outside_prompt():
    item = span("def execute(): pass", handle="mapper://page/1")
    subject = controller()
    subject.seed([item, item])
    receipt = subject.receipt("READY")
    prompt = subject.prompt()
    assert receipt["deduplicated_spans"] == 1
    assert receipt["spans"][0]["hash"].startswith("sha256:")
    assert receipt["spans"][0]["provenance"] == "mapper:signature"
    assert "expansions" not in prompt
    assert prompt["context"][0]["handle"] == "mapper://page/1"


def test_expansion_requires_observable_gap_and_records_reason():
    subject = controller(soft=3, hard=12)
    subject.seed([span("one two three")])
    with pytest.raises(InvalidExpansion):
        subject.expand([span("four")],
                       reason=ExpansionReason.MISSING_SYMBOL, evidence="")
    expanded = subject.expand(
        [span("four five")], reason=ExpansionReason.FAILING_TEST,
        evidence="tests/test_app.py::test_user failed",
    )
    assert expanded["expansion"]["reason_code"] == "FAILING_TEST"
    assert expanded["observed"]["context_tokens"] == 5


def test_expansion_is_hash_bound_and_cache_is_reused():
    subject = controller(soft=1, hard=10)
    receipt = subject.expand(
        [span("alpha beta", provenance="mapper:g1", handle="mapper://g1/a"),
         span("gamma", provenance="mapper:g1", handle="mapper://g1/b")],
        reason=ExpansionReason.INSUFFICIENT_EVIDENCE,
        evidence="only signature available",
    )
    assert "fast_pages" not in receipt
    assert receipt["observed"]["context_tokens"] == 3
    subject.receipt("AGAIN")
    assert subject.receipt("AGAIN")["cache_hits"] > 0


def test_fast_paging_api_is_gone():
    assert not hasattr(AdaptiveContextController, "expand_from_fast")


def test_stale_span_and_unknown_counter_fail_closed():
    subject = controller()
    with pytest.raises(StaleSpan) as stale:
        subject.seed([span("old", revision="old")])
    assert stale.value.reason_code == "STALE_SPAN"
    unknown = AdaptiveContextController(
        BudgetScope(BudgetLimits(5, 10)), stage="plan", task="x",
        provider="unknown", expected_revision="abc123", counter=None,
    )
    with pytest.raises(TokenCountUnavailable) as unavailable:
        unknown.seed([span("cannot count")])
    assert unavailable.value.reason_code == "TOKEN_COUNT_UNAVAILABLE"


def test_provider_usage_preserves_null_reasons():
    subject = controller()
    subject.seed([span("one")])
    subject.record_provider_usage({"input_tokens": 10, "cached_tokens": 4})
    observed = subject.receipt("READY")["observed"]
    assert observed["input_tokens"] == 10
    assert observed["cached_tokens"] == 4
    assert observed["reasoning_tokens"] is None
    assert "provider omitted" in observed["reason"]


def test_checked_in_benchmark_receipt_is_measured_and_hash_valid():
    path = Path(__file__).parent / "fixtures" / "adaptive_context_benchmark_810.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["classification"] == "MEASURED_LOCAL"
    assert payload["local_llm"] is False
    assert payload["quality"]["adaptive_fact_recall"] == 1.0
    assert payload["runs"] >= 100
    expected = payload.pop("receipt_hash")
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert expected == "sha256:" + hashlib.sha256(raw).hexdigest()
