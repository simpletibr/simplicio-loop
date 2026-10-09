'''Contract test for the cost (USD) budget alert of the alerts panel (issue #1404, criterion: the budget alert fires when a
run's projected cost exceeds its budget, labelled with proof_kind).

The USD used comes from the token_usage events priced by budget.cost_estimate, the same price table the budget panel
reads, so the alert needs no cost_sample producer. A cost is always an estimate, so both the projection and the
exceeded alert carry proof_kind "estimado".
'''
from datetime import datetime, timezone

from simplicio_loop.dashboard import alerts

BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
PRICES = {'as_of': '2026-10-08', 'source_url': 'https://example.invalid/pricing',
          'models': {'claude-haiku-5-5': {'input_per_mtok': 1, 'output_per_mtok': 5}}}


def _at(offset_s):
    return datetime.fromtimestamp(BASE.timestamp() + offset_s, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _event(seq, offset_s, kind, phase=None, payload=None):
    event = {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': kind, 'ts': _at(offset_s), 'payload': payload or {}}
    if phase:
        event['phase'] = phase
    return event


def _run(budget, events, prices=PRICES):
    watch = alerts.AlertWatch(budget=budget, prices=prices)
    raised, _ = watch.update(events, int(BASE.timestamp() * 1000) + 2000)
    return [(a['id'], a['severity'], a['proof_kind']) for a in raised if a['id'].endswith(':usd')]


def test_projected_cost_over_the_budget_raises_an_estimado_alert():
    # 300 input tokens at $1/Mtok = $0.0003 used in 'executing' (fraction 3/7), projected $0.0007 > $0.0005 limit.
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    assert _run({'usd': 0.0005}, events) == [('budget-projected:usd', 'warning', 'estimado')]


def test_projected_cost_within_the_budget_raises_no_alert():
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    assert _run({'usd': 0.01}, events) == []


def test_measured_cost_over_the_budget_raises_an_exceeded_estimado_alert():
    # 1,000,000 output tokens at $5/Mtok = $5.00, far past the $1.00 limit: exceeded, still an estimate.
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 0, 'output_tokens': 1000000}),
    ]
    assert _run({'usd': 1.0}, events) == [('budget-exceeded:usd', 'critical', 'estimado')]


def test_a_model_without_a_price_leaves_usd_unverified_and_raises_nothing():
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'unknown-model', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    assert _run({'usd': 0.0005}, events) == []


def test_no_price_table_leaves_usd_unverified_and_raises_nothing():
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    assert _run({'usd': 0.0005}, events, prices=None) == []
