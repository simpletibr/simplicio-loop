'''Langfuse view of one run for the Live dashboard (issue #1610).

Read only, local only: the route that serves this never opens a socket to Langfuse and never reads a credential, so a
Langfuse outage cannot stall the panel and no key can reach the browser. Everything comes from files:

* ``langfuse_enabled`` and ``langfuse_host`` from ``.simplicio-loop/loop.toml`` of the default branch (read with ``git show``;
  the clone's copy is a file a plan can edit), checked by the exporter's own ``load_config`` (https, or http for loopback).
* The exporter's outbox, dead letters and ledger under ``.simplicio-loop/langfuse/``: the chip and the queue size.
* The run's execution report and events, mapped by the exporter's own ``plan``: the gate scores and tokens the loop holds
  now, compared with the digests the ledger recorded when the server accepted them.

Off (the default) answers only the chip. See ``docs/LANGFUSE.md``.
'''
from __future__ import annotations

import json
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

from simplicio_loop import dashboard_events
from simplicio_loop.langfuse_export.config import load_config
from simplicio_loop.langfuse_export.exporter import langfuse_dir
from simplicio_loop.langfuse_export.ids import span_id, trace_id
from simplicio_loop.langfuse_export.mapping import TYPE_KEY, plan
from simplicio_loop.langfuse_export.queue import Ledger, Outbox, content_hash
from simplicio_loop.langfuse_export.redact import scrub
from simplicio_loop.wave_worktree import default_branch_commit

SCHEMA = 'simplicio.dashboard-langfuse/v1'
LOOP_TOML = '.simplicio-loop/loop.toml'
LATE_WINDOWS = 2  # the oldest queued item is late once it has waited this many batch windows
GIT_TIMEOUT_SECONDS = 10
USAGE_KEY = 'langfuse.observation.usage_details'
COST_REASON = 'o exportador não envia custo; o Langfuse o calcula pelo modelo e pelos tokens'
SEEN, DIVERGES, QUEUED, NOT_SENT = 'igual', 'diverge', 'na fila', 'não enviado'


def _chip(state: str, label: str, reason: str | None = None) -> dict[str, Any]:
    return {'state': state, 'label': label, 'reason': reason}


def _off() -> dict[str, Any]:
    return {'schema': SCHEMA, 'chip': _chip('off', 'desligado')}


def _unverified(reason: str) -> dict[str, Any]:
    return {'state': 'UNVERIFIED', 'reason': reason, 'gates': [], 'tokens': None,
            'cost': {'state': 'UNVERIFIED', 'reason': COST_REASON}}


