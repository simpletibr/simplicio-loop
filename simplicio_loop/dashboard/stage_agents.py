'''Per-stage agents, tokens and cost for the Simplicio Live dashboard (issue #1404).

One row per (stage, model) read from the token_usage events. The model and the tokens are measured; the role and the
effort are the model-roles table's default for that model, not an observation of the agent that ran. The cost goes
through budget.cost_estimate, so a stage's cost and the run's cost share one price path. Every cost is an estimate
and carries proof_kind "estimado". A model the table does not list gets no role and an UNVERIFIED cost with the reason.

The breakdown (issue #1550) groups the same token_usage events by phase, lane, model, task and iteration, and the agent
map groups the worker_claimed events by lane. Tokens are measured (proof_kind "medido"); a cost is always an estimate.
The runner records 0 or null for the provider tokens of a worker run, so those tokens, and the cost built on them, stay
UNVERIFIED with the reason: nothing is invented. The event stream has no slot event, so slots are UNVERIFIED too.
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
    return {'schema': VIEW_SCHEMA, 'rows': rows(events, prices), 'cost': budget.cost_estimate(events, prices),
            'breakdown': breakdown(events, prices), 'agent_map': agent_map(events)}


def _is_event(event: Any, kind: str) -> bool:
    return isinstance(event, dict) and event.get('schema') == SCHEMA and event.get('kind') == kind


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event['payload'] if isinstance(event.get('payload'), dict) else {}


def _iteration(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _usage_events(events: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int | None, str | None]]:
    '''Each token_usage event with its iteration and where it came from.

    The iteration is the event's own, else the last one seen on an earlier event of the stream (``ordem dos eventos``),
    else None: an event with no iteration known is never assigned one.
    '''
    out = []
    current = None
    for event in events:
        if isinstance(event, dict) and event.get('schema') == SCHEMA:
            own = _iteration(event.get('iteration'))
            if _is_event(event, 'token_usage'):
                if own is not None:
                    out.append((event, own, 'evento'))
                else:
                    out.append((event, current, 'ordem dos eventos' if current is not None else None))
            if own is not None:
                current = own
    return out


def _group(events: list[dict[str, Any]], prices: dict[str, Any] | None, key: Any, source: str | None) -> dict[str, Any]:
    tokens_in = tokens_out = 0
    for event in events:
        tokens_in += budget._number(_payload(event).get('input_tokens')) or 0
        tokens_out += budget._number(_payload(event).get('output_tokens')) or 0
    cost = budget.cost_estimate(events, prices)
    total = tokens_in + tokens_out
    return {'key': key, 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'tokens': total or None,
            'tokens_proof_kind': 'medido', 'cost_usd': cost['usd'], 'cost_state': cost['state'],
            'proof_kind': 'estimado', 'reason': cost['reason'], 'source': source}


def _tokens_summary(usage: list[tuple[dict[str, Any], int | None, str | None]]) -> dict[str, Any]:
    total = 0
    for event, _, _ in usage:
        total += (budget._number(_payload(event).get('input_tokens')) or 0) + (budget._number(_payload(event).get('output_tokens')) or 0)
    row: dict[str, Any] = {'total': total or None, 'state': 'PASS' if total else 'UNVERIFIED', 'proof_kind': 'medido',
                           'reason': None}
    if not total:
        row['reason'] = ('tokens do provedor não medidos: o registro do worker traz 0 ou null (sem contagem do provedor)'
                         if usage else 'tokens do provedor não medidos: nenhum token_usage no run')
    return row


def breakdown(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''Tokens and estimated cost per phase, lane, model, task and iteration, each in first-seen order (iterations ascending).'''
    usage = _usage_events(list(events))
    keys = {'by_phase': lambda e, i: _text(e.get('phase')), 'by_lane': lambda e, i: _text(e.get('lane')),
            'by_model': lambda e, i: _text(_payload(e).get('model')), 'by_task': lambda e, i: _text(e.get('task_id')),
            'by_iteration': lambda e, i: i}
    out: dict[str, Any] = {}
    for name, pick in keys.items():
        groups: dict[Any, list[tuple[dict[str, Any], str | None]]] = {}
        for event, iteration, source in usage:
            groups.setdefault(pick(event, iteration), []).append((event, source))
        found = []
        for key, members in groups.items():
            sources = {source for _, source in members}
            source = None if None in sources else ('ordem dos eventos' if 'ordem dos eventos' in sources else 'evento')
            found.append(_group([event for event, _ in members], prices, key, source if name == 'by_iteration' else None))
        if name == 'by_iteration':
            found.sort(key=lambda row: (row['key'] is None, row['key'] if row['key'] is not None else 0))
        out[name] = found
    out['tokens'] = _tokens_summary(usage)
    return out


NO_SLOTS = 'slots não medidos: nenhum evento de slot no stream do run'
NO_LEASE = 'worker_claimed sem lease_id'
NO_CLAIMS = 'nenhum worker_claimed no run: instâncias, slots e leases não medidos'


def agent_map(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    '''Claims, tasks and leases per lane from the worker_claimed events; slots have no event and stay UNVERIFIED.'''
    lanes: dict[str | None, dict[str, Any]] = {}
    for event in events:
        if not _is_event(event, 'worker_claimed'):
            continue
        lane = _text(event.get('lane'))
        row = lanes.setdefault(lane, {'key': lane, 'claims': 0, 'tasks': [], 'lease_ids': [], 'branches': [],
                                      'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None})
        row['claims'] += 1
        for field, value in (('tasks', _text(event.get('task_id'))), ('lease_ids', _text(_payload(event).get('lease_id'))),
                             ('branches', _text(_payload(event).get('branch')))):
            if value and value not in row[field]:
                row[field].append(value)
    for row in lanes.values():
        row['lease_reason'] = None if row['lease_ids'] else NO_LEASE
    found = list(lanes.values())
    return {'state': 'PASS' if found else 'UNVERIFIED', 'reason': None if found else NO_CLAIMS, 'lanes': found,
            'slots': {'state': 'UNVERIFIED', 'reason': NO_SLOTS}}


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
