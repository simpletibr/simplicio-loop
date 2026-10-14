'''Contract test for the budget alert of the Simplicio Live alerts panel (issue #1404, criterion: the budget alert fires
when the projection passes the limit).

The limit comes from the run's task-contract.json through budget.declared, the usage from token_usage events, and the alert
from AlertWatch, the same path the dashboard server runs for each SSE stream. The alert is labelled proof_kind "estimado"
because it is a projection.
'''
import json
from datetime import datetime, timezone

from simplicio_loop.dashboard import alerts, budget

BASE = datetime(2026, 10, 8, 10, 0, 0, tzinfo=timezone.utc)


def _at(offset_s):
    return datetime.fromtimestamp(BASE.timestamp() + offset_s, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _event(seq, offset_s, kind, phase=None, payload=None):
    event = {'schema': 'simplicio.dashboard-event/v1', 'seq': seq, 'kind': kind, 'ts': _at(offset_s), 'payload': payload or {}}
    if phase:
        event['phase'] = phase
    return event


def test_projection_over_the_contract_limit_raises_an_estimado_budget_alert(tmp_path):
    (tmp_path / 'task-contract.json').write_text(json.dumps({'tasks': [{'routing': {'budget': {'tokens': 600}}}]}), encoding='utf-8')
    limits = budget.declared(tmp_path)
    watch = alerts.AlertWatch(budget=limits)
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    raised, _ = watch.update(events, int(BASE.timestamp() * 1000) + 2000)
    budget_alerts = [a for a in raised if a['rule'] == 'budget-projected']
    assert [(a['id'], a['severity'], a['proof_kind']) for a in budget_alerts] == [('budget-projected:tokens', 'warning', 'estimado')]


def test_projection_within_the_contract_limit_raises_no_budget_alert(tmp_path):
    (tmp_path / 'task-contract.json').write_text(json.dumps({'tasks': [{'routing': {'budget': {'tokens': 5000}}}]}), encoding='utf-8')
    watch = alerts.AlertWatch(budget=budget.declared(tmp_path))
    events = [
        _event(1, 0, 'phase_entered', phase='executing'),
        _event(2, 1, 'token_usage', phase='executing', payload={'model': 'claude-haiku-5-5', 'input_tokens': 300, 'output_tokens': 0}),
    ]
    raised, _ = watch.update(events, int(BASE.timestamp() * 1000) + 2000)
    assert [a for a in raised if a['rule'] == 'budget-projected'] == []
