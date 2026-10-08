'''Quality action and convergence unit tests for the Simplicio Live panels (issue #1403, slice 1403a, TDD red).

reducer.js has no quality action yet and selectView has no dod, quality or convergence keys, so these tests fail
on a missing key or a wrong value. The reducer runs in node through tests/fixtures/live_pipeline/driver.mjs.
The receipt has the quality-matrix.json shape: schema simplicio.quality-matrix/v1, coverage_threshold,
requirements and coverage.measured.
'''
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import dashboard_events as de

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
RUN_ID = 'run-q1'
BASE_MS = int(datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
PILLARS = ['implementation', 'unit', 'integration', 'system', 'regression', 'benchmark', 'coverage']
REQUIREMENTS = ['implementation', 'unit', 'integration', 'system', 'regression', 'benchmark']
NO_RECEIPT = 'quality-matrix.json ainda nao gerado'
NO_PRODUCER = 'sem produtor no fluxo atual'


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _drive(steps):
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps, 'runId': RUN_ID}),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _ts(offset_ms):
    moment = datetime.fromtimestamp((BASE_MS + offset_ms) / 1000, tz=timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000)


def _now_of(evt):
    parsed = datetime.strptime(evt['ts'], '%Y-%m-%dT%H:%M:%S.%fZ')
    return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _event(seq, offset_ms, kind, iteration=None, payload=None, severity='info'):
    evt = de.build_envelope(run_id=RUN_ID, kind=kind, source='hook', seq=seq, ts=_ts(offset_ms),
                            iteration=iteration, payload=payload or {}, severity=severity)
    assert de.validate_envelope(evt) == [], (kind, seq)
    return evt


def _event_steps(events):
    return [{'action': {'type': 'event', 'event': evt}, 'now': _now_of(evt)} for evt in events]


def _quality_step(receipt):
    return {'action': {'type': 'quality', 'receipt': receipt}, 'now': BASE_MS}


def _proof(name):
    return '.simplicio-loop/loop-runs/%s/evidence/%s.json' % (RUN_ID, name)


def _receipt(coverage=None):
    requirements = {name: {'status': 'pass', 'proof_ref': _proof(name), 'detail': name + ' verificado'}
                    for name in REQUIREMENTS}
    return {'schema': 'simplicio.quality-matrix/v1', 'run_id': RUN_ID, 'coverage_threshold': 85,
            'requirements': requirements,
            'coverage': coverage if coverage is not None else {'measured': 90.0}}


def _with_entry(name, entry):
    receipt = _receipt()
    receipt['requirements'][name] = entry
    return receipt


def _with_status(name, status):
    return _with_entry(name, {'status': status, 'proof_ref': _proof(name), 'detail': name})


def _dod_of(receipt):
    return _drive([_quality_step(receipt)])[-1]['dod']


def _pillar(dod, name):
    matches = [pillar for pillar in dod['pillars'] if pillar['pillar'] == name]
    assert len(matches) == 1, name
    return matches[0]


def _converging_events():
    return [
        _event(1, 0, 'iteration_started', iteration=1, payload={'trigger': 'user_prompt'}),
        _event(2, 2000, 'gate_evaluated', iteration=1, severity='warning',
               payload={'gate': 'dod', 'verdict': 'fail', 'message': 'dod incompleto'}),
        _event(3, 5000, 'iteration_finished', iteration=1, payload={'outcome': 'refeed'}),
        _event(4, 6000, 'iteration_started', iteration=2, payload={'trigger': 'refeed'}),
        _event(5, 7000, 'gate_evaluated', iteration=2,
               payload={'gate': 'evidence', 'verdict': 'pass', 'message': 'evidencia verificada'}),
        _event(6, 9000, 'iteration_finished', iteration=2, payload={'outcome': 'pass'}),
    ]


def test_quality_action_fills_the_seven_pillars_in_order():
    dod = _dod_of(_receipt())
    assert [pillar['pillar'] for pillar in dod['pillars']] == PILLARS
    assert all({'pillar', 'label', 'state', 'detail', 'ref'} <= set(pillar) for pillar in dod['pillars'])
    assert all(pillar['label'] for pillar in dod['pillars'])


