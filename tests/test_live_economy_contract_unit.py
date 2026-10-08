'''Contract test for the Simplicio Live global economy panel (issue #1404, slice 1404a, TDD red).

hooks/simplicio_dashboard.py get_status() is the source of the token numbers. The test writes a fixture
proxy_savings.json under a temporary HOME, loads the hook with importlib, feeds get_status() through the reducer as a
tokens action and checks that the economy fields equal the status fields. It fails today because the reducer has no
tokens action and no economy key. It skips when node is missing.
'''
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / 'hooks' / 'simplicio_dashboard.py'
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
SAVINGS = {
    'lifetime': {'requests': 4, 'tokens_saved': 1500, 'total_input_tokens': 4500,
                 'compression_savings_usd': 0.0345, 'total_output_tokens': 900},
    'history': [
        {'timestamp': '2026-10-08T09:00:00Z', 'provider': 'anthropic', 'model': 'claude-sonnet-4-5',
         'total_input_tokens': 1200, 'total_tokens_saved': 500},
        {'timestamp': '2026-10-08T09:02:00Z', 'provider': 'openai', 'model': 'gpt-4o',
         'total_input_tokens': 900, 'total_tokens_saved': 300},
        {'timestamp': '2026-10-08T09:05:00Z', 'provider': 'anthropic', 'model': 'claude-sonnet-4-5',
         'total_input_tokens': 1000, 'total_tokens_saved': 400},
        {'timestamp': '2026-10-08T09:09:00Z', 'provider': 'deepseek', 'model': 'deepseek-v3',
         'total_input_tokens': 1400, 'total_tokens_saved': 300},
    ],
    'display_session': {'started_at': '2026-10-08T09:00:00Z', 'last_activity_at': '2026-10-08T09:09:00Z',
                        'tokens_saved': 1500},
}


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _drive(steps):
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps}), capture_output=True,
                          text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _status(monkeypatch, home):
    savings = home / '.simplicio-loop' / 'proxy_savings.json'
    savings.parent.mkdir(parents=True)
    savings.write_text(json.dumps(SAVINGS), encoding='utf-8')
    # The hook reads HOME at import time, so HOME is set before the module is executed.
    monkeypatch.setenv('HOME', str(home))
    spec = importlib.util.spec_from_file_location('simplicio_dashboard_economy_contract', HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_status()


def _economy(status):
    response = {'status': 'MEASURED', 'data': status}
    steps = [{'action': {'type': 'tokens', 'response': response}, 'now': 0}]
    return _drive(steps)[-1]['economy']


@pytest.fixture
def run(monkeypatch, tmp_path):
    status = _status(monkeypatch, tmp_path)
    return status, _economy(status)


def test_economy_fields_equal_the_get_status_fields(run):
    status, economy = run
    assert economy['status'] == 'MEASURED'
    assert economy['requests'] == status['requests']
    assert economy['tokensBefore'] == status['tokens_before']
    assert economy['tokensAfter'] == status['tokens_after']
    assert economy['tokensSaved'] == status['tokens_saved']
    assert economy['savingsPct'] == status['savings_pct']
    assert economy['usdSaved'] == status['usd_saved']
    assert economy['proxyRunning'] == status['proxy_running']
    assert economy['ledgerEvents'] == status['ledger_events']
    assert economy['activeModel'] == (status['active_model'] or None)
    assert economy['modelsSeen'] == status['models_seen']
    assert economy['series'] == [entry['saved'] for entry in status['series']]


def test_the_fixture_numbers_reach_the_view(run):
    _, economy = run
    assert (economy['requests'], economy['tokensBefore'], economy['tokensAfter'], economy['tokensSaved'],
            economy['savingsPct']) == (4, 6000, 4500, 1500, 25.0)


def test_providers_come_from_the_status_and_not_intercept_is_the_difference(run):
    status, economy = run
    total, interceptable = status['provider_total'], status['provider_interceptable']
    assert economy['providers'] == {'total': total, 'interceptable': interceptable,
                                    'notInterceptable': max(0, total - interceptable)}


def test_the_economy_never_carries_log_lines_or_runtimes(run):
    status, economy = run
    assert 'runtimes' in status
    assert 'log_lines' not in economy and 'runtimes' not in economy
