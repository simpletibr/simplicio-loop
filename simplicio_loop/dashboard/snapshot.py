'''Single-file HTML snapshot of one dashboard run (issue #1401, slice 3b).

The page is server-rendered with inline CSS only. It has no script, link, image, frame, url() or
import and no network address, so it opens offline and runs no code. Every value is escaped.
Run data comes from ``runs`` (already redacted). Events show only seq, ts, kind, phase and severity.
'''
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import runs
from simplicio_loop.dashboard_events import read_events

EVENT_LIMIT = 25
EVENT_FIELDS = ('seq', 'ts', 'kind', 'phase', 'severity')
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_CSS = ' '.join([
    ':root { color-scheme: light dark; --bg: #f7f7f5; --fg: #1d1d1b; --muted: #6b6b66; --line: #d8d8d2; --accent: #2f6f5e; }',
    '@media (prefers-color-scheme: dark) { :root { --bg: #161715; --fg: #ecece6; --muted: #9c9c94; --line: #3a3b37; --accent: #6fbf9f; } }',
    'body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; }',
    'main { max-width: 960px; margin: 0 auto; padding: 16px; }',
    'h1 { font-size: 1.4rem; margin: 8px 0; } h2 { font-size: 1.1rem; margin: 24px 0 8px; }',
    '.meta { color: var(--muted); } code { font-family: ui-monospace, monospace; overflow-wrap: anywhere; }',
    'dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }',
    'dt { color: var(--muted); } dd { margin: 0; overflow-wrap: anywhere; }',
    '.bar { height: 10px; background: var(--line); border-radius: 5px; overflow: hidden; margin: 6px 0; }',
    '.bar span { display: block; height: 100%; background: var(--accent); }',
    '.table-wrap { overflow-x: auto; } table { width: 100%; border-collapse: collapse; }',
    'th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }',
    'th { color: var(--muted); font-weight: 600; }',
])


class SnapshotError(Exception):
    '''No snapshot can be written: the watched repos hold no runs, or the run id is unknown.'''


def ranked_runs(repos: Any) -> list[tuple[runs.RunRef, dict[str, Any]]]:
    '''Every run under ``repos`` with its summary, newest ``updated_at`` first (shared with the CLI).'''
    rows = [(ref, runs.run_summary(ref)) for ref in runs.discover_runs(repos)]
    rows.sort(key=lambda row: (runs._parse_ts(row[1].get('updated_at')) or _EPOCH, row[1]['run_id']),
              reverse=True)
    return rows


def _esc(value: Any) -> str:
    return html.escape('' if value is None else str(value), quote=True)


def _row(values: list[Any], tag: str = 'td') -> str:
    return '<tr>' + ''.join('<%s>%s</%s>' % (tag, _esc(value), tag) for value in values) + '</tr>'


def _table(head: list[str], body: str) -> str:
    return ('<div class="table-wrap"><table><thead>' + _row(head, 'th') + '</thead><tbody>' + body
            + '</tbody></table></div>')


def _select(rows: list[tuple[runs.RunRef, dict[str, Any]]], run_id: str | None) -> runs.RunRef:
    if not rows:
        raise SnapshotError('no runs found under the watched repos')
    if run_id is None:
        return rows[0][0]
    for ref, _ in rows:
        if ref['run_id'] == run_id:
            return ref
    raise SnapshotError('run not found: %s' % run_id)


def _facts(summary: dict[str, Any], state: dict[str, Any]) -> str:
    percent = max(0, min(100, int(summary.get('percent') or 0)))
    bar = ('<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="%d">'
           '<span style="width:%d%%"></span></div>' % (percent, percent))
    facts = [
        ('Run', summary['run_id']),
        ('Status', summary.get('status')),
        ('Phase', summary.get('phase')),
        ('Goal', state.get('goal')),
        ('Repo', summary.get('repo')),
        ('Started', summary.get('started_at')),
        ('Updated', summary.get('updated_at')),
    ]
    items = ''.join('<dt>%s</dt><dd>%s</dd>' % (_esc(key), _esc(value) or '-') for key, value in facts)
    return '<dl>' + items + '</dl>' + bar + '<p class="meta">%d%% complete</p>' % percent


def _events(run_dir: Any) -> str:
    events = read_events(run_dir)[-EVENT_LIMIT:]
    body = ''.join(_row([event.get(field) for field in EVENT_FIELDS]) for event in events)
    return _table(list(EVENT_FIELDS), body or '<tr><td colspan="5">no events yet</td></tr>')


def _all_runs(rows: list[tuple[runs.RunRef, dict[str, Any]]]) -> str:
    body = ''.join(_row([s['run_id'], s.get('status'), s.get('phase'), '%s%%' % (s.get('percent') or 0),
                         s.get('updated_at')]) for _, s in rows)
    return _table(['Run', 'Status', 'Phase', 'Percent', 'Updated'],
                  body or '<tr><td colspan="5">no runs</td></tr>')


def render_snapshot(repos: Any, run_id: str | None = None) -> str:
    '''The HTML page for one run: the newest one, or ``run_id``. SnapshotError when none can be shown.'''
    rows = ranked_runs(repos)
    ref = _select(rows, run_id)
    detail = runs.run_detail(ref)
    generated = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    body = ('<main><h1>Simplicio Live snapshot</h1>'
            '<p class="meta">Generated %s. Read-only, no script.</p>'
            '<h2>Run</h2>%s'
            '<h2>Recent events</h2>%s'
            '<h2>All runs</h2>%s</main>') % (
        _esc(generated), _facts(detail['summary'], detail['state']), _events(ref['run_dir']), _all_runs(rows))
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Simplicio Live snapshot</title><style>' + _CSS + '</style></head>'
            '<body>' + body + '</body></html>\n')


def write_snapshot(out: Any, repos: Any, run_id: str | None = None) -> Path:
    '''Write the snapshot page to ``out`` and return its path; nothing is written when rendering fails.'''
    page = render_snapshot(repos, run_id)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page, encoding='utf-8')
    return target