@pytest.mark.parametrize('status, expected', [('pass', 'PASS'), ('fail', 'FAIL'),
                                              ('not_applicable', 'PENDING'), ('missing', 'UNVERIFIED')])
def test_requirement_status_maps_to_the_pillar_state(status, expected):
    assert _pillar(_dod_of(_with_status('unit', status)), 'unit')['state'] == expected


def test_a_failing_pillar_makes_the_dod_fail():
    assert _dod_of(_with_status('system', 'fail'))['state'] == 'FAIL'


def test_a_missing_pillar_leaves_the_dod_unverified():
    assert _dod_of(_with_status('regression', 'missing'))['state'] == 'UNVERIFIED'


def test_a_pending_pillar_keeps_the_dod_out_of_pass():
    assert _dod_of(_with_status('unit', 'not_applicable'))['state'] != 'PASS'


def test_a_complete_matrix_makes_the_dod_pass():
    assert _dod_of(_receipt())['state'] == 'PASS'


@pytest.mark.parametrize('measured, expected', [(84.9, 'FAIL'), (85, 'PASS')])
def test_coverage_is_compared_with_the_threshold(measured, expected):
    dod = _dod_of(_receipt(coverage={'measured': measured}))
    assert _pillar(dod, 'coverage')['state'] == expected
    assert dod['coverage'] == {'measured': measured, 'threshold': 85, 'state': expected}
    assert dod['state'] == expected


@pytest.mark.parametrize('coverage, expected', [({'measured': None, 'status': 'not_applicable'}, 'PENDING'),
                                                ({'measured': None}, 'UNVERIFIED')])
def test_coverage_without_a_measure_is_pending_only_when_not_applicable(coverage, expected):
    assert _pillar(_dod_of(_receipt(coverage=coverage)), 'coverage')['state'] == expected


def test_null_receipt_leaves_every_pillar_unverified_with_the_exact_detail():
    dod = _dod_of(None)
    assert [(pillar['state'], pillar['detail']) for pillar in dod['pillars']] == [('UNVERIFIED', NO_RECEIPT)] * 7
    assert dod['state'] == 'UNVERIFIED'
    assert dod['coverage']['measured'] is None
    assert dod['coverage']['state'] == 'UNVERIFIED'


def test_proof_ref_becomes_the_ref_after_the_run_segment():
    assert _pillar(_dod_of(_with_status('unit', 'pass')), 'unit')['ref'] == 'evidence/unit.json'


def test_proof_ref_without_the_run_segment_gives_a_null_ref():
    receipt = _with_entry('unit', {'status': 'pass', 'proof_ref': 'evidence/unit.json', 'detail': 'unit'})
    assert _pillar(_dod_of(receipt), 'unit')['ref'] is None


def test_quality_block_reports_the_diff_as_unverified_without_a_producer():
    for receipt in (None, _receipt()):
        quality = _drive([_quality_step(receipt)])[-1]['quality']
        assert quality['diff'] == {'state': 'UNVERIFIED', 'reason': NO_PRODUCER}


def test_quality_block_has_the_contract_keys():
    quality = _drive([_quality_step(_receipt())])[-1]['quality']
    assert {'tests', 'lint', 'coverageTrend', 'flaky', 'diff'} <= set(quality)


def test_convergence_has_one_point_per_finished_iteration_with_failing_and_unverified_counts():
    convergence = _drive(_event_steps(_converging_events()))[-1]['convergence']
    assert convergence['points'] == [{'iteration': 1, 'failing': 1, 'unverified': 5},
                                     {'iteration': 2, 'failing': 1, 'unverified': 4}]
    assert convergence['state'] == 'OK'


def test_convergence_ignores_an_iteration_that_is_still_open():
    convergence = _drive(_event_steps(_converging_events()[:4]))[-1]['convergence']
    assert convergence['points'] == [{'iteration': 1, 'failing': 1, 'unverified': 5}]


def test_convergence_without_points_is_unverified_with_a_reason():
    convergence = _drive([{'action': None, 'now': BASE_MS}])[-1]['convergence']
    assert (convergence['state'], convergence['points']) == ('UNVERIFIED', [])
    assert isinstance(convergence['reason'], str) and convergence['reason']