def _default_branch_table(repo: str) -> dict[str, Any]:
    '''loop.toml as committed on the default branch; empty when the branch has none (the exporter is then off).'''
    sha = default_branch_commit(repo, timeout=GIT_TIMEOUT_SECONDS)
    if not sha:
        return {}
    try:
        shown = subprocess.run(['git', '-C', repo, 'show', '%s:%s' % (sha, LOOP_TOML)], capture_output=True, text=True,
                               timeout=GIT_TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return {}
    return tomllib.loads(shown.stdout) if shown.returncode == 0 else {}


def _load_report(repo: str, run_id: str) -> tuple[dict[str, Any] | None, str]:
    path = Path(repo) / '.simplicio-loop' / 'runtime' / 'execution-reports' / ('%s.json' % Path(run_id).name)
    if not path.is_file():
        return None, 'sem execution report deste run'
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None, 'execution report ilegível'
    return (report, '') if isinstance(report, dict) else (None, 'execution report ilegível')


def _enqueued_at(name: str) -> float | None:
    '''Outbox files are named ``<time_ns, 20 digits>-<id>.<kind>.json``.'''
    stamp = name[:20]
    return int(stamp) / 1e9 if stamp.isdigit() else None


def _minutes(seconds: float) -> int:
    return max(1, int(seconds // 60))


def _report_start(report: dict[str, Any] | None) -> float | None:
    if report is None:
        return None
    for key in ('finished_at_unix', 'started_at_unix'):
        value = report.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _status(ledger: Ledger, key: str, digest: str) -> str:
    sent = ledger.sent.get(key)
    if sent == digest:
        return SEEN
    if sent is not None:
        return DIVERGES
    return QUEUED if ledger.pending.get(key) == digest else NOT_SENT


def _usage(span: dict[str, Any]) -> dict[str, int]:
    usage = json.loads(span['attributes'].get(USAGE_KEY) or '{}')
    return {'input': int(usage.get('input', 0)), 'output': int(usage.get('output', 0))}


def _loop_tokens(report: dict[str, Any]) -> dict[str, int] | None:
    '''Measured tokens summed straight from the report: the loop's own number, not the mapped one.'''
    total, measured = {'input': 0, 'output': 0}, False
    for task in report.get('tasks') or []:
        tokens = task.get('tokens') or {}
        if tokens.get('source') != 'cli_measured':
            continue
        measured = True
        total['input'] += int(tokens.get('tokens_in') or 0)
        total['output'] += int(tokens.get('tokens_out') or 0)
    return total if measured else None


def _tokens(report: dict[str, Any], spans: list[dict[str, Any]], ledger: Ledger) -> dict[str, Any] | None:
    loop = _loop_tokens(report)
    if loop is None:
        return None
    generations = [span for span in spans if span['attributes'].get(TYPE_KEY) == 'generation']
    states = [_status(ledger, span['span_id'], content_hash(span)) for span in generations]
    seen = [_usage(span) for span, state in zip(generations, states) if state == SEEN]
    langfuse = {'input': sum(u['input'] for u in seen), 'output': sum(u['output'] for u in seen)} if seen else None
    diverge = DIVERGES in states or (bool(states) and all(s == SEEN for s in states) and langfuse != loop)
    return {'loop': loop, 'langfuse': langfuse, 'diverge': diverge}


def _compare(ref: dict[str, Any], batch_capture: bool, ledger: Ledger, report: dict[str, Any] | None,
             why: str) -> dict[str, Any]:
    if report is None:
        return _unverified(why)
    events_module = dashboard_events.load()
    if events_module is None:
        return _unverified('emissor de eventos do painel indisponível')
    events = list(events_module.read_live_events(str(ref['run_dir'])))
    try:
        shape = plan(report, events, capture_content=batch_capture)
        tokens = _tokens(report, scrub(shape.spans), ledger)
    except (KeyError, TypeError, ValueError):
        return _unverified('execution report inválido')
    gates = []
    for score in scrub(shape.scores):
        gates.append({'name': score['metadata']['gate'], 'passed': score['value'] == 1,
                      'langfuse': _status(ledger, score['id'], content_hash(score))})
    diverge = any(g['langfuse'] == DIVERGES for g in gates) or bool(tokens and tokens['diverge'])
    return {'state': 'DIVERGE' if diverge else 'OK', 'reason': None, 'gates': gates, 'tokens': tokens,
            'cost': {'state': 'UNVERIFIED', 'reason': COST_REASON}}


def _failed(run_id: str, reason: str, queue: int = 0) -> dict[str, Any]:
    return {'schema': SCHEMA, 'chip': _chip('error', 'erro', reason), 'queue': queue,
            'trace': {'id': trace_id(run_id), 'url': None, 'exported': False}, 'compare': _unverified(reason)}


def panel(ref: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    '''The payload of ``GET /api/runs/<id>/langfuse`` for the run ``ref`` (see the route in ``server.py``).'''
    now = time.time() if now is None else now
    repo, run_id = str(ref['repo']), str(ref['run_id'])
    try:
        table = _default_branch_table(repo)
    except tomllib.TOMLDecodeError:
        return _failed(run_id, 'loop.toml da branch padrão ilegível')
    if table.get('langfuse_enabled', False) is False:
        return _off()
    try:
        config = load_config(table, {})  # the loop.toml alone: the exporter's environment is not this process's
    except (TypeError, ValueError) as error:
        return _failed(run_id, str(error))
    base = langfuse_dir(Path(repo))
    try:
        queued = Outbox(base / 'queue', base / 'dead').pending()
        dead = len(list((base / 'dead').glob('*.json'))) if (base / 'dead').is_dir() else 0
        ledger = Ledger(base / 'ledger.json')
    except (OSError, ValueError):
        return _failed(run_id, 'estado do exportador ilegível')
    report, why = _load_report(repo, run_id)
    root = span_id(run_id, 'run')
    exported = root in ledger.sent
    waiting = [t for t in (_enqueued_at(item.path.name) for item in queued) if t is not None]
    late_after = LATE_WINDOWS * config.batch_seconds
    stuck = _report_start(report)
    unseen = not any(root in table for table in (ledger.sent, ledger.pending, ledger.rejected))
    if dead:
        chip = _chip('error', 'erro', '%d requisição(ões) recusada(s) em dead/' % dead)
    elif waiting and now - min(waiting) >= late_after:
        chip = _chip('late', 'atrasado %d min' % _minutes(now - min(waiting)))
    elif unseen and stuck is not None and now - stuck >= late_after:
        chip = _chip('late', 'atrasado %d min' % _minutes(now - stuck))
    elif queued:
        chip = _chip('sending', 'enviando')
    else:
        chip = _chip('ok', 'em dia')
    tid = trace_id(run_id)
    return {'schema': SCHEMA, 'chip': chip, 'queue': len(queued),
            'trace': {'id': tid, 'url': '%s/trace/%s' % (config.host, tid), 'exported': exported},
            'compare': _compare(ref, config.capture_content, ledger, report, why)}
