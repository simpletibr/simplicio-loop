'''Unit tests for the remaining alert rules of the Simplicio Live dashboard (issue #1406).

Lease expired (from the coordination view), the same stall fingerprint K times, a gate that fails again after a
fix, a decision that waits too long, and a per-phase silence threshold. Each rule has a fixture that raises it and
clears it, and a healthy long run raises none of them.
'''
from datetime import datetime, timedelta, timezone

from simplicio_loop.dashboard import alerts, config

RUN = 'run-rules'
BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


def _ms(offset_s):
    return int((BASE + timedelta(seconds=offset_s)).timestamp() * 1000)


def _event(seq, offset_s, kind, phase=None, payload=None):
    moment = BASE + timedelta(seconds=offset_s)
    return {'schema': 'simplicio.dashboard-event/v1', 'run_id': RUN, 'seq': seq,
            'ts': moment.strftime('%Y-%m-%dT%H:%M:%S.000Z'), 'kind': kind, 'phase': phase, 'iteration': None,
            'payload': payload or {}, 'severity': 'info', 'source': 'hook', 'refs': []}


def _ids(watch):
    return [alert['id'] for alert in watch.snapshot()]


def test_an_expired_lease_is_raised_critical_with_item_and_worker_and_cleared_when_it_is_renewed():
    leases = [{'item': 'T-1', 'worker': 'w-a', 'state': 'expired'}]
    watch = alerts.AlertWatch(leases=lambda: leases)
    raised, _ = watch.update([], _ms(0))
    assert [(a['id'], a['severity']) for a in raised] == [('lease-expired:T-1', 'critical')]
    assert 'T-1' in raised[0]['why'] and 'w-a' in raised[0]['why']
    leases[0] = {'item': 'T-1', 'worker': 'w-a', 'state': 'live'}
    _, cleared = watch.update([], _ms(1))
    assert cleared == ['lease-expired:T-1']


def test_live_and_stale_leases_and_a_failing_reader_raise_nothing():
    watch = alerts.AlertWatch(leases=lambda: [{'item': 'T-1', 'worker': 'w', 'state': 'live'},
                                              {'item': 'T-2', 'worker': 'w', 'state': 'stale'}])
    raised, _ = watch.update([], _ms(0))
    assert raised == []

    def broken():
        raise OSError('backlog gone')

    watch = alerts.AlertWatch(leases=broken)
    raised, _ = watch.update([], _ms(0))
    assert raised == []


def test_the_same_fingerprint_k_times_is_raised_and_a_new_phase_clears_it():
    watch = alerts.AlertWatch(stall_repeats=3)
    stall = lambda seq, at: _event(seq, at, 'stall_detected', 'executing', {'fingerprint': 'pytest:E1', 'streak': 1})
    raised, _ = watch.update([_event(1, 0, 'phase_entered', 'executing'), stall(2, 1), stall(3, 2)], _ms(3))
    assert 'stall-repeated:pytest:E1' not in [a['id'] for a in raised]
    raised, _ = watch.update([stall(4, 3)], _ms(4))
    assert [(a['id'], a['severity']) for a in raised] == [('stall-repeated:pytest:E1', 'critical')]
    assert '3' in raised[0]['why'] and 'pytest:E1' in raised[0]['why']
    _, cleared = watch.update([_event(5, 4, 'phase_entered', 'validating')], _ms(5))
    assert 'stall-repeated:pytest:E1' in cleared


def test_different_fingerprints_do_not_add_up():
    watch = alerts.AlertWatch(stall_repeats=3)
    events = [_event(1, 0, 'phase_entered', 'executing')]
    for seq, name in enumerate(['a', 'b', 'c'], start=2):
        events.append(_event(seq, seq, 'stall_detected', 'executing', {'fingerprint': name}))
    watch.update(events, _ms(5))
    assert not [i for i in _ids(watch) if i.startswith('stall-repeated')]


