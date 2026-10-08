'''Coordination view of a task backlog for the Simplicio Live dashboard (GET /api/coordination).

Read-only. The backlog is the JSONL that ``scripts/task_backlog.py`` writes: one ``master`` line, then one ``item``
line per work item. This module turns it into the kanban columns, the dependency edges, the lease health of each
leased item, the drain progress, the worker slots, the GitHub issue and PR links of each item and the git worktrees
of the repository. It is stdlib only and fails open: a missing or unreadable backlog yields an UNVERIFIED view
instead of an exception, and a repository whose worktrees cannot be listed yields UNVERIFIED worktrees only.
'''
from __future__ import annotations

import calendar
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

COLUMNS = ('ready', 'claimed', 'running', 'verifying', 'done', 'blocked')
DEFAULT_TTL_S = 900
DEFAULT_PRIORITY = 100
_TS_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
_GITHUB_PREFIX = 'https://github.com/'
_REPO_RE = re.compile(r'[\w.-]+/[\w.-]+')
_GIT_TIMEOUT_S = 5
_BRANCH_PREFIX = 'refs/heads/'
# Porcelain status codes of an unmerged (conflicted) path.
_UNMERGED = ('DD', 'AU', 'UD', 'UA', 'DU', 'AA', 'UU')
# Any status not listed here (blocked, failed, quarantined, dead-letter, cancelled, skipped, unknown) is blocked.
_STATUS_COLUMNS = {
    'ready': 'ready',
    'claimed': 'claimed',
    'running': 'running',
    'verification': 'verifying',
    'delivery': 'verifying',
    'done': 'done',
}
_LEASE_RANK = {'live': 0, 'stale': 1, 'expired': 2}


class _Unreadable(Exception):
    '''The backlog cannot be read as JSON objects; the message is the UNVERIFIED reason.'''


def build_coordination(backlog_path: Any, now: float | None = None, repo: Any = None) -> dict[str, Any]:
    '''Coordination payload for one backlog file, measured at ``now`` (epoch seconds, default the wall clock).

    ``repo`` is the repository directory whose git worktrees are listed; None leaves the worktrees UNVERIFIED.
    '''
    current = time.time() if now is None else float(now)
    try:
        master, raw_items = _read_backlog(Path(backlog_path))
        return _measured(master or {}, raw_items, current, repo)
    except _Unreadable as exc:
        return _unverified(str(exc))
    except Exception:  # noqa: BLE001 - the endpoint never raises; any failure is an UNVERIFIED view
        return _unverified('backlog could not be interpreted')


