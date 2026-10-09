'''Contract between the global economy card (static/live/economy.js) and the budget cost (budget.cost_estimate).

Both paths price from simplicio_loop/dashboard/prices.json. The contract (issue #1404, criterion "os números batem"):
for the same model id and the same input tokens, the economy card's input USD equals the budget's USD, and a dated
model id (for example claude-haiku-5-5-20251001) resolves to its family's price the same way in both. The JS side runs
under node; the test skips when no node is installed, as the reducer tests do.
'''
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from simplicio_loop.dashboard import budget

REPO = Path(__file__).resolve().parents[1]
DASHBOARD = REPO / 'simplicio_loop' / 'dashboard'
ECONOMY = DASHBOARD / 'static' / 'live' / 'economy.js'
PRICES = DASHBOARD / 'prices.json'
MODEL_IDS = ['claude-haiku-5-5', 'claude-haiku-5-5-20251001', 'claude-sonnet-5-5-20260101', 'claude-opus-5-5']
TOKENS = 2_500_000


def _node():
    for candidate in (shutil.which('node'), '/opt/node22/bin/node'):
        if candidate:
            return candidate
    pytest.skip('node is not installed: no node on PATH and no /opt/node22/bin/node')


def _prices():
    return json.loads(PRICES.read_text(encoding='utf-8'))


def _economy_input_usd(model):
    script = (
        "import { economyView } from " + json.dumps(ECONOMY.as_uri()) + ";\n"
        "import fs from 'node:fs';\n"
        "const response = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        "process.stdout.write(JSON.stringify(economyView(response).cost));\n"
    )
    payload = {
        'status': 'MEASURED',
        'pricing': _prices(),
        'data': {
            'requests': 3,
            'tokens_before': TOKENS,
            'tokens_after': TOKENS,
            'tokens_saved': 0,
            'active_model': {'model': model},
            'models_seen': [model],
        },
    }
    proc = subprocess.run([_node(), '--input-type=module', '-e', script], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    cost = json.loads(proc.stdout)
    assert cost['state'] == 'ESTIMADO', cost
    return cost['inputUsd']


def _budget_input_usd(model):
    event = {'schema': budget.SCHEMA, 'kind': 'token_usage',
             'payload': {'model': model, 'input_tokens': TOKENS, 'output_tokens': 0}}
    row = budget.cost_estimate([event], _prices())
    assert row['state'] == 'ESTIMADO', row
    return row['usd']


@pytest.mark.parametrize('model', MODEL_IDS)
def test_economy_input_usd_equals_the_budget_input_side_for_the_same_model(model):
    assert _economy_input_usd(model) == pytest.approx(_budget_input_usd(model), rel=1e-9), model


def test_economy_js_carries_no_price_literal_of_its_own():
    text = ECONOMY.read_text(encoding='utf-8')
    assert not __import__('re').search(r'(input|output)_per_mtok\s*[:=]\s*\d', text), (
        'economy.js hard-codes a rate; the price must come from the backend table in response.pricing')
