'''Contract test for the two price-tier alerts of the alerts panel (issue #1608).

requests-over-tier (warning, medido) fires when a measured provider request (requests == 1) had a prompt above its model's
tier limit; the goal is zero, so a zero or unknown count raises nothing. tier-crossable:<model> (warning, estimado) fires when
the effective input ceiling reaches the tier limit of a model the run used. A model with no tier or no price entry raises
nothing. The tests use the real prices.json.
'''
import json
from datetime import datetime, timezone
from pathlib import Path

from simplicio_loop.dashboard import alerts

PRICES = json.loads((Path(alerts.__file__).with_name('prices.json')).read_text(encoding='utf-8'))
BASE = datetime(2026, 10, 10, 10, 0, 0, tzinfo=timezone.utc)


def _at(offset_s):
    return datetime.fromtimestamp(BASE.timestamp() + offset_s, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _usage(seq, tokens_in, tokens_out, model='claude-haiku-5-5', **extra):
    payload = {'model': model, 'input_tokens': tokens_in, 'output_tokens': tokens_out, **extra}
    return {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': 'token_usage', 'ts': _at(seq), 'payload': payload}


def _run(events, ceiling=None, prices=PRICES):
    watch = alerts.AlertWatch(prices=prices, ceiling=ceiling)
    raised, _ = watch.update(events, int(BASE.timestamp() * 1000) + 2000)
    return [(a['id'], a['severity'], a['proof_kind']) for a in raised]


def test_a_measured_request_over_the_tier_raises_a_medido_warning():
    assert _run([_usage(1, 150000, 2000, requests=1)]) == [('requests-over-tier', 'warning', 'medido')]


def test_an_aggregate_event_over_the_tier_is_not_counted_and_raises_nothing():
    assert _run([_usage(1, 150000, 0)]) == []


def test_a_request_exactly_at_the_tier_limit_raises_nothing():
    assert _run([_usage(1, 100000, 0, requests=1)]) == []


def test_without_a_price_table_the_request_count_is_unknown_and_raises_nothing():
    assert _run([_usage(1, 150000, 0, requests=1)], prices=None) == []


def test_a_ceiling_above_the_tier_limit_raises_a_tier_alert_for_the_model_used():
    assert _run([_usage(1, 1000, 0)], ceiling=100001) == [('tier-crossable:claude-haiku-5-5', 'warning', 'estimado')]


def test_a_ceiling_at_the_tier_limit_cannot_cross_it_and_raises_nothing():
    assert _run([_usage(1, 1000, 0)], ceiling=100000) == []


def test_a_ceiling_below_the_tier_limit_raises_no_tier_alert():
    assert _run([_usage(1, 1000, 0)], ceiling=98000) == []


def test_a_model_without_a_tier_or_a_price_entry_raises_no_tier_alert():
    events = [_usage(1, 1000, 0, model='claude-haiku-4-5'), _usage(2, 1000, 0, model='unknown-model')]
    assert _run(events, ceiling=500000) == []


def test_no_ceiling_means_no_tier_alert():
    assert _run([_usage(1, 1000, 0)], ceiling=None) == []


def test_requests_over_the_tier_add_up_across_events_and_updates_and_a_resend_adds_nothing():
    watch = alerts.AlertWatch(prices=PRICES)
    now = int(BASE.timestamp() * 1000) + 2000
    first = _usage(1, 150000, 0, requests=1)
    second = _usage(2, 160000, 0, requests=1)
    watch.update([first], now)
    assert watch._tier_alerts()[0]['why'].startswith('1 ')
    watch.update([first, second], now)
    assert watch._tier_alerts()[0]['why'].startswith('2 ')
    watch.update([first, second], now)
    assert watch._tier_alerts()[0]['why'].startswith('2 ')


def test_the_tier_alert_reason_names_the_ceiling_and_the_threshold():
    watch = alerts.AlertWatch(prices=PRICES, ceiling=120000)
    raised, _ = watch.update([_usage(1, 1000, 0)], int(BASE.timestamp() * 1000) + 2000)
    reason = next(a['why'] for a in raised if a['id'] == 'tier-crossable:claude-haiku-5-5')
    assert '120000' in reason and '100000' in reason


def test_an_unreadable_ceiling_raises_a_named_alert_not_silence():
    watch = alerts.AlertWatch(prices=PRICES, ceiling=None, ceiling_error='agent_input_token_ceiling: 0 is not an integer')
    raised, _ = watch.update([_usage(1, 1000, 0)], int(BASE.timestamp() * 1000) + 2000)
    assert [(a['id'], a['severity']) for a in raised] == [('ceiling-unreadable', 'warning')]
    assert 'agent_input_token_ceiling' in raised[0]['why']


def test_the_server_turns_a_bad_ceiling_into_a_reason_and_a_good_one_into_a_value(tmp_path, monkeypatch):
    from simplicio_loop.dashboard import server
    monkeypatch.setenv('SIMPLICIO_AGENT_INPUT_TOKEN_CEILING', '90000')
    assert server.input_ceiling_or_error(str(tmp_path)) == (90000, None)
    monkeypatch.setenv('SIMPLICIO_AGENT_INPUT_TOKEN_CEILING', '0')
    value, error = server.input_ceiling_or_error(str(tmp_path))
    assert value is None and 'SIMPLICIO_AGENT_INPUT_TOKEN_CEILING' in error
