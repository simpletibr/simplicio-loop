'''Pure reducer unit tests for the Simplicio Live global economy panel (issue #1404, slice 1404a, TDD red).

reducer.js does not import ./economy.js yet, has no tokens action and selectView has no economy key, so these tests
fail on a missing key, a missing module or a wrong value. The reducer runs in node through
tests/fixtures/live_pipeline/driver.mjs; the events are built and validated with scripts/dashboard_events.py.
'''
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

import dashboard_events as de

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
REDUCER = REPO / 'simplicio_loop' / 'dashboard' / 'static' / 'live' / 'reducer.js'
RUN_ID = 'run-economy-fixture'
BASE_MS = int(datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
ECONOMY_KEYS = ['status', 'reason', 'scope', 'proof', 'requests', 'tokensBefore', 'tokensAfter', 'tokensSaved',
                'savingsPct', 'usdSaved', 'providers', 'proxyRunning', 'ledgerEvents', 'activeModel', 'modelsSeen',
                'series', 'seriesKind', 'cost']
AGENT_KEYS = ['agentMap', 'tokensByPhase', 'cost', 'budget', 'comparison']
AGENT_ROW_KEYS = ['key', 'label', 'state', 'reason']
VIEW_KEYS = ['runId', 'lastSeq', 'connection', 'phase', 'rail', 'percent', 'phases', 'gates', 'agora', 'health',
             'lanes', 'alerts', 'iterations', 'convergence', 'dod', 'quality']
NO_PANEL = 'painel de tokens indisponivel'
NO_TRAFFIC = 'proxy de captura sem trafego medido'
LOG_MARKER = 'LOG-MARKER-7f3a'
ACTIVE = {'provider': 'anthropic', 'model': 'claude-sonnet-4-5', 'timestamp': '2026-10-08T09:10:00Z', 'saved': 400}
MODELS = [{'provider': 'anthropic', 'model': 'claude-sonnet-4-5'}, {'provider': 'openai', 'model': 'gpt-4o'}]
SERIES = [
    {'before': 1200, 'after': 800, 'saved': 400, 'ts': '2026-10-08T09:00:00Z'},
    {'before': 900, 'after': 600, 'saved': 300, 'ts': '2026-10-08T09:05:00Z'},
    {'before': 1000, 'after': 600, 'saved': 400, 'ts': '2026-10-08T09:10:00Z'},
]
MEASURED_DATA = {
    'requests': 12, 'tokens_before': 10000, 'tokens_after': 6000, 'tokens_saved': 4000, 'savings_pct': 40.0,
    'usd_saved': 0.12, 'provider_total': 5, 'provider_interceptable': 3, 'proxy_running': True,
    'ledger_events': 9, 'active_model': ACTIVE, 'models_seen': MODELS, 'series': SERIES,
    'log_lines': [LOG_MARKER + ' PERF tok_before=1000 tok_after=600'],
    'runtimes': [{'name': 'codex', 'active': True}],
}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _run_node(args, stdin_text=''):
    proc = subprocess.run([_node()] + args, input=stdin_text, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _drive(steps):
    return _run_node([str(DRIVER)], json.dumps({'steps': steps}))


def _ts(offset_ms):
    moment = datetime.fromtimestamp((BASE_MS + offset_ms) / 1000, tz=timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000)


def _event(seq, offset_ms, kind, iteration=None, payload=None):
    evt = de.build_envelope(run_id=RUN_ID, kind=kind, source='hook', seq=seq, ts=_ts(offset_ms),
                            iteration=iteration, payload=payload or {}, severity='info')
    assert de.validate_envelope(evt) == [], (kind, seq)
    return evt


def _event_steps(events):
    steps = []
    for evt in events:
        parsed = datetime.strptime(evt['ts'], '%Y-%m-%dT%H:%M:%S.%fZ')
        now = int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)
        steps.append({'action': {'type': 'event', 'event': evt}, 'now': now})
    return steps


def _tokens(response):
    return {'action': {'type': 'tokens', 'response': response}, 'now': BASE_MS}


def _measured(**changes):
    return {'status': 'MEASURED', 'data': dict(MEASURED_DATA, **changes)}


def _economy(response):
    return _drive([_tokens(response)])[-1]['economy']


def _agents(response):
    return _drive([_tokens(response)])[-1]['agentsCost']


def test_measured_numbers_equal_the_input():
    economy = _economy(_measured())
    assert economy['status'] == 'MEASURED'
    assert (economy['requests'], economy['tokensBefore'], economy['tokensAfter'], economy['tokensSaved'],
            economy['savingsPct'], economy['usdSaved']) == (12, 10000, 6000, 4000, 40.0, 0.12)


def test_measured_providers_proxy_ledger_and_active_model_come_from_the_input():
    economy = _economy(_measured())
    assert economy['providers'] == {'total': 5, 'interceptable': 3, 'notInterceptable': 2}
    assert (economy['proxyRunning'], economy['ledgerEvents'], economy['activeModel']) == (True, 9, ACTIVE)


@pytest.mark.parametrize('total, interceptable, expected', [(5, 3, 2), (4, 4, 0), (2, 5, 0)])
def test_not_intercept_is_total_minus_interceptable_and_never_negative(total, interceptable, expected):
    economy = _economy(_measured(provider_total=total, provider_interceptable=interceptable))
    assert economy['providers']['notInterceptable'] == expected


def test_proof_marks_tokens_and_usd_as_estimated():
    assert _economy(_measured())['proof'] == {'tokens': 'estimado', 'usd': 'estimado'}


def test_series_is_the_saved_tokens_of_each_entry_and_is_acumulado():
    economy = _economy(_measured())
    assert economy['series'] == [400, 300, 400]
    assert economy['seriesKind'] == 'acumulado'


def test_economy_keeps_exactly_the_contract_keys_and_global_scope():
    economy = _economy(_measured())
    assert sorted(economy) == sorted(ECONOMY_KEYS)
    assert economy['scope'] == 'global'


def test_models_seen_is_capped_at_eight_entries():
    models = [{'provider': 'p%d' % n, 'model': 'm%d' % n} for n in range(10)]
    assert _economy(_measured(models_seen=models))['modelsSeen'] == models[:8]


def test_active_model_is_null_without_history():
    assert _economy(_measured(active_model={}))['activeModel'] is None


def test_a_missing_panel_response_is_unverified_with_its_reason():
    economy = _economy(None)
    assert (economy['status'], economy['reason']) == ('UNVERIFIED', NO_PANEL)


def test_a_response_that_is_not_measured_is_unverified_with_its_reason():
    economy = _economy({'status': 'UNVERIFIED', 'reason': 'proxy offline', 'data': MEASURED_DATA})
    assert (economy['status'], economy['reason']) == ('UNVERIFIED', 'proxy offline')


def test_a_measured_response_without_data_is_unverified():
    assert _economy({'status': 'MEASURED'})['status'] == 'UNVERIFIED'


def test_zero_requests_is_unverified_with_the_traffic_reason():
    economy = _economy(_measured(requests=0))
    assert (economy['status'], economy['reason']) == ('UNVERIFIED', NO_TRAFFIC)


def test_the_economy_view_never_carries_log_lines_or_runtimes():
    economy = _economy(_measured())
    assert 'log_lines' not in economy and 'runtimes' not in economy
    assert LOG_MARKER not in json.dumps(economy, ensure_ascii=False)


def test_agents_cost_lists_five_rows_in_contract_order():
    assert [row['key'] for row in _agents(_measured())] == AGENT_KEYS


def test_each_agents_cost_row_has_a_label_and_a_reason_and_only_the_cost_row_is_estimated():
    for row in _agents(_measured()):
        extra = {'roles'} if row['key'] == 'agentMap' else set()
        assert set(row) == set(AGENT_ROW_KEYS) | extra, row
        assert row['state'] in ('UNVERIFIED', 'ESTIMADO'), row
        assert row['state'] != 'ESTIMADO' or row['key'] == 'cost', row
        assert row['label'] and row['reason'], row


@pytest.mark.parametrize('response', [None, _measured(), _measured(requests=0)])
def test_no_agents_cost_row_is_ever_pass(response):
    assert 'PASS' not in [row['state'] for row in _agents(response)]


def test_the_tokens_action_leaves_last_seq_untouched():
    events = [_event(1, 0, 'iteration_started', payload={'trigger': 'user_prompt'}),
              _event(2, 1000, 'iteration_started', iteration=1, payload={'trigger': 'refeed'})]
    views = _drive(_event_steps(events) + [_tokens(_measured())])
    assert views[-2]['lastSeq'] == 2
    assert 'economy' in views[-1], 'the tokens action is not applied'
    assert views[-1]['lastSeq'] == views[-2]['lastSeq']


def test_the_existing_view_keys_are_still_there():
    view = _drive([_tokens(_measured())])[-1]
    assert [key for key in VIEW_KEYS if key not in view] == []


def test_reducer_imports_the_economy_module():
    text = REDUCER.read_text(encoding='utf-8')
    assert re.search(r'import\s[^;]*from\s+\S*economy\.js', text), 'reducer.js does not import ./economy.js'
