'''Run discovery, summaries and safe artifact reads for the Simplicio Live dashboard (#1399).

Read-only over each repo's run directories: ``<repo>/.simplicio-loop/loop-runs/<id>`` and
``<repo>/.simplicio-loop/orchestrator/runs/<id>``. The only file this module writes is the
dashboard state file.
'''
from __future__ import annotations

import json
import os
import re
import urllib.parse
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from simplicio_loop.evidence import redact_sensitive_text
from simplicio_loop.progress import build_progress

RUN_ROOTS = ('.simplicio-loop/loop-runs', '.simplicio-loop/orchestrator/runs')
RUN_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
MAX_ARTIFACT_BYTES = 1_000_000
STATE_ENV = 'SIMPLICIO_DASHBOARD_STATE'
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_BEARER_RE = re.compile(r'(?i)Bearer +[A-Za-z0-9._~+/=-]{1,512}')
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:[.][A-Za-z0-9-]{1,63}){1,8}')
_SENSITIVE_KEY_RE = re.compile(r'(?i)secret|passw|api[_-]?key|authoriz|cookie|credential|private[_-]?key|token')


class ArtifactError(Exception):
    '''Base for artifact read failures; ``status`` is the HTTP status the server returns.'''

    status = 500


class ArtifactForbidden(ArtifactError):
    status = 403


class ArtifactNotFound(ArtifactError):
    status = 404


class ArtifactTooLarge(ArtifactError):
    status = 413


class RunRef(TypedDict):
    repo: str
    run_id: str
    run_dir: Path


def discover_runs(repos: str | os.PathLike | Iterable[str | os.PathLike]) -> list[RunRef]:
    '''Run directories under each repo's two run roots; symlinks and invalid run ids are skipped.'''
    if isinstance(repos, (str, os.PathLike)):
        repos = [repos]
    found: list[RunRef] = []
    for repo in repos:
        repo_path = Path(repo)
        for rel in RUN_ROOTS:
            root = repo_path / rel
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if child.is_symlink() or not child.is_dir() or not RUN_ID_RE.fullmatch(child.name):
                    continue
                found.append({'repo': str(repo_path), 'run_id': child.name, 'run_dir': child})
    return found


def state_file_path() -> Path:
    '''Dashboard state file: ``SIMPLICIO_DASHBOARD_STATE`` when set, else under the user's home.'''
    override = os.environ.get(STATE_ENV, '').strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / '.simplicio-loop' / 'dashboard' / 'state.json'


