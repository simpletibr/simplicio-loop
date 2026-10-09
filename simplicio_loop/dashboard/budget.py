'''Run budget reading for the Simplicio Live dashboard (issue #1404).

The declared limits come from the run's ``task-contract.json`` (sum over tasks of ``routing.budget``). Usage comes from
the ``token_usage`` and ``cost_sample`` events and from the event clock. The projection extrapolates usage by phase
progress, so it is an estimate and always carries ``proof_kind: estimado``. A figure with no declared limit, no
measured usage or no progress to extrapolate from is UNVERIFIED, never a pass.
'''
from __future__ import annotations

import heapq
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from simplicio_loop.progress import PHASES

KEYS = ('tokens', 'usd', 'seconds')
SCHEMA = 'simplicio.dashboard-event/v1'
MAX_CONTRACT_BYTES = 1_000_000
TOP_N = 20
# A count (tokens, USD, seconds) above this is not a measurement: no run spends 10**15 of anything, and the cap keeps every
# sum finite (two events of 1e308 would add up to Infinity, which is not JSON).
MAX_NUMBER = 10 ** 15


def _number(value: Any) -> float | int | None:
    '''The value when it is a finite, non-negative number up to MAX_NUMBER, else None (a bool, a string, NaN, Infinity, too big).'''
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)) or value < 0:
        return None
    return value if value <= MAX_NUMBER else None


def declared(run_dir: str | Path) -> dict[str, float | int | None]:
    '''Declared limits summed over the tasks; None for a dimension no task declares.'''
    totals: dict[str, float | int | None] = {key: None for key in KEYS}
    path = Path(run_dir) / 'task-contract.json'
    try:
        if path.stat().st_size > MAX_CONTRACT_BYTES:
            return totals
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return totals
    tasks = data.get('tasks') if isinstance(data, dict) else None
    for task in tasks if isinstance(tasks, list) else []:
        routing = task.get('routing') if isinstance(task, dict) else None
        limits = routing.get('budget') if isinstance(routing, dict) else None
        if not isinstance(limits, dict):
            continue
        for key in KEYS:
            value = _number(limits.get(key))
            if value is not None:
                totals[key] = (totals[key] or 0) + value
    return totals


