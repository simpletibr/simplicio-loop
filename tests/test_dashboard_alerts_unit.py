'''Unit tests for the server-side alert rules of the Simplicio Live dashboard (issue #1406, slice 1406b, TDD red).

AlertWatch reads a run's dashboard events in order and reports the alerts it raised and cleared. One alert id is raised
once while it stays active, so repeated updates never duplicate it. The rules match the page's reducer: a stall lasts
until a different phase starts, a gate is failing while its latest verdict is fail, and the oracle is unverified once
the run is done and its receipt is ready but the oracle gave no verdict.
'''
from datetime import datetime, timedelta, timezone

from simplicio_loop.dashboard import alerts

RUN = 'run-alerts'
BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)
SILENCE_MS = 5 * 60 * 1000


def _stamp(offset_s):
    moment = BASE + timedelta(seconds=offset_s)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000)


def _ms(offset_s):
    return int((BASE + timedelta(seconds=offset_s)).timestamp() * 1000)


def _event(seq, offset_s, kind, phase=None, iteration=None, payload=None, severity='info'):
    return {'schema': 'simplicio.dashboard-event/v1', 'run_id': RUN, 'seq': seq, 'ts': _stamp(offset_s),
            'kind': kind, 'phase': phase, 'iteration': iteration, 'payload': payload or {},
            'severity': severity, 'source': 'hook', 'refs': []}


def _ids(watch):
    return [alert['id'] for alert in watch.snapshot()]


def test_a_stall_is_raised_critical_and_names_the_streak():
    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'phase_entered', phase='executing'),
                              _event(2, 1, 'stall_detected', phase='executing', payload={'streak': 3})], _ms(2))
    assert [alert['id'] for alert in raised] == ['run-stalled']
    assert raised[0]['severity'] == 'critical'
    assert '3' in raised[0]['why']


def test_a_stall_clears_when_a_different_phase_starts_but_not_when_the_same_phase_repeats():
    watch = alerts.AlertWatch()
    watch.update([_event(1, 0, 'phase_entered', phase='executing'),
                  _event(2, 1, 'stall_detected', phase='executing', payload={'streak': 2})], _ms(2))
    raised, cleared = watch.update([_event(3, 2, 'phase_entered', phase='executing')], _ms(3))
    assert raised == [] and cleared == []
    _, cleared = watch.update([_event(4, 3, 'phase_entered', phase='validating')], _ms(4))
    assert cleared == ['run-stalled']


def test_a_failing_gate_is_raised_and_cleared_by_a_later_pass():
    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'gate_evaluated', phase='validating',
                                     payload={'gate': 'watcher', 'verdict': 'fail', 'message': 'verificação falhou'})], _ms(1))
    assert [alert['id'] for alert in raised] == ['gate-failing:watcher']
    assert raised[0]['why'] == 'verificação falhou'
    _, cleared = watch.update([_event(2, 2, 'gate_evaluated', phase='validating',
                                      payload={'gate': 'watcher', 'verdict': 'pass'})], _ms(2))
    assert cleared == ['gate-failing:watcher']


def test_a_silent_phase_past_five_minutes_is_raised_and_a_new_event_clears_it():
    watch = alerts.AlertWatch()
    watch.update([_event(1, 0, 'phase_entered', phase='executing')], _ms(0))
    raised, _ = watch.update([], _ms(SILENCE_MS // 1000 + 1))
    assert [alert['id'] for alert in raised] == ['phase-silent:executing']
    assert raised[0]['ref'] == {'type': 'phase', 'phase': 'executing'}
    _, cleared = watch.update([_event(2, SILENCE_MS // 1000 + 2, 'iteration_started', phase='executing', iteration=1)],
                              _ms(SILENCE_MS // 1000 + 2))
    assert cleared == ['phase-silent:executing']


def test_a_silence_below_the_threshold_raises_nothing():
    watch = alerts.AlertWatch()
    watch.update([_event(1, 0, 'phase_entered', phase='executing')], _ms(0))
    raised, _ = watch.update([], _ms(SILENCE_MS // 1000 - 1))
    assert raised == []


def test_the_oracle_is_unverified_only_when_the_run_is_done_with_a_ready_receipt():
    calls = []

    def ready():
        calls.append(1)
        return True

    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'phase_entered', phase='executing')], _ms(0), receipt_ready=ready)
    assert raised == [] and calls == []  # not done yet: the receipt is not even read
    raised, _ = watch.update([_event(2, 1, 'phase_entered', phase='done')], _ms(1), receipt_ready=ready)
    assert [alert['id'] for alert in raised] == ['oracle-unverified']
    assert raised[0]['severity'] == 'warning'


def test_an_oracle_with_a_verdict_or_a_missing_receipt_raises_nothing():
    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'phase_entered', phase='done'),
                              _event(2, 1, 'gate_evaluated', phase='done', payload={'gate': 'oracle', 'verdict': 'pass'})],
                             _ms(1), receipt_ready=lambda: True)
    assert raised == []
    watch = alerts.AlertWatch()
    raised, _ = watch.update([_event(1, 0, 'phase_entered', phase='done')], _ms(0), receipt_ready=lambda: False)
    assert raised == []


def test_an_active_alert_is_never_raised_twice():
    watch = alerts.AlertWatch()
    watch.update([_event(1, 0, 'gate_evaluated', phase='validating',
                         payload={'gate': 'evidence', 'verdict': 'fail'})], _ms(0))
    for step in range(1, 5):
        raised, cleared = watch.update([], _ms(step))
        assert raised == [] and cleared == []
    assert _ids(watch) == ['gate-failing:evidence']


def test_the_snapshot_lists_the_active_alerts_critical_first():
    watch = alerts.AlertWatch()
    watch.update([_event(1, 0, 'phase_entered', phase='executing'),
                  _event(2, 1, 'gate_evaluated', phase='executing', payload={'gate': 'evidence', 'verdict': 'fail'}),
                  _event(3, 2, 'stall_detected', phase='executing', payload={'streak': 2})], _ms(2))
    assert _ids(watch) == ['run-stalled', 'gate-failing:evidence']


def test_a_healthy_six_minute_stream_raises_no_alert_at_any_step():
    watch = alerts.AlertWatch()
    events = [_event(1, 0, 'phase_entered', phase='executing'),
              _event(2, 1, 'iteration_started', phase='executing', iteration=1, payload={'trigger': 'user_prompt'})]
    events += [_event(position, position * 30, 'gate_evaluated', phase='executing', iteration=1,
                      payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'ok'}) for position in range(3, 15)]
    for event in events:
        raised, _ = watch.update([event], _ms(_offset(event)))
        assert raised == [], event['seq']
    assert watch.snapshot() == []


def _offset(event):
    moment = datetime.strptime(event['ts'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
    return int((moment - BASE).total_seconds())