def write_state_file(state: dict[str, Any], path: Path | None = None) -> Path:
    '''Atomically write the state as JSON, mode 0600 (owner read and write only).'''
    target = Path(path) if path else state_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(state, fh, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def read_state_file(path: Path | None = None) -> dict[str, Any]:
    '''Saved dashboard state, or an empty dict when the file is missing or unreadable.'''
    target = Path(path) if path else state_file_path()
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_ts(value: object) -> datetime | None:
    '''Parse an ISO-8601 timestamp (a trailing Z is allowed) as aware UTC; None when unparseable.'''
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_json(path: Path) -> Any:
    '''Parse a JSON file with secrets masked; None when missing, oversize or malformed.'''
    try:
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            return None
        return _redact_json(json.loads(path.read_text(encoding='utf-8')))
    except (OSError, ValueError):
        return None


def _load_state(run_dir: Path) -> dict[str, Any]:
    data = _read_json(run_dir / 'state.json')
    return data if isinstance(data, dict) else {}


def _duration_s(state: dict[str, Any]) -> int | None:
    '''Seconds from started_at to finished_at, or to updated_at while the run has not finished.'''
    start = _parse_ts(state.get('started_at'))
    end = _parse_ts(state.get('finished_at')) or _parse_ts(state.get('updated_at'))
    if start is None or end is None or end < start:
        return None
    return int((end - start).total_seconds())


def _last_seq(run_dir: Path) -> int:
    '''Highest ``seq`` in events.jsonl, streamed line by line so the file is never held in memory.'''
    last = 0
    try:
        with (run_dir / 'events.jsonl').open('r', encoding='utf-8', errors='replace') as fh:
            for line in fh:
                try:
                    seq = json.loads(line).get('seq')
                except (ValueError, AttributeError):
                    continue
                if isinstance(seq, int) and seq > last:
                    last = seq
    except OSError:
        return 0
    return last


def run_summary(ref: RunRef | Path) -> dict[str, Any]:
    '''Progress fields from ``build_progress`` plus identity, timing, last event seq and cost.

    ``status`` is the raw state status (for example ``running`` or ``done``); the progress verdict
    is kept under ``progress_status``. ``cost_usd`` is always None: no measured receipt exists yet.
    '''
    run_dir = Path(ref['run_dir'] if isinstance(ref, dict) else ref)
    state = _load_state(run_dir)
    summary = dict(build_progress(state, run_dir=run_dir))
    fallback_repo = ref['repo'] if isinstance(ref, dict) else ''
    summary.update({
        'run_id': run_dir.name,
        'status': str(state.get('status') or summary['status']),
        'progress_status': summary['status'],
        'repo': str(state.get('repo') or fallback_repo),
        'started_at': state.get('started_at'),
        'finished_at': state.get('finished_at'),
        'updated_at': state.get('updated_at'),
        'duration_s': _duration_s(state),
        'last_seq': _last_seq(run_dir),
        'cost_usd': None,
    })
    return summary


def list_runs(root: str | os.PathLike, status: str | None = None, repo: str | None = None,
              since: str | None = None) -> list[dict[str, Any]]:
    '''Summaries of the runs under one repo root, newest ``updated_at`` first.

    ``status`` and ``repo`` are exact matches. ``since`` keeps runs updated at or after that ISO time.
    '''
    since_ts = None
    if since is not None:
        since_ts = _parse_ts(since)
        if since_ts is None:
            raise ValueError('since must be an ISO-8601 timestamp')
    rows: list[dict[str, Any]] = []
    for ref in discover_runs(root):
        summary = run_summary(ref)
        if status is not None and summary['status'] != status:
            continue
        if repo is not None and summary['repo'] != repo:
            continue
        updated = _parse_ts(summary.get('updated_at'))
        if since_ts is not None and (updated is None or updated < since_ts):
            continue
        rows.append(summary)
    rows.sort(key=lambda row: (_parse_ts(row.get('updated_at')) or _EPOCH, row['run_id']), reverse=True)
    return rows


def run_detail(ref: RunRef | Path) -> dict[str, Any]:
    '''State, manifest and plan JSON plus receipt names and sizes. Receipt contents are never read.'''
    run_dir = Path(ref['run_dir'] if isinstance(ref, dict) else ref)
    return {
        'summary': run_summary(ref),
        'state': _load_state(run_dir),
        'manifest': _read_json(run_dir / 'manifest.json'),
        'plan': _read_json(run_dir / 'plan.json'),
        'receipts': _index_receipts(run_dir),
        'artifacts': _index_artifacts(run_dir),
    }


# The on-demand artifacts the drill-down reads; a name is listed only when the run wrote a regular file for it.
ON_DEMAND_ARTIFACTS = ('task-contract.json', 'mapper-context.json')


def _index_artifacts(run_dir: Path) -> list[str]:
    '''Names of the on-demand artifacts present as regular files. Their contents are never read here.'''
    names = []
    for name in ON_DEMAND_ARTIFACTS:
        path = run_dir / name
        if path.is_file() and not path.is_symlink():
            names.append(name)
    return names


def _index_receipts(run_dir: Path) -> list[dict[str, Any]]:
    '''Files under ``receipts/``, top-level ``*receipt*.json`` and ``quality-matrix.json``, as run-relative name and size.'''
    candidates: list[Path] = []
    receipts_dir = run_dir / 'receipts'
    if receipts_dir.is_dir():
        candidates.extend(sorted(receipts_dir.iterdir()))
    candidates.extend(sorted(run_dir.glob('*receipt*.json')))
    quality = run_dir / 'quality-matrix.json'
    if quality.is_file():
        candidates.append(quality)
    index: list[dict[str, Any]] = []
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            index.append({'name': path.relative_to(run_dir).as_posix(), 'size': path.stat().st_size})
    return index


def read_artifact(run_dir: str | os.PathLike, rel: str, max_bytes: int = MAX_ARTIFACT_BYTES) -> bytes:
    '''Bytes of ``rel`` inside the run directory, with secrets masked.

    ``rel`` is percent-decoded once, then rejected when it is absolute, holds a backslash or NUL,
    or has an empty, ``.`` or ``..`` segment. The resolved real path must stay under the run
    directory, which also blocks symlink escapes.
    '''
    decoded = urllib.parse.unquote(rel)
    parts = decoded.split('/')
    if (not decoded or chr(0) in decoded or chr(92) in decoded or os.path.isabs(decoded)
            or decoded.startswith('/') or any(part in ('', '.', '..') for part in parts)):
        raise ArtifactForbidden(rel)
    base = os.path.realpath(run_dir)
    candidate = os.path.realpath(os.path.join(base, *parts))
    try:
        inside = os.path.commonpath([base, candidate]) == base
    except ValueError:
        inside = False
    if not inside or candidate == base:
        raise ArtifactForbidden(rel)
    try:
        size = os.stat(candidate).st_size
    except OSError:
        raise ArtifactNotFound(rel) from None
    if not os.path.isfile(candidate):
        raise ArtifactNotFound(rel)
    if size > max_bytes:
        raise ArtifactTooLarge(rel)
    with open(candidate, 'rb') as fh:
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ArtifactTooLarge(rel)
    return _redact_bytes(data)


def redact_text(text: str) -> str:
    '''Mask bearer tokens and email addresses, plus the secret shapes evidence.py already knows.'''
    masked = redact_sensitive_text(text)
    masked = _BEARER_RE.sub('Bearer [REDACTED_SECRET]', masked)
    return _EMAIL_RE.sub('[REDACTED_EMAIL]', masked)


def _redact_bytes(data: bytes) -> bytes:
    '''Mask secrets in a byte payload; bytes that are not UTF-8 round-trip unchanged.'''
    return redact_text(data.decode('utf-8', 'surrogateescape')).encode('utf-8', 'surrogateescape')


def _redact_json(value: Any, sensitive: bool = False) -> Any:
    '''Recursively mask strings; every string under a secret-looking key is masked whole.'''
    if isinstance(value, dict):
        return {str(k): _redact_json(v, sensitive or bool(_SENSITIVE_KEY_RE.search(str(k))))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(item, sensitive) for item in value]
    if isinstance(value, str):
        return '[REDACTED]' if sensitive else redact_text(value)
    return value