def _iteration(value: Any) -> int | None:
    '''The iteration of an event (an integer >= 0), else None: a bool or a string is not an iteration.'''
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _task(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _bump(group: dict[str, int], key: Any, amount: int) -> None:
    if isinstance(key, str) and key:
        group[key] = group.get(key, 0) + amount


def _token_events(events: Iterable[dict[str, Any]]) -> Iterator[tuple[dict[str, Any], str, int, int, str | None, int | None, str | None]]:
    '''Each token_usage event with a count as (event, model, input, output, task_id, iteration, lane); a count-less one is skipped.'''
    for event in events:
        if not isinstance(event, dict) or event.get('schema') != SCHEMA or event.get('kind') != 'token_usage':
            continue
        payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
        tokens_in, tokens_out = _number(payload.get('input_tokens')), _number(payload.get('output_tokens'))
        if not (tokens_in or 0) + (tokens_out or 0):
            continue
        model = payload.get('model') if isinstance(payload.get('model'), str) and payload.get('model') else ''
        lane = event.get('lane') if isinstance(event.get('lane'), str) and event.get('lane') else None
        yield event, model, tokens_in or 0, tokens_out or 0, _task(event.get('task_id')), _iteration(event.get('iteration')), lane


def usage(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    '''Tokens and USD summed from the producer events, grouped by phase, lane, model, task and iteration.

    The task and iteration groups come from the event envelope. Tokens whose event has no task (or no iteration) count in
    ``unattributed_tokens``, so the parts of each split add up to ``tokens``.
    '''
    events = list(events)
    tokens = 0
    usd = 0.0
    samples = 0
    cost_seen = False
    by_phase: dict[str, int] = {}
    by_lane: dict[str, int] = {}
    by_model: dict[str, int] = {}
    by_task: dict[str, int] = {}
    by_iteration: dict[str, int] = {}
    unattributed = {'task': 0, 'iteration': 0}
    for event in events:
        if isinstance(event, dict) and event.get('schema') == SCHEMA and event.get('kind') == 'cost_sample':
            payload = event.get('payload') if isinstance(event.get('payload'), dict) else {}
            value = _number(payload.get('usd'))
            if value is not None:
                usd += value
                cost_seen = True
    for event, model, tokens_in, tokens_out, task, iteration, lane in _token_events(events):
        amount = int(tokens_in + tokens_out)
        tokens += amount
        samples += 1
        _bump(by_phase, event.get('phase'), amount)
        _bump(by_lane, lane, amount)
        _bump(by_model, model, amount)
        if task is None:
            unattributed['task'] += amount
        else:
            _bump(by_task, task, amount)
        if iteration is None:
            unattributed['iteration'] += amount
        else:
            _bump(by_iteration, str(iteration), amount)
    return {'tokens': tokens if samples else None, 'usd': usd if cost_seen else None, 'samples': samples,
            'by_phase': by_phase, 'by_lane': by_lane, 'by_model': by_model, 'by_task': by_task,
            'by_iteration': by_iteration, 'unattributed_tokens': unattributed}


def price_for(models: dict[str, Any], model: str) -> dict[str, Any] | None:
    '''The longest table key that prefixes the model id, so a dated id takes its family's price.

    Same rule as priceFor in static/live/economy.js; the two must agree (tests/test_dashboard_economy_pricing_contract_unit.py).
    '''
    best = None
    for key in models:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return models[best] if best is not None else None


def cost_estimate(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''USD for the run: measured input/output tokens per model times the price table. Always an estimate.

    UNVERIFIED (with the reason) when no tokens were measured, the table is missing, or a model has no price. ``by_model``
    and ``by_task`` list at most TOP_N of the most expensive; with more models, ``others`` carries the model count, tokens and
    cost of the rest, and ``tasks`` counts every priced task. ``by_iteration`` lists the TOP_N most expensive iterations.
    ``unattributed_usd`` is the USD of the tokens whose event has no task or no iteration, so each split adds up to ``usd``.
    '''
    row: dict[str, Any] = {'usd': None, 'state': 'UNVERIFIED', 'proof_kind': 'estimado', 'reason': None,
                           'as_of': None, 'source_url': None, 'by_model': {}, 'by_task': {}, 'tasks': 0,
                           'by_iteration': {}, 'iterations': 0, 'unattributed_usd': {'task': None, 'iteration': None}}
    priced_events = list(_token_events(events))
    table = prices.get('models') if isinstance(prices, dict) and isinstance(prices.get('models'), dict) else None
    if isinstance(prices, dict):
        row['as_of'], row['source_url'] = prices.get('as_of'), prices.get('source_url')
    if not priced_events:
        row['reason'] = 'tokens não medidos: nenhum token_usage com contagem registrada pelo run'
        return row
    if table is None:
        row['reason'] = 'tabela de preços indisponível'
        return row
    per_model: dict[str, list[float]] = {}
    for _, model, tokens_in, tokens_out, _, _, _ in priced_events:
        totals = per_model.setdefault(model, [0, 0])
        totals[0] += tokens_in
        totals[1] += tokens_out
    rates: dict[str, tuple[float, float]] = {}
    for model in sorted(per_model):
        price = price_for(table, model)
        in_rate = _number(price.get('input_per_mtok')) if isinstance(price, dict) else None
        out_rate = _number(price.get('output_per_mtok')) if isinstance(price, dict) else None
        if in_rate is None or out_rate is None:
            row['reason'] = 'sem preço na tabela para o modelo %r' % (model or 'desconhecido')
            return row
        rates[model] = (in_rate, out_rate)

    def usd_of(model: str, tokens_in: float, tokens_out: float) -> float:
        return (tokens_in * rates[model][0] + tokens_out * rates[model][1]) / 1_000_000

    priced = [(model, usd_of(model, *per_model[model]), per_model[model][0], per_model[model][1]) for model in sorted(per_model)]
    total = 0.0
    for _, usd, _, _ in priced:
        total += usd
    row['usd'] = round(total, 6)
    row['state'] = 'ESTIMADO'
    # The reply stays small however many model ids the run used: the TOP_N most expensive models by name, and one ``others``
    # row with the tokens and cost of the rest, so that the listed parts add up to ``usd``.
    kept = priced if len(priced) <= TOP_N else sorted(heapq.nlargest(TOP_N, priced, key=lambda item: item[1]))
    row['by_model'] = {model: round(usd, 6) for model, usd, _, _ in kept}
    if len(kept) < len(priced):
        listed = {model for model, *_ in kept}
        rest = [item for item in priced if item[0] not in listed]
        tokens_in, tokens_out = sum(item[2] for item in rest), sum(item[3] for item in rest)
        row['others'] = {'models': len(rest), 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'tokens': tokens_in + tokens_out,
                         'usd': round(row['usd'] - sum(row['by_model'].values()), 6), 'state': 'ESTIMADO',
                         'proof_kind': 'estimado', 'reason': None}
    task_usd: dict[str, float] = {}
    iteration_usd: dict[str, float] = {}
    unattributed = {'task': 0.0, 'iteration': 0.0}
    for _, model, tokens_in, tokens_out, task, iteration, _ in priced_events:
        usd = usd_of(model, tokens_in, tokens_out)
        if task is None:
            unattributed['task'] += usd
        else:
            task_usd[task] = task_usd.get(task, 0.0) + usd
        if iteration is None:
            unattributed['iteration'] += usd
        else:
            iteration_usd[str(iteration)] = iteration_usd.get(str(iteration), 0.0) + usd
    row['tasks'] = len(task_usd)
    row['by_task'] = {task: round(usd, 6) for task, usd in heapq.nlargest(TOP_N, task_usd.items(), key=lambda item: item[1])}
    row['iterations'] = len(iteration_usd)
    row['by_iteration'] = {it: round(usd, 6) for it, usd in heapq.nlargest(TOP_N, iteration_usd.items(), key=lambda item: item[1])}
    row['unattributed_usd'] = {key: round(value, 6) for key, value in unattributed.items()}
    return row


def _fraction(phase: str | None) -> float:
    if phase not in PHASES:
        return 0.0
    return PHASES.index(phase) / (len(PHASES) - 1)


def project(limit: float | int | None, used: float | int | None, phase: str | None) -> dict[str, Any]:
    '''One dimension: the limit, the measured use and the use extrapolated to the end of the run.'''
    row: dict[str, Any] = {'limit': limit, 'used': used, 'projected': None, 'state': 'UNVERIFIED',
                           'proof_kind': 'estimado', 'reason': None}
    if limit is None:
        row['reason'] = 'nenhum limite declarado no contrato da tarefa'
    elif used is None:
        row['reason'] = 'uso não medido: nenhum produtor de token_usage escreve eventos'
    elif used > limit:
        row['state'] = 'EXCEEDED'
    else:
        fraction = _fraction(phase)
        if fraction <= 0:
            row['reason'] = 'sem progresso de fase para projetar'
        else:
            projected = round(used / fraction, 4)
            row['projected'] = projected
            row['state'] = 'PROJECTED_OVER' if projected > limit else 'OK'
    return row


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts[:-1] + '+00:00' if ts.endswith('Z') else ts)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def elapsed_s(events: list[dict[str, Any]]) -> float | None:
    '''Seconds between the first and the last event timestamp; None when fewer than two are readable.'''
    stamps = [stamp for stamp in (_parse(e.get('ts')) for e in events if isinstance(e, dict)) if stamp]
    if len(stamps) < 2:
        return None
    return (max(stamps) - min(stamps)).total_seconds()


def current_phase(events: Iterable[dict[str, Any]]) -> str | None:
    phase = None
    for event in events:
        if isinstance(event, dict) and event.get('kind') == 'phase_entered' and isinstance(event.get('phase'), str):
            phase = event['phase']
    return phase


def report(run_dir: str | Path, events: list[dict[str, Any]], prices: dict[str, Any] | None = None) -> dict[str, Any]:
    '''The budget panel payload for one run: limits, usage and one projection per dimension.'''
    limits = declared(run_dir)
    used = usage(events)
    phase = current_phase(events)
    measured = {'tokens': used['tokens'], 'usd': used['usd'], 'seconds': elapsed_s(events)}
    return {'phase': phase, 'limits': limits, 'usage': used, 'cost': cost_estimate(events, prices),
            'rows': {key: project(limits[key], measured[key], phase) for key in KEYS}}


COMPARE_FIELDS = ('duration_s', 'tokens', 'cost_usd', 'iterations')
COMPARE_WINDOW = 10


def compare(current: dict[str, Any], previous: list[dict[str, Any]]) -> dict[str, Any]:
    '''This run against the average of the last ten finished runs (history records, newest first).

    The current run and runs still running are skipped. A value no run measured is UNVERIFIED, never zero.
    '''
    window = [r for r in previous if r.get('run_id') != current.get('run_id') and r.get('verdict') != 'RUNNING'][:COMPARE_WINDOW]
    fields: dict[str, Any] = {}
    for key in COMPARE_FIELDS:
        values = [v for v in (_number(r.get(key)) for r in window) if v is not None]
        now = _number(current.get(key))
        row: dict[str, Any] = {'current': now, 'average': None, 'samples': len(values), 'delta_pct': None, 'state': 'UNVERIFIED'}
        if values and now is not None:
            average = sum(values) / len(values)
            row['average'] = average
            row['state'] = 'ESTIMADO'
            if average > 0:
                row['delta_pct'] = round((now - average) / average * 100, 1)
        fields[key] = row
    return {'runs': len(window), 'fields': fields}
