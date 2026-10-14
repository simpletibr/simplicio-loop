'''Unit tests for the price table and the agent-role payload of the Simplicio Live panel (issue #1404, slice 1404b, TDD red).

simplicio_loop/dashboard/prices.json is the only price source: it names its as_of date and the official page it was
copied from. The server ships it inside /api/tokens as `pricing`, and reads the stage-agents roles for /api/agents.
'''
import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PRICES = REPO / 'simplicio_loop' / 'dashboard' / 'prices.json'
SERVER = REPO / 'simplicio_loop' / 'dashboard' / 'server.py'
SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'


def _server():
    spec = importlib.util.spec_from_file_location('dashboard_server_under_test', SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Hook:
    def __init__(self, status):
        self._status = status

    def get_status(self):
        return self._status


def test_the_price_table_names_its_schema_date_and_source():
    table = json.loads(PRICES.read_text(encoding='utf-8'))
    assert table['schema'] == 'simplicio.price-table/v1'
    assert re.fullmatch(r'\d{4}-\d{2}-\d{2}', table['as_of']), table['as_of']
    assert table['source_url'] == SOURCE
    assert table['unit'] == 'USD per million tokens'


def test_every_price_is_a_positive_number_per_input_and_output():
    models = json.loads(PRICES.read_text(encoding='utf-8'))['models']
    assert models, 'the table lists no model'
    for model_id, prices in models.items():
        assert re.fullmatch(r'claude-[a-z]+-\d+(-\d+)?', model_id), model_id
        for field in ('input_per_mtok', 'output_per_mtok'):
            assert isinstance(prices[field], (int, float)) and prices[field] > 0, (model_id, field)


def test_the_table_carries_the_current_sonnet_55_and_haiku_55_prices_from_the_source():
    models = json.loads(PRICES.read_text(encoding='utf-8'))['models']
    assert models['claude-sonnet-5-5']['input_per_mtok'] == 2
    assert models['claude-sonnet-5-5']['output_per_mtok'] == 10
    assert models['claude-haiku-5-5']['input_per_mtok'] == 0.10
    assert 'note' in models['claude-haiku-5-5'], 'the prompt-length tier must be named, not hidden'


def test_tokens_payload_carries_the_price_table(monkeypatch):
    server = _server()
    monkeypatch.setattr(server, '_load_hook', lambda: _Hook({'requests': 1}))
    body = server._tokens()
    assert body['status'] == 'MEASURED'
    assert body['pricing'] == json.loads(PRICES.read_text(encoding='utf-8'))


def test_tokens_payload_marks_the_pricing_unverified_when_the_table_is_unreadable(monkeypatch):
    server = _server()
    monkeypatch.setattr(server, '_load_hook', lambda: _Hook({'requests': 1}))
    monkeypatch.setattr(server, 'PRICES_FILE', REPO / 'missing' / 'prices.json')
    body = server._tokens()
    assert body['pricing'] == {'status': 'UNVERIFIED', 'reason': 'tabela de preços indisponível'}


def test_agents_lists_the_contract_roles_and_never_passes(monkeypatch):
    server = _server()
    body = server._agents()
    assert body['status'] == 'UNVERIFIED'
    role_ids = [role['role_id'] for role in body['roles']]
    assert 'implementation_agent' in role_ids and 'completion_auditor' in role_ids
    executing = next(role for role in body['roles'] if role['role_id'] == 'implementation_agent')
    assert executing['stages'] == ['executing']
    assert 'instâncias' in body['reason']


def test_agents_is_unverified_when_the_contract_cannot_be_read(monkeypatch):
    server = _server()
    monkeypatch.setattr(server, 'STAGES_FILE', str(REPO / 'missing' / 'stages.json'))
    body = server._agents()
    assert body['status'] == 'UNVERIFIED' and body['roles'] == []
    assert body['reason']
