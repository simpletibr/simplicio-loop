'''Reducer unit tests for the budget and tokens-by-phase rows of the Simplicio Live cost panel (issue #1404, TDD red).

The 'budget' action carries the GET /api/runs/<id>/budget body. A projection is an estimate, so it shows ESTIMADO
with its limit, use and projected figure in the reason; a measured overrun is FAIL; no limit or no usage stays
UNVERIFIED with the reason. Tokens by phase list the measured token_usage events, and stay UNVERIFIED with no producer.
'''
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
NOW = 1791453600000


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed')


def _rows(budget):
    steps = [{'action': {'type': 'budget', 'response': budget}, 'now': NOW}]
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps}), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return {row['key']: row for row in json.loads(proc.stdout)[-1]['agentsCost']}


def _row(state, **extra):
    base = {'limit': 600, 'used': 300, 'projected': 700.0, 'state': state, 'proof_kind': 'estimado', 'reason': None}
    base.update(extra)
    return base


def _report(tokens, by_phase=None, by_model=None):
    unverified = {'limit': None, 'used': None, 'projected': None, 'state': 'UNVERIFIED', 'proof_kind': 'estimado',
                  'reason': 'nenhum limite declarado no contrato da tarefa'}
    return {'phase': 'executing', 'limits': {}, 'rows': {'tokens': tokens, 'usd': unverified, 'seconds': unverified},
            'usage': {'tokens': 300, 'usd': None, 'samples': 1, 'by_phase': by_phase or {}, 'by_lane': {}, 'by_model': by_model or {}}}


def test_a_projection_over_the_limit_is_an_estimate_that_says_so():
    row = _rows(_report(_row('PROJECTED_OVER')))['budget']
    assert row['state'] == 'ESTIMADO'
    assert 'estimado' in row['reason'] and '600' in row['reason'] and 'passa do limite' in row['reason']


def test_a_forecast_that_fits_is_an_estimate_without_the_overrun_text():
    row = _rows(_report(_row('OK', projected=500.0)))['budget']
    assert row['state'] == 'ESTIMADO' and 'passa do limite' not in row['reason']


def test_a_measured_overrun_fails():
    row = _rows(_report(_row('EXCEEDED', used=700)))['budget']
    assert row['state'] == 'FAIL' and 'medido' in row['reason']


def test_no_limit_or_no_usage_stays_unverified_with_the_reason():
    row = _rows(_report(_row('UNVERIFIED', limit=None, used=None, projected=None, reason='nenhum limite declarado no contrato da tarefa')))['budget']
    assert row['state'] == 'UNVERIFIED' and row['reason'] == 'nenhum limite declarado no contrato da tarefa'


def test_without_a_budget_response_the_row_keeps_its_old_unverified_reason():
    row = _rows(None)['budget']
    assert row['state'] == 'UNVERIFIED' and row['reason']


def test_tokens_by_phase_list_the_measured_events_and_are_measured_not_estimated():
    row = _rows(_report(_row('OK'), by_phase={'planning': 120, 'executing': 365}, by_model={'m-a': 485}))['tokensByPhase']
    assert row['state'] == 'PASS'
    assert 'planning 120' in row['reason'] and 'executing 365' in row['reason'] and 'm-a 485' in row['reason']


def test_tokens_by_phase_without_a_producer_stays_unverified():
    assert _rows(_report(_row('OK')))['tokensByPhase']['state'] == 'UNVERIFIED'