def _read_backlog(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    '''Master line (last one wins) and item lines; any malformed or non-object line makes the file unreadable.'''
    try:
        text = path.read_text(encoding='utf-8', errors='replace')
    except FileNotFoundError:
        raise _Unreadable('backlog file not found') from None
    except OSError:
        raise _Unreadable('backlog file is unreadable') from None
    master = None
    items = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            raise _Unreadable(f'backlog line {number} is not valid JSON') from None
        if not isinstance(obj, dict):
            raise _Unreadable(f'backlog line {number} is not a JSON object')
        if obj.get('kind') == 'master':
            master = obj
        elif obj.get('kind') == 'item':
            items.append(obj)
    return master, items


def _measured(master: dict[str, Any], raw_items: list[dict[str, Any]], now: float, repo: Any) -> dict[str, Any]:
    parsed = [(str(obj.get('id') or '').strip(), obj) for obj in raw_items]
    parsed = [(iid, obj) for iid, obj in parsed if iid]
    statuses = {iid: str(obj.get('status') or '') for iid, obj in parsed}
    items = [_item_view(iid, obj, statuses, now) for iid, obj in parsed]
    counts = {column: 0 for column in COLUMNS}
    for item in items:
        counts[item['column']] += 1
    total = len(items)
    done = counts['done']
    remaining = total - done
    done_objs = [obj for iid, obj in parsed if statuses[iid] == 'done']
    eta_s, eta_label, eta_reason = _eta(done_objs, remaining)
    return {
        'status': 'MEASURED',
        'revision': _int(master.get('revision'), 0),
        'columns': [{'key': column, 'count': counts[column]} for column in COLUMNS],
        'items': items,
        'edges': _edges(parsed, statuses),
        'drain': {
            'total': total,
            'done': done,
            'remaining': remaining,
            'blocked': counts['blocked'],
            'percent': int(done * 100 / total) if total else 0,
            'eta_s': eta_s,
            'eta_label': eta_label,
            'reason': eta_reason,
        },
        'slots': _slots(items),
        'worktrees': _worktrees(repo, parsed),
    }


def _item_view(iid: str, obj: dict[str, Any], statuses: dict[str, str], now: float) -> dict[str, Any]:
    status = str(obj.get('status') or '')
    depends_on = _id_list(obj.get('depends_on'))
    column = _STATUS_COLUMNS.get(status, 'blocked')
    blocked_by = [] if column == 'done' else [dep for dep in depends_on if statuses.get(dep) != 'done']
    if column == 'ready' and blocked_by:
        column = 'blocked'
    lease = _lease_view(obj.get('lease'), now)
    github = obj['github'] if isinstance(obj.get('github'), dict) else {}
    repo_slug = _repo_slug(github.get('repo'))
    return {
        'id': iid,
        'goal': str(obj.get('goal') or '').strip(),
        'status': status,
        'column': column,
        'priority': _int(obj.get('priority'), DEFAULT_PRIORITY),
        'depends_on': depends_on,
        'blocked_by': blocked_by,
        'worker': lease['worker'] if lease else None,
        'lease': lease,
        'issue': _link(_number(github.get('issue')) or _number(obj.get('issue')), obj.get('issue_url'),
                       repo_slug, 'issues'),
        'pr': _link(_number(github.get('pr')) or _number(obj.get('pr')), obj.get('pr_url'), repo_slug, 'pull'),
    }


def _link(number: int | None, explicit_url: Any, repo_slug: str | None, kind: str) -> dict[str, Any] | None:
    '''None without a positive number; else the number with an explicit https://github.com/ URL or a built one.'''
    if number is None:
        return None
    url = _github_url(explicit_url)
    if url is None and repo_slug is not None:
        url = f'https://github.com/{repo_slug}/{kind}/{number}'
    return {'number': number, 'url': url}


def _github_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    return url if url.startswith(_GITHUB_PREFIX) else None


def _repo_slug(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    slug = value.strip()
    return slug if _REPO_RE.fullmatch(slug) else None


def _number(value: Any) -> int | None:
    '''A positive issue or PR number from an int or a string of ASCII digits; anything else is None.'''
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not (text.isascii() and text.isdigit()):
            return None
        try:
            value = int(text)
        except ValueError:
            return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _lease_view(raw: Any, now: float) -> dict[str, Any] | None:
    '''Lease health at ``now``: expired at or past expiry (or unparsable), stale past half its TTL, else live.'''
    if not isinstance(raw, dict):
        return None
    worker = str(raw.get('worker') or '').strip()
    if not worker:
        return None
    heartbeat = _parse_utc(raw.get('heartbeat_at'))
    expires = _parse_utc(raw.get('expires_at'))
    ttl = _ttl(raw.get('ttl_seconds'))
    if expires is None or expires <= now:
        state = 'expired'
    elif heartbeat is None or now - heartbeat > ttl / 2:
        state = 'stale'
    else:
        state = 'live'
    return {
        'worker': worker,
        'heartbeat_at': raw.get('heartbeat_at'),
        'expires_at': raw.get('expires_at'),
        'age_s': None if heartbeat is None else int(now - heartbeat),
        'remaining_s': 0 if expires is None else max(0, int(expires - now)),
        'state': state,
    }


def _edges(parsed: list[tuple[str, dict[str, Any]]], statuses: dict[str, str]) -> list[dict[str, Any]]:
    '''One edge per dependency whose both ends are in the backlog; satisfied when the dependency is done.'''
    return [{'from': dep, 'to': iid, 'satisfied': statuses[dep] == 'done'}
            for iid, obj in parsed
            for dep in _id_list(obj.get('depends_on'))
            if dep in statuses]


def _eta(done_objs: list[dict[str, Any]], remaining: int) -> tuple[int | None, str, str | None]:
    '''Seconds left at the observed rate: done items per second since the earliest freeze, over done items.'''
    stamps = []
    for obj in done_objs:
        frozen = _parse_utc(obj.get('frozen_at'))
        finished = _parse_utc(obj.get('done_at'))
        if frozen is not None and finished is not None:
            stamps.append((frozen, finished))
    if len(stamps) < 2:
        return None, 'UNVERIFIED', 'fewer than 2 done items with parsable frozen_at and done_at timestamps'
    start = min(frozen for frozen, _ in stamps)
    end = max(finished for _, finished in stamps)
    if end <= start:
        return None, 'UNVERIFIED', 'done timestamps do not span a positive interval'
    if remaining <= 0:
        return 0, 'ESTIMATE', None
    return int(remaining * (end - start) / len(stamps)), 'ESTIMATE', None


def _slots(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    '''One slot per worker holding a lease. A slot is reclaimable only when every lease it holds has expired.'''
    by_worker: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item['lease']:
            by_worker.setdefault(item['worker'], []).append(item)
    slots = []
    for worker in sorted(by_worker):
        held = by_worker[worker]
        states = [item['lease']['state'] for item in held]
        slots.append({
            'worker': worker,
            'items': [item['id'] for item in held],
            'state': max(states, key=_LEASE_RANK.__getitem__),
            'reclaimable': all(state == 'expired' for state in states),
        })
    return slots


def _worktrees(repo: Any, parsed: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    '''Rows of ``git worktree list --porcelain`` for ``repo``; any failure to list them is UNVERIFIED with no rows.'''
    if repo is None or not str(repo).strip():
        return _worktrees_unverified('no repository given')
    try:
        return _listed_worktrees(str(repo), parsed)
    except Exception:  # noqa: BLE001 - the view never raises; a broken listing is UNVERIFIED worktrees
        return _worktrees_unverified('worktrees could not be listed')


def _listed_worktrees(repo: str, parsed: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    try:
        listing = _git(['-C', repo, 'worktree', 'list', '--porcelain'])
    except FileNotFoundError:
        return _worktrees_unverified('git is not installed')
    except subprocess.TimeoutExpired:
        return _worktrees_unverified('git worktree list timed out')
    except OSError:
        return _worktrees_unverified('git could not be run')
    if listing.returncode != 0:
        return _worktrees_unverified(f'git worktree list exited with {listing.returncode}')
    rows = []
    for index, block in enumerate(_porcelain_blocks(listing.stdout)):
        state = _worktree_state(block)
        rows.append({
            'path': block['path'],
            'branch': block['branch'],
            'head': block['head'],
            'item_id': _item_for(block['path'], block['branch'], parsed),
            'state': state,
            'cleanup': _cleanup(state, block['locked']),
            'main': index == 0,
        })
    return {'status': 'MEASURED', 'reason': None, 'rows': rows}


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    '''Run git without a shell, capturing its output, with the worktree timeout.'''
    return subprocess.run(['git', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=_GIT_TIMEOUT_S, check=False)


def _porcelain_blocks(text: str) -> list[dict[str, Any]]:
    '''One dict per worktree block of the porcelain output; the first block is the main worktree.'''
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.strip():
            current = None
            continue
        key, _, value = line.partition(' ')
        if key == 'worktree':
            current = {'path': value, 'head': None, 'branch': None, 'locked': False, 'prunable': False}
            blocks.append(current)
        elif current is None:
            continue
        elif key == 'HEAD':
            current['head'] = value[:7] or None
        elif key == 'branch':
            current['branch'] = _short_branch(value)
        elif key == 'locked':
            current['locked'] = True
        elif key == 'prunable':
            current['prunable'] = True
    return blocks


def _worktree_state(block: dict[str, Any]) -> str:
    '''prunable, then conflict, dirty, locked, clean; ``unknown`` when the worktree's own status cannot run.'''
    if block['prunable'] or not os.path.exists(block['path']):
        return 'prunable'
    try:
        status = _git(['-C', block['path'], 'status', '--porcelain'])
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    if status.returncode != 0:
        return 'unknown'
    lines = [line for line in status.stdout.splitlines() if line.strip()]
    if any(line[:2] in _UNMERGED for line in lines):
        return 'conflict'
    if lines:
        return 'dirty'
    return 'locked' if block['locked'] else 'clean'


def _cleanup(state: str, locked: bool) -> str:
    '''A locked worktree cannot be pruned; a prunable one is pending ``git worktree prune``.'''
    if locked:
        return 'locked'
    return 'pending' if state == 'prunable' else 'none'


def _item_for(path: str, branch: str | None, parsed: list[tuple[str, dict[str, Any]]]) -> str | None:
    '''An item naming this worktree's path or branch wins; else the longest id found as whole segments of the branch.'''
    for iid, obj in parsed:
        if _same_path(obj.get('worktree'), path) or (branch is not None and _same_branch(obj.get('branch'), branch)):
            return iid
    if branch is None:
        return None
    matches = [iid for iid, _ in parsed if _id_in_branch(iid, branch)]
    return max(matches, key=len) if matches else None


def _id_in_branch(iid: str, branch: str) -> bool:
    '''True when the id is a run of whole ``/``, ``_`` or ``-`` separated segments of the branch name.'''
    return re.search(r'(?:\A|[/_-])' + re.escape(iid) + r'(?=[/_-]|\Z)', branch) is not None


def _same_path(value: Any, path: str) -> bool:
    return isinstance(value, str) and bool(value.strip()) and os.path.normpath(value.strip()) == os.path.normpath(path)


def _same_branch(value: Any, branch: str) -> bool:
    return isinstance(value, str) and _short_branch(value.strip()) == branch


def _short_branch(ref: str) -> str | None:
    return ref.removeprefix(_BRANCH_PREFIX) or None


def _worktrees_unverified(reason: str) -> dict[str, Any]:
    return {'status': 'UNVERIFIED', 'reason': reason, 'rows': []}


def _unverified(reason: str) -> dict[str, Any]:
    return {
        'status': 'UNVERIFIED',
        'reason': reason,
        'columns': [{'key': column, 'count': 0} for column in COLUMNS],
        'items': [],
        'edges': [],
        'drain': None,
        'slots': [],
        'worktrees': _worktrees_unverified('backlog is unverified, so worktrees were not listed'),
    }


def _id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ids = (str(raw).strip() for raw in value if raw is not None)
    return list(dict.fromkeys(iid for iid in ids if iid))


def _parse_utc(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return calendar.timegm(time.strptime(value.strip(), _TS_FORMAT))
    except ValueError:
        return None


def _ttl(value: Any) -> int:
    ttl = _int(value, DEFAULT_TTL_S)
    return ttl if ttl > 0 else DEFAULT_TTL_S


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default
