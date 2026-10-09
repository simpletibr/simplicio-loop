'''Per-stage agents, tokens and cost for the Simplicio Live dashboard (issue #1404).

One row per (stage, model) read from the token_usage events. The model and the tokens are measured; the role and the
effort are the model-roles table's default for that model, not an observation of the agent that ran. The cost goes
through budget.cost_estimate, so a stage's cost and the run's cost share one price path. Every cost is an estimate
and carries proof_kind "estimado". A model the table does not list gets no role and an UNVERIFIED cost with the reason.

The breakdown (issue #1550) groups the same token_usage events by phase, lane, model, task and iteration, and the agent
map groups the worker_claimed events by lane. Tokens are measured (proof_kind "medido"); a cost is always an estimate.
The runner records 0 or null for the provider tokens of a worker run, so those tokens, and the cost built on them, stay
UNVERIFIED with the reason: nothing is invented. The event stream has no slot event, so slots are UNVERIFIED too.

The route is polled every 3 s, so the reply is bounded and cheap (issue #1550, post-merge audit of #1556): the token_usage
events are tallied in ONE pass, every dimension keeps its TOP_N groups plus one aggregate row (``others`` = how many groups it
folds), names are cut to NAME_MAX characters, and run_view() memoizes the view of an unchanged run by its events-file stat.
'''
from __future__ import annotations

import heapq
import json
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Iterable

from simplicio_loop import dashboard_events, model_roles
from simplicio_loop.dashboard import budget

SCHEMA = 'simplicio.dashboard-event/v1'
VIEW_SCHEMA = 'simplicio.dashboard-stage-agents/v1'
TOP_N = budget.TOP_N
NAME_MAX = 120
CACHE_MAX = 16
DIMENSIONS = ('by_phase', 'by_lane', 'by_model', 'by_task', 'by_iteration')


