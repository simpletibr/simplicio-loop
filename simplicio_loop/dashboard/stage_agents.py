'''Per-stage agents, tokens and cost for the Simplicio Live dashboard (issue #1404).

One row per (stage, model) read from the token_usage events. The model and the tokens are measured; the role and the
effort are the model-roles table's default for that model, not an observation of the agent that ran. The cost goes
through budget.cost_estimate, so a stage's cost and the run's cost share one price path. Every cost is an estimate
and carries proof_kind "estimado". A model the table does not list gets no role and an UNVERIFIED cost with the reason.
'''
from __future__ import annotations

from typing import Any, Iterable

from simplicio_loop import model_roles
from simplicio_loop.dashboard import budget

SCHEMA = 'simplicio.dashboard-event/v1'
VIEW_SCHEMA = 'simplicio.dashboard-stage-agents/v1'


def view(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''The GET /api/runs/<id>/stage-agents body: the per-stage rows plus the run's own cost estimate.'''
    events = list(events)
    return {'schema': VIEW_SCHEMA, 'rows': rows(events, prices), 'cost': budget.cost_estimate(events, prices)}


def rows(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> list[dict[str, Any]]:
    '''One row per (stage, model), in first-seen order. Empty when no token_usage event was measured.'''
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, dict) or event.get('schema') != SCHEMA or event.get('kind') != 'token_usage':
            continue
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        phase = event.get('phase') if isinstance(event.get('phase'), str) else ''
        model = payload.get('model') if isinstance(payload.get('model'), str) else ''
        groups.setdefault((phase, model), []).append(event)
    out = []
    for (phase, model), group in groups.items():
        tokens_in = tokens_out = 0
        for event in group:
            payload = event['payload'] if isinstance(event.get('payload'), dict) else {}
            tokens_in += budget._number(payload.get('input_tokens')) or 0
            tokens_out += budget._number(payload.get('output_tokens')) or 0
        cost = budget.cost_estimate(group, prices)
        placed = model_roles.role_of(model) if model else None
        reason = cost['reason'] or (None if placed else 'modelo sem papel na tabela de papéis')
        out.append({'phase': phase or None, 'role': placed['role'] if placed else None,
                    'effort': placed['effort'] if placed else None, 'model': model or None,
                    'tokens_in': tokens_in, 'tokens_out': tokens_out, 'cost_usd': cost['usd'],
                    'cost_state': cost['state'], 'proof_kind': 'estimado', 'reason': reason})
    return out
