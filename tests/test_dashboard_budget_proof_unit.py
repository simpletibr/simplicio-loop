'''Unit tests for the proof_kind of the budget alerts (issue #1404, criterion: estimated values are labelled).

A projection is an extrapolation, so its alert says "estimado". An overrun already measured says "medido". The alert
carries the proof_kind so the UI can label it without reading the message text.
'''
from datetime import datetime, timezone

from simplicio_loop.dashboard import alerts

BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


def _ms(seconds):
    return int((BASE.timestamp() + seconds) * 1000)


def _event(seq, offset_s, kind, phase=None, payload=None):
    stamp = datetime.fromtimestamp(BASE.timestamp() + offset_s, tz=timezone.utc)
    event = {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': kind,
             'ts': stamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), 'payload': payload or {}}
    if phase:
        event['phase'] = phase
    return event


def _usage(seq, offset_s, tokens):
    return _event(seq, offset_s, 'token_usage', phase='executing',
                  payload={'model': 'm', 'input_tokens': tokens, 'output_tokens': 0})


def test_projected_overrun_alert_is_labelled_estimado():
    watch = alerts.AlertWatch(budget={'tokens': 600, 'usd': None, 'seconds': None})
    raised, _ = watch.update([_event(1, 0, 'phase_entered', phase='executing'), _usage(2, 1, 300)], _ms(2))
    assert [(a['id'], a['proof_kind']) for a in raised] == [('budget-projected:tokens', 'estimado')]


def test_measured_overrun_alert_is_labelled_medido():
    watch = alerts.AlertWatch(budget={'tokens': 600, 'usd': None, 'seconds': None})
    watch.update([_event(1, 0, 'phase_entered', phase='executing'), _usage(2, 1, 300)], _ms(2))
    raised, _ = watch.update([_usage(3, 2, 400)], _ms(3))
    assert [(a['id'], a['proof_kind']) for a in raised] == [('budget-exceeded:tokens', 'medido')]


def test_non_budget_alerts_still_carry_a_proof_kind_field():
    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'stall_detected', phase='executing', payload={'streak': 2})], _ms(1))
    assert raised and all('proof_kind' in a for a in raised)