def test_a_gate_that_fails_again_after_a_fix_is_raised_and_cleared_by_a_pass():
    watch = alerts.AlertWatch()
    gate = lambda seq, at, verdict: _event(seq, at, 'gate_evaluated', 'validating', {'gate': 'tests', 'verdict': verdict})
    raised, _ = watch.update([gate(1, 0, 'fail')], _ms(1))
    assert [a['id'] for a in raised] == ['gate-failing:tests']  # first failure: no "again" yet
    raised, _ = watch.update([gate(2, 1, 'pass')], _ms(2))
    assert raised == []
    raised, _ = watch.update([gate(3, 2, 'fail')], _ms(3))
    assert sorted(a['id'] for a in raised) == ['gate-failing:tests', 'gate-refailed:tests']
    _, cleared = watch.update([gate(4, 3, 'pass')], _ms(4))
    assert sorted(cleared) == ['gate-failing:tests', 'gate-refailed:tests']


def test_a_decision_waiting_past_the_limit_is_raised_and_leaving_the_phase_clears_it():
    watch = alerts.AlertWatch(decision_wait_ms=10 * 60 * 1000, silence_ms=60 * 60 * 1000)
    watch.update([_event(1, 0, 'phase_entered', 'awaiting_decision')], _ms(0))
    raised, _ = watch.update([], _ms(10 * 60 - 1))
    assert raised == []
    raised, _ = watch.update([], _ms(10 * 60 + 1))
    assert [(a['id'], a['severity']) for a in raised] == [('decision-waiting', 'warning')]
    assert '10' in raised[0]['why']
    _, cleared = watch.update([_event(2, 10 * 60 + 2, 'phase_entered', 'executing')], _ms(10 * 60 + 3))
    assert 'decision-waiting' in cleared


def test_a_per_phase_silence_threshold_overrides_the_default_for_that_phase_only():
    watch = alerts.AlertWatch(phase_silence_ms={'executing': 30 * 60 * 1000})
    watch.update([_event(1, 0, 'phase_entered', 'executing')], _ms(0))
    raised, _ = watch.update([], _ms(10 * 60))
    assert raised == []  # default would be 5 min, executing may be silent for 30
    watch = alerts.AlertWatch(phase_silence_ms={'executing': 30 * 60 * 1000})
    watch.update([_event(1, 0, 'phase_entered', 'mapping')], _ms(0))
    raised, _ = watch.update([], _ms(6 * 60))
    assert [a['id'] for a in raised] == ['phase-silent:mapping']


def test_a_healthy_long_run_with_live_leases_raises_none_of_the_new_rules():
    watch = alerts.AlertWatch(leases=lambda: [{'item': 'T-1', 'worker': 'w', 'state': 'live'}])
    events = [_event(1, 0, 'phase_entered', 'mapping'), _event(2, 20, 'phase_entered', 'executing')]
    seq = 3
    for at in range(30, 3600, 45):
        verdict = 'pass'
        events.append(_event(seq, at, 'gate_evaluated', 'executing', {'gate': 'tests', 'verdict': verdict}))
        seq += 1
    for event in events:
        at = int((datetime.strptime(event['ts'], '%Y-%m-%dT%H:%M:%S.000Z').replace(tzinfo=timezone.utc) - BASE).total_seconds())
        raised, _ = watch.update([event], _ms(at))
        assert raised == [], event['seq']


def test_config_reads_the_new_thresholds_and_rejects_bad_values(tmp_path):
    path = tmp_path / '.simplicio-loop' / 'dashboard.toml'
    path.parent.mkdir(parents=True)
    path.write_text('[alerts]\nstall_fingerprint_repeats = 4\ndecision_wait_minutes = 20\n\n'
                    '[alerts.phase_silence]\nexecuting = 30\nmapping = 2\n', encoding='utf-8')
    cfg = config.load(tmp_path)
    assert cfg.stall_repeats == 4 and cfg.decision_wait_ms == 20 * 60 * 1000
    assert cfg.phase_silence_ms == {'executing': 30 * 60 * 1000, 'mapping': 2 * 60 * 1000}
    path.write_text('[alerts]\nstall_fingerprint_repeats = 1\ndecision_wait_minutes = -2\n\n'
                    '[alerts.phase_silence]\nexecuting = "x"\n', encoding='utf-8')
    cfg = config.load(tmp_path)
    assert cfg.stall_repeats == alerts.STALL_REPEATS and cfg.decision_wait_ms == alerts.DECISION_WAIT_MS
    assert cfg.phase_silence_ms == {} and len(cfg.problems) == 3
