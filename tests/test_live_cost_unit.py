'''Pure reducer unit tests for the 1404b cost and agent rows of the Simplicio Live economy panel (issue #1404, TDD red).

The reducer turns the proxy's measured tokens and the page's price table into an ESTIMADO cost with the active model's
input price. A cost with no measured tokens, no identified model or no table entry stays UNVERIFIED with a reason.
Agent roles come from the stage-agents contract through the 'agents' action; no instance is measured, so no row passes.
The reducer runs in node through tests/fixtures/live_pipeline/driver.mjs.
'''
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'driver.mjs'
BASE_MS = int(datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
AS_OF = '2026-10-08'
SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
PRICING = {
    'schema': 'simplicio.price-table/v1', 'as_of': AS_OF, 'source_url': SOURCE, 'unit': 'USD per million tokens',
    'models': {
        'claude-sonnet-4-6': {'input_per_mtok': 3, 'output_per_mtok': 15},
        'claude-haiku-5-5': {'input_per_mtok': 0.10, 'output_per_mtok': 0.50, 'note': 'acima de 100 mil tokens: tarifa maior'},
        'claude-haiku-5': {'input_per_mtok': 9, 'output_per_mtok': 9},
    },
}
AGENTS = {
    'status': 'UNVERIFIED', 'reason': 'instâncias ativas não medidas',
    'roles': [
        {'role_id': 'implementation_agent', 'title': 'Implementation Agent', 'stages': ['executing']},
        {'role_id': 'review_panel', 'title': 'Independent Review Panel', 'stages': ['validating', 'watching']},
    ],
}
AGENT_KEYS = ['agentMap', 'tokensByPhase', 'cost', 'budget', 'comparison']


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _drive(steps):
    proc = subprocess.run([_node(), str(DRIVER)], input=json.dumps({'steps': steps}),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _data(**overrides):
    data = {
        'requests': 12, 'tokens_before': 10000, 'tokens_after': 6000, 'tokens_saved': 4000, 'savings_pct': 40.0,
        'usd_saved': 0.12, 'provider_total': 5, 'provider_interceptable': 3, 'proxy_running': True,
        'ledger_events': 9,
        'active_model': {'provider': 'anthropic', 'model': 'claude-sonnet-4-6', 'timestamp': '2026-10-08T09:10:00Z', 'saved': 400},
        'models_seen': [{'provider': 'anthropic', 'model': 'claude-sonnet-4-6'}], 'series': [],
    }
    data.update(overrides)
    return data


def _response(data=None, pricing=PRICING):
    response = {'status': 'MEASURED', 'source': 'hooks/simplicio_dashboard.py get_status', 'cost_usd': 'UNVERIFIED',
                'data': _data() if data is None else data}
    if pricing is not None:
        response['pricing'] = pricing
    return response


def _tokens_step(response):
    return {'action': {'type': 'tokens', 'response': response}, 'now': BASE_MS}


def _cost(response):
    return _drive([_tokens_step(response)])[-1]['economy']['cost']


def _rows(response, agents=AGENTS):
    steps = [_tokens_step(response), {'action': {'type': 'agents', 'response': agents}, 'now': BASE_MS}]
    return _drive(steps)[-1]['agentsCost']


def _row(rows, key):
    matches = [row for row in rows if row['key'] == key]
    assert len(matches) == 1, key
    return matches[0]


def test_measured_tokens_with_a_priced_model_give_an_estimate_of_the_sent_and_saved_tokens():
    cost = _cost(_response())
    assert cost['state'] == 'ESTIMADO'
    assert cost['proof'] == 'estimado'
    assert cost['model'] == 'claude-sonnet-4-6'
    assert cost['inputPerMtok'] == 3
    assert cost['inputUsd'] == pytest.approx(6000 * 3 / 1_000_000)
    assert cost['savedUsd'] == pytest.approx(4000 * 3 / 1_000_000)
    assert cost['asOf'] == AS_OF
    assert cost['sourceUrl'] == SOURCE


def test_a_dated_model_id_takes_the_price_of_the_longest_matching_key():
    cost = _cost(_response(_data(active_model={'provider': 'anthropic', 'model': 'claude-haiku-5-5-20261001'})))
    assert cost['state'] == 'ESTIMADO'
    assert cost['inputPerMtok'] == 0.10
    assert cost['note'] == 'acima de 100 mil tokens: tarifa maior'


def test_a_model_missing_from_the_table_stays_unverified_with_the_reason():
    cost = _cost(_response(_data(active_model={'provider': 'openai', 'model': 'gpt-4o'})))
    assert (cost['state'], cost['inputUsd'], cost['savedUsd']) == ('UNVERIFIED', None, None)
    assert 'tabela' in cost['reason']


def test_no_identified_active_model_stays_unverified():
    cost = _cost(_response(_data(active_model={})))
    assert cost['state'] == 'UNVERIFIED'
    assert cost['reason'] == 'modelo ativo não identificado'


def test_a_missing_price_table_stays_unverified():
    cost = _cost(_response(pricing=None))
    assert cost['state'] == 'UNVERIFIED'
    assert cost['reason'] == 'tabela de preços indisponível'


def test_an_unmeasured_economy_passes_its_reason_to_the_cost():
    cost = _cost({'status': 'UNVERIFIED', 'reason': 'token monitor unavailable: OSError'})
    assert cost['state'] == 'UNVERIFIED'
    assert cost['reason'] == 'token monitor unavailable: OSError'


def test_zero_traffic_gives_no_cost():
    cost = _cost(_response(_data(requests=0)))
    assert cost['state'] == 'UNVERIFIED'
    assert cost['inputUsd'] is None


def test_agent_map_lists_the_contract_roles_and_stays_unverified():
    row = _row(_rows(_response()), 'agentMap')
    assert row['state'] == 'UNVERIFIED'
    assert 'instâncias ativas não medidas' in row['reason']
    assert row['roles'] == AGENTS['roles']


def test_agent_map_without_contract_roles_is_unverified_with_a_reason():
    row = _row(_rows(_response(), agents={'status': 'UNVERIFIED', 'roles': [], 'reason': 'contrato ilegível'}), 'agentMap')
    assert row['state'] == 'UNVERIFIED'
    assert row['reason'] == 'contrato ilegível'
    assert row['roles'] == []


def test_the_cost_row_shows_the_estimate_as_its_state_and_reason():
    row = _row(_rows(_response()), 'cost')
    assert row['state'] == 'ESTIMADO'
    assert 'estimado' in row['reason'] and 'claude-sonnet-4-6' in row['reason']


def test_the_cost_row_stays_unverified_when_the_cost_is_unknown():
    row = _row(_rows(_response(pricing=None)), 'cost')
    assert row['state'] == 'UNVERIFIED'
    assert row['reason'] == 'tabela de preços indisponível'


def test_budget_and_comparison_stay_unverified_with_a_reason_until_their_producers_exist():
    rows = _rows(_response())
    for key in ('budget', 'comparison', 'tokensByPhase'):
        row = _row(rows, key)
        assert row['state'] == 'UNVERIFIED', key
        assert row['reason'], key


def test_no_agent_row_is_ever_pass():
    rows = _rows(_response())
    assert [row['key'] for row in rows] == AGENT_KEYS
    assert {row['state'] for row in rows} <= {'ESTIMADO', 'UNVERIFIED'}