def view(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''The GET /api/runs/<id>/stage-agents body: the per-stage rows plus the run's own cost estimate.'''
    events = events if isinstance(events, list) else list(events)
    tally = _tally(events)
    return {'schema': VIEW_SCHEMA, 'rows': _stage_rows(tally, prices), 'cost': _cost(tally['run'], prices),
            'breakdown': _breakdown(tally, prices), 'agent_map': agent_map(events)}


def _is_event(event: Any, kind: str) -> bool:
    return isinstance(event, dict) and event.get('schema') == SCHEMA and event.get('kind') == kind


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _name(value: Any) -> Any:
    '''A name as shown: at most NAME_MAX characters, so one huge name cannot inflate the reply.'''
    return value[:NAME_MAX - 1] + '\u2026' if isinstance(value, str) and len(value) > NAME_MAX else value


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return event['payload'] if isinstance(event.get('payload'), dict) else {}


def _iteration(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _leaves(events: list[dict[str, Any]]) -> tuple[dict[tuple, list], int]:
    '''The token_usage events summed per (phase, lane, model, task, iteration, source): the only pass over the events.

    Also the number of events that carried a count the budget reading refuses (NaN, Infinity, negative, a string, above
    budget.MAX_NUMBER): that count is not summed, and the event is reported as ignored.

    The iteration is the event's own, else the last one seen on an earlier event of the stream (``ordem dos eventos``),
    else None: an event with no iteration known is never assigned one. Leaves keep first-seen order.
    '''
    leaves: dict[tuple, list] = {}
    current = None
    ignored = 0
    for event in events:
        if not (isinstance(event, dict) and event.get('schema') == SCHEMA):
            continue
        own = _iteration(event.get('iteration'))
        if event.get('kind') == 'token_usage':
            payload = _payload(event)
            if own is not None:
                iteration, source = own, 'evento'
            else:
                iteration, source = current, ('ordem dos eventos' if current is not None else None)
            key = (_text(event.get('phase')), _text(event.get('lane')), _text(payload.get('model')), _text(event.get('task_id')),
                   iteration, source)
            raw_in, raw_out = payload.get('input_tokens'), payload.get('output_tokens')
            tokens_in, tokens_out = budget._number(raw_in), budget._number(raw_out)
            if (tokens_in is None and raw_in is not None) or (tokens_out is None and raw_out is not None):
                ignored += 1
            tokens_in, tokens_out = tokens_in or 0, tokens_out or 0
            leaf = leaves.get(key)
            if leaf is None:
                leaves[key] = [tokens_in, tokens_out]
            else:
                leaf[0] += tokens_in
                leaf[1] += tokens_out
        if own is not None:
            current = own
    return leaves, ignored


_SOURCE_BITS = {None: 1, 'ordem dos eventos': 2, 'evento': 4}


def _add(groups: dict[Any, list], key: Any, model: str, tokens_in: Any, tokens_out: Any, source: int = 0) -> None:
    '''Add tokens to the group's accumulator [in, out, {model: [in, out]}, source bits]; only a measured count is priced.'''
    acc = groups.get(key)
    if acc is None:
        groups[key] = [tokens_in, tokens_out, {model: [tokens_in, tokens_out]} if tokens_in + tokens_out else {}, source]
        return
    acc[0] += tokens_in
    acc[1] += tokens_out
    if tokens_in + tokens_out:
        per = acc[2].get(model)
        if per is None:
            acc[2][model] = [tokens_in, tokens_out]
        else:
            per[0] += tokens_in
            per[1] += tokens_out
    acc[3] |= source


def _tally(events: list[dict[str, Any]]) -> dict[str, Any]:
    '''Fold the leaves into one accumulator per group of every dimension and per (phase, model) stage.'''
    leaves, ignored = _leaves(events)
    dims: dict[str, dict[Any, list]] = {name: {} for name in DIMENSIONS}
    stages: dict[Any, list] = {}
    by_phase, by_lane, by_model, by_task, by_iteration = (dims[name] for name in DIMENSIONS)
    total = 0
    for (phase, lane, model, task, iteration, source), (tokens_in, tokens_out) in leaves.items():
        name = model or ''
        total += tokens_in + tokens_out
        _add(by_phase, phase, name, tokens_in, tokens_out)
        _add(by_lane, lane, name, tokens_in, tokens_out)
        _add(by_model, model, name, tokens_in, tokens_out)
        _add(by_task, task, name, tokens_in, tokens_out)
        _add(by_iteration, iteration, name, tokens_in, tokens_out, _SOURCE_BITS[source])
        _add(stages, (phase, model), name, tokens_in, tokens_out)
    return {'dims': dims, 'stages': stages, 'run': _merge(by_model, list(by_model))[2], 'total': total, 'seen': bool(leaves),
            'ignored': ignored}


def _cost(models: dict[str, list], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''budget.cost_estimate over one synthetic event per model bucket, so a group is priced from its sums, not its events.'''
    return budget.cost_estimate([{'schema': SCHEMA, 'kind': 'token_usage',
                                  'payload': {'model': _name(model), 'input_tokens': i, 'output_tokens': o}}
                                 for model, (i, o) in models.items()], prices)


def _row(key: Any, acc: list, prices: dict[str, Any] | None, source: str | None, others: int | None = None) -> dict[str, Any]:
    tokens_in, tokens_out = acc[0], acc[1]
    cost = _cost(acc[2], prices)
    row = {'key': _name(key), 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'tokens': (tokens_in + tokens_out) or None,
           'tokens_proof_kind': 'medido', 'cost_usd': cost['usd'], 'cost_state': cost['state'],
           'proof_kind': 'estimado', 'reason': cost['reason'], 'source': source}
    if others:
        row['others'] = others
    return row


def _source(acc: list) -> str | None:
    bits = acc[3]
    return None if bits & _SOURCE_BITS[None] else ('ordem dos eventos' if bits & _SOURCE_BITS['ordem dos eventos'] else 'evento')


def _split(groups: dict[Any, list], recent: bool = False) -> tuple[list, list]:
    '''(kept keys, folded keys): the TOP_N groups with most tokens (the TOP_N latest iterations when ``recent``), first-seen order.'''
    keys = list(groups)
    if len(keys) <= TOP_N:
        return keys, []
    if recent:
        top = set(heapq.nlargest(TOP_N, (key for key in keys if key is not None)))
    else:
        top = set(heapq.nlargest(TOP_N, keys, key=lambda key: groups[key][0] + groups[key][1]))
    return [key for key in keys if key in top], [key for key in keys if key not in top]


def _merge(groups: dict[Any, list], keys: list) -> list:
    merged: list = [0, 0, {}, 0]
    for key in keys:
        acc = groups[key]
        merged[0] += acc[0]
        merged[1] += acc[1]
        for model, (tokens_in, tokens_out) in acc[2].items():
            per = merged[2].setdefault(model, [0, 0])
            per[0] += tokens_in
            per[1] += tokens_out
    return merged


def _tokens_summary(total: int, seen: bool, ignored: int = 0) -> dict[str, Any]:
    row: dict[str, Any] = {'total': total or None, 'state': 'PASS' if total else 'UNVERIFIED', 'proof_kind': 'medido',
                           'reason': None}
    note = ('%d evento(s) com contagem de tokens n\u00e3o finita, negativa ou acima de %.0e ignorado(s)'
            % (ignored, budget.MAX_NUMBER)) if ignored else None
    if not total:
        row['reason'] = ('tokens do provedor n\u00e3o medidos: o registro do worker traz 0 ou null (sem contagem do provedor)'
                         if seen else 'tokens do provedor n\u00e3o medidos: nenhum token_usage no run')
        if note:
            row['reason'] += '; ' + note
    if note:
        row['ignored'] = ignored
        if total:
            row['ignored_reason'] = note
    return row


def _breakdown(tally: dict[str, Any], prices: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, groups in tally['dims'].items():
        iteration = name == 'by_iteration'
        kept, rest = _split(groups, recent=iteration)
        if iteration:
            kept.sort(key=lambda key: (key is None, key if key is not None else 0))
        found = [_row(key, groups[key], prices, _source(groups[key]) if iteration else None) for key in kept]
        if rest:
            found.append(_row(None, _merge(groups, rest), prices, None, others=len(rest)))
        out[name] = found
    out['tokens'] = _tokens_summary(tally['total'], tally['seen'], tally['ignored'])
    return out


def breakdown(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> dict[str, Any]:
    '''Tokens and estimated cost per phase, lane, model, task and iteration: TOP_N rows each plus one "others" row.'''
    return _breakdown(_tally(events if isinstance(events, list) else list(events)), prices)


NO_SLOTS = 'slots não medidos: nenhum evento de slot no stream do run'
NO_LEASE = 'worker_claimed sem lease_id'
NO_CLAIMS = 'nenhum worker_claimed no run: instâncias, slots e leases não medidos'


def agent_map(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    '''Claims, tasks and leases per lane from the worker_claimed events; slots have no event and stay UNVERIFIED.

    TOP_N lanes (the most claims) plus one "others" row. Each list keeps a lane's first TOP_N distinct values and ``*_total``
    is the distinct count, so a lane with thousands of tasks stays small and every claim is deduplicated in O(1).'''
    lanes: dict[str | None, dict[str, Any]] = {}
    seen: set[tuple[str | None, str, str]] = set()
    for event in events:
        if not _is_event(event, 'worker_claimed'):
            continue
        lane = _text(event.get('lane'))
        row = lanes.get(lane)
        if row is None:
            row = lanes[lane] = {'key': lane, 'claims': 0, 'tasks': [], 'lease_ids': [], 'branches': [], 'tasks_total': 0,
                                 'lease_ids_total': 0, 'branches_total': 0, 'state': 'PASS', 'proof_kind': 'medido',
                                 'lease_reason': None}
        row['claims'] += 1
        payload = _payload(event)
        for field, value in (('tasks', _text(event.get('task_id'))), ('lease_ids', _text(payload.get('lease_id'))),
                             ('branches', _text(payload.get('branch')))):
            if value is not None and (lane, field, value) not in seen:
                seen.add((lane, field, value))
                row[field + '_total'] += 1
                if len(row[field]) < TOP_N:
                    row[field].append(_name(value))
    kept, rest = _split_lanes(lanes)
    found = []
    for key in kept:
        row = lanes[key]
        row['key'] = _name(key)
        row['lease_reason'] = None if row['lease_ids'] else NO_LEASE
        found.append(row)
    if rest:
        found.append({'key': None, 'claims': sum(lanes[key]['claims'] for key in rest), 'tasks': [], 'lease_ids': [],
                      'branches': [], 'state': 'PASS', 'proof_kind': 'medido', 'lease_reason': None, 'others': len(rest)})
    return {'state': 'PASS' if found else 'UNVERIFIED', 'reason': None if found else NO_CLAIMS, 'lanes': found,
            'slots': {'state': 'UNVERIFIED', 'reason': NO_SLOTS}}


def _split_lanes(lanes: dict[Any, dict[str, Any]]) -> tuple[list, list]:
    keys = list(lanes)
    if len(keys) <= TOP_N:
        return keys, []
    top = set(heapq.nlargest(TOP_N, keys, key=lambda key: lanes[key]['claims']))
    return [key for key in keys if key in top], [key for key in keys if key not in top]


def _stage_rows(tally: dict[str, Any], prices: dict[str, Any] | None) -> list[dict[str, Any]]:
    stages = tally['stages']
    kept, rest = _split(stages)
    out = []
    for key in kept:
        phase, model = key
        acc = stages[key]
        cost = _cost(acc[2], prices)
        placed = model_roles.role_of(model) if model else None
        reason = cost['reason'] or (None if placed else 'modelo sem papel na tabela de papéis')
        out.append({'phase': _name(phase), 'role': placed['role'] if placed else None,
                    'effort': placed['effort'] if placed else None, 'model': _name(model),
                    'tokens_in': acc[0], 'tokens_out': acc[1], 'cost_usd': cost['usd'],
                    'cost_state': cost['state'], 'proof_kind': 'estimado', 'reason': reason})
    if rest:
        merged = _merge(stages, rest)
        cost = _cost(merged[2], prices)
        out.append({'phase': None, 'role': None, 'effort': None, 'model': None, 'tokens_in': merged[0],
                    'tokens_out': merged[1], 'cost_usd': cost['usd'], 'cost_state': cost['state'],
                    'proof_kind': 'estimado', 'reason': cost['reason'], 'others': len(rest)})
    return out


def rows(events: Iterable[dict[str, Any]], prices: dict[str, Any] | None) -> list[dict[str, Any]]:
    '''One row per (stage, model), in first-seen order, TOP_N plus one "others" row. Empty when no token_usage was measured.'''
    return _stage_rows(_tally(events if isinstance(events, list) else list(events)), prices)


# --- the memoized view of one run -----------------------------------------------------------------------------------------
_STREAM_FILE = re.compile(r'events\.jsonl(?:\.\d+)?')
WAIT_TIMEOUT_S = 10.0  # how long a poller waits for a computation of its run before it serves the last view or gives up
RETRY_AFTER_S = 1


class ViewBusy(Exception):
    '''A computation of this run did not finish within WAIT_TIMEOUT_S and there is no earlier view to serve.'''

    def __init__(self, retry_after: int = RETRY_AFTER_S) -> None:
        super().__init__('stage-agents view busy; retry after %d s' % retry_after)
        self.retry_after = retry_after


class _Flight:
    '''One computation in progress. ``began`` (monotonic) is taken before ``stamp``, so every request that arrived before ``began``
    is older than the stamp: whatever it could see on disk, the stamp, and the events read after it, include.'''
    __slots__ = ('began', 'stamp', 'prices', 'done', 'view', 'error')

    def __init__(self, prices: str, stamp: Any, began: float) -> None:
        self.began, self.stamp, self.prices = began, stamp, prices
        self.done = threading.Event()
        self.view: dict[str, Any] | None = None
        self.error: BaseException | None = None


class _Entry:
    __slots__ = ('mutex', 'stamp', 'prices', 'view', 'computed', 'flight')

    def __init__(self) -> None:
        self.mutex = threading.Lock()  # held for bookkeeping only, never while the events are read
        self.stamp: Any = None
        self.prices: str | None = None
        self.view: dict[str, Any] | None = None
        self.computed = 0.0  # monotonic time the cached view was finished
        self.flight: _Flight | None = None


_CACHE: OrderedDict[str, _Entry] = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _stamp(run_dir: Any) -> tuple | None:
    '''(name, inode, size, mtime, ctime) of the run's live event files, or None when it has no live stream (nothing to key on).

    The ctime cannot be set from user space, so a same-size rewrite that restores the mtime still changes the key.'''
    try:
        with os.scandir(run_dir) as entries:
            stats = [(e.name, e.stat()) for e in entries if _STREAM_FILE.fullmatch(e.name) and e.is_file()]
        files = sorted((name, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) for name, st in stats)
    except OSError:
        return None
    return tuple(files) if any(name == 'events.jsonl' for name, *_ in files) else None


def _stale(entry: _Entry) -> dict[str, Any]:
    '''The last good view as a copy flagged ``stale`` with its age in seconds, or ViewBusy when the run has none.'''
    with entry.mutex:
        cached, computed = entry.view, entry.computed
    if cached is None:
        raise ViewBusy()
    return {**cached, 'stale': True, 'age_s': round(time.monotonic() - computed, 3)}


def run_view(run_dir: Any, prices: dict[str, Any] | None, read: Any = None) -> dict[str, Any]:
    '''view() of a run's events, memoized per run directory while the live event files are unchanged.

    The key is the run dir plus the stat of its events files (name, inode, size, mtime, ctime) and the price table, taken before
    the events are read, so a file that grows during the read is read again on the next poll. A run with no live stream, or one
    rebuilt from other files (``derived``), is never cached. The cache holds CACHE_MAX runs; the returned dict is shared, so
    callers must not mutate it.

    One computation per run runs at a time and the pollers coalesce on it (no lock is held while the events are read). A poller
    may take a computation's result when its stamp is the poller's own, or when the computation took its stamp after the
    poller arrived (it then holds everything the poller could have seen); a poller that arrives later, with the files changed
    since, waits for the computation in flight and then starts or joins a newer one. Freshness is therefore never weaker than
    "an append finished before the request began is in the reply", while N pollers of a hot run cost two computations, not N.

    A poller waits at most WAIT_TIMEOUT_S for a computation. After that it gets the last good view as a copy with ``stale: true``
    and ``age_s``, or ViewBusy (the route answers 503 with Retry-After) when the run has none.'''
    arrived = time.monotonic()
    read = read or dashboard_events.read_events
    key = os.fspath(run_dir)
    with _CACHE_LOCK:
        entry = _CACHE.pop(key, None) or _Entry()
        _CACHE[key] = entry
        while len(_CACHE) > CACHE_MAX:
            _CACHE.popitem(last=False)
    fingerprint = json.dumps(prices, sort_keys=True, default=str)
    deadline = arrived + WAIT_TIMEOUT_S
    while True:
        seen = _stamp(run_dir)  # this request's own look at the files, after it arrived
        with entry.mutex:
            if seen is not None and entry.view is not None and entry.stamp == seen and entry.prices == fingerprint:
                return entry.view
            flight = entry.flight
            if flight is None:
                began = time.monotonic()
                flight = entry.flight = _Flight(fingerprint, _stamp(run_dir), began)
                lead = True
            else:
                lead = False
        if lead:
            return _compute(entry, flight, run_dir, prices, read)
        entitled = flight.prices == fingerprint and (flight.began >= arrived or (seen is not None and flight.stamp == seen))
        if not flight.done.wait(max(0.0, deadline - time.monotonic())):
            return _stale(entry)
        if entitled:
            if flight.error is not None:
                raise flight.error
            if flight.view is not None:
                return flight.view


def _compute(entry: _Entry, flight: _Flight, run_dir: Any, prices: dict[str, Any] | None, read: Any) -> dict[str, Any]:
    try:
        events = read(run_dir)
        result = view(events, prices)
        live = flight.stamp is not None and bool(events) and not events[0].get('derived')
        with entry.mutex:
            if live:
                entry.stamp, entry.prices, entry.view, entry.computed = flight.stamp, flight.prices, result, time.monotonic()
            else:
                entry.stamp, entry.prices, entry.view = None, None, None
        flight.view = result
        return result
    except BaseException as exc:
        flight.error = exc
        raise
    finally:
        with entry.mutex:
            entry.flight = None
        flight.done.set()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def cache_size() -> int:
    with _CACHE_LOCK:
        return len(_CACHE)
