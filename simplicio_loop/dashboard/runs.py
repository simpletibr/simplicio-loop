'''Run discovery, summaries and safe artifact reads for the Simplicio Live dashboard (#1399).

Read-only over each repo's run directories: ``<repo>/.simplicio-loop/loop-runs/<id>`` and
``<repo>/.simplicio-loop/orchestrator/runs/<id>``. The only file this module writes is the
dashboard state file.
'''
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from simplicio_loop.dashboard import receipt_check
from simplicio_loop.evidence import redact_sensitive_text
from simplicio_loop.progress import build_progress

RUN_ROOTS = ('.simplicio-loop/loop-runs', '.simplicio-loop/orchestrator/runs')
RUN_ID_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
MAX_ARTIFACT_BYTES = 1_000_000
STATE_ENV = 'SIMPLICIO_DASHBOARD_STATE'
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_BEARER_RE = re.compile(r'(?i)Bearer +[A-Za-z0-9._~+/=-]{1,512}')
_PRIVATE_KEY_RE = re.compile(r'(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)')
_OPENAI_STYLE_RE = re.compile(r'\bsk-[A-Za-z0-9_-]{16,}')
_GITHUB_PAT_RE = re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}')
# keyword, up to 64 more key characters, separator, value. The text before the keyword stays outside the match (the old
# 64-character prefix was retried at every word start) and the suffix is possessive: nothing in it can be given back.
_PAIR_RE = re.compile(
    r'(?i)((?:passw(?:or)?d|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)'
    r'[A-Za-z0-9_-]{0,64}+)(["\']?\s*[:=]\s*["\']?)([^\s"\',;&]{4,})')
_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:[.][A-Za-z0-9-]{1,63}){1,8}')
COMMAND_SCAN_MAX = 4096
_Q = r'(?:"[^"]*"|\'[^\']*\'|\S+)'
_URL_USERINFO_RE = re.compile(r'(?i)\b([a-z][a-z0-9+.-]{0,15}://)[^\s/?#@]*@')
_HEADER_RE = re.compile(r'(?i)\b((?:proxy-)?authorization|(?:set-)?cookie)(\s{0,8}[:=]\s{0,8})[^\'"\n]+')
_SECRET_FLAG_RE = re.compile(
    r'(?i)(--?(?:pass(?:word|wd|phrase)?|pwd|token(?:[-_]code)?|secret|api[-_]?key|access[-_]?key|auth(?:orization)?|pat)\s+)'
    r'(?!--)' + _Q)  # a value never starts a flag: the "-token" of `print-identity-token --access-token X` swallowed it
_USER_ARG_RE = re.compile(  # user:pass of curl; a numeric uid:gid (docker -u 1000:1000) is not one
    r'(?<![\w-])(-u\s+|--(?:proxy-)?user[\s=]+)(?!\d+:\d*(?:\s|\Z))'
    r'(?:"[^"\s:]+:[^"]*"|\'[^\'\s:]+:[^\']*\'|[^\s:\'"]+:\S+)')
_COOKIE_ARG_RE = re.compile(r'(?<![\w-])(-b\s+|--cookie[\s=]+)(?:"[^"]*=[^"]*"|\'[^\']*=[^\']*\'|\S*=\S*)')
_SHORT_PASS_RE = re.compile(  # -p is a password only for these programs (it is a port, a path or a plugin for most others)
    r'((?i:\b(?:mysql\w*|sshpass|twine|mongo\w*|(?:docker|podman|az)\s+login)\b)[^;&|\n]{0,200}?\s-p\s*)(?:"[^"]*"|\'[^\']*\'|[^\s-]\S*)')
_PROGRAM_PASS_RE = re.compile(  # the password flag of programs where it is not -p: redis-cli -a, sqlcmd -P
    r'((?i:\bredis-cli\b)[^;&|\n]{0,200}?\s-a\s*|(?i:\bsqlcmd\b)[^;&|\n]{0,200}?\s-P\s*)(?:"[^"]*"|\'[^\']*\'|[^\s-]\S*)')
_SMB_USER_RE = re.compile(  # smbclient -U user%password
    r'((?i:\b(?:smbclient|rpcclient)\b)[^;&|\n]{0,200}?\s(?:-U\s*|--user[=\s]\s*)[^\s%]{1,64}%)\S+')
# vault login TOKEN: the token is the argument without an =, the method arguments (username=me) hold one
_VAULT_LOGIN_RE = re.compile(r'(\bvault\s+login\s+(?:-\S+\s+){0,8})[^\s=-][^\s=]*(?=\s|\Z)')
# header.payload.signature, whatever the signature's length (the long-token rule needs 32 characters)
_JWT_RE = re.compile(r'(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{4,4096}+\.[A-Za-z0-9_-]{4,4096}+\.[A-Za-z0-9_-]{0,4096}+')
_LONG_TOKEN_RE = re.compile(  # a base64/random blob: 32+ characters mixing upper case, lower case and digits
    r'(?<![A-Za-z0-9+/_-])(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{32,}')
_TOKEN_PREFIX_RE = re.compile(  # tokens with a well-known prefix, whatever their length or alphabet
    r'\b(?:xox[abeprs]-|npm_|glpat-|pypi-|hf_|sk_(?:live|test)_|rk_live_|AIza|ya29[.]|hv[sbr][.])[A-Za-z0-9_.-]{10,}')
_CUT_WORD_RE = re.compile(r'\s\S*\Z')
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
    '''Parse a JSON file with secrets masked; None when missing, a symlink, oversize or malformed.'''
    if path.is_symlink():
        return None
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


TAIL_WINDOW_BYTES = 4096  # the bytes just before a read's offset: their digest tells a rewrite that grew the file back apart
_EMPTY_DIGEST = hashlib.blake2b(b'', digest_size=16).digest()


def _line_seq(line: bytes) -> int:
    '''The ``seq`` of one events.jsonl line; 0 when the line is not a JSON object with a positive integer ``seq``.'''
    try:
        seq = json.loads(line.decode('utf-8', 'replace')).get('seq')
    except (ValueError, AttributeError):
        return 0
    return seq if isinstance(seq, int) and seq > 0 else 0


class _Tail:
    '''Where the last read of events.jsonl stopped: the file it read (device and inode), the byte offset just past its last newline,
    the highest seq before that offset, and the digest of the TAIL_WINDOW_BYTES before it.'''

    __slots__ = ('digest', 'ident', 'offset', 'seq')

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.ident = None
        self.offset = 0
        self.seq = 0
        self.digest = _EMPTY_DIGEST


def _window_digest(fh, offset: int) -> bytes:
    '''Digest of the TAIL_WINDOW_BYTES bytes that end at ``offset`` (of the open binary file ``fh``).'''
    start = max(0, offset - TAIL_WINDOW_BYTES)
    fh.seek(start)
    return hashlib.blake2b(fh.read(offset - start), digest_size=16).digest()


def _tail_seq(run_dir: Path, tail: _Tail) -> int:
    '''Highest seq of events.jsonl, reading only the bytes after ``tail.offset``; the offset and the seq before it are kept in ``tail``.

    The state belongs to one file. A different device or inode (rotation, replacement), a file shorter than the offset (truncation)
    or other bytes before the offset (a rewrite that grew the file back past it) starts again from byte 0. Only complete lines move
    the offset: a last line without its newline is counted in this answer and read again next time, so a half-written event is
    neither counted twice nor lost. The events file is only appended to and rotated, never edited in place, so an edit that changes
    nothing in the last TAIL_WINDOW_BYTES before the offset is not seen; a full scan (``_last_seq`` with no tail) sees it.
    '''
    path = run_dir / 'events.jsonl'
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            tail.reset()
            return 0
        with path.open('rb') as fh:
            st = os.fstat(fh.fileno())
            ident = (st.st_dev, st.st_ino)
            if ident != tail.ident or st.st_size < tail.offset or _window_digest(fh, tail.offset) != tail.digest:
                offset, seq = 0, 0
            else:
                offset, seq = tail.offset, tail.seq
            fh.seek(offset)
            answer = committed = seq
            committed_offset = pos = offset
            for line in fh:
                pos += len(line)
                answer = max(answer, _line_seq(line))
                if line.endswith(b'\n'):
                    committed_offset, committed = pos, answer
            tail.ident, tail.offset, tail.seq = ident, committed_offset, committed
            tail.digest = _window_digest(fh, committed_offset)
            return answer
    except OSError:
        tail.reset()
        return 0


def _last_seq(run_dir: Path, tail: _Tail | None = None) -> int:
    '''Highest ``seq`` in events.jsonl. With no ``tail`` the whole file is streamed line by line (the reference answer, never held
    in memory); with one, only the bytes after its offset are read (see _tail_seq).'''
    if tail is not None:
        return _tail_seq(run_dir, tail)
    last = 0
    if (run_dir / 'events.jsonl').is_symlink():
        return 0
    try:
        with (run_dir / 'events.jsonl').open('rb') as fh:
            for line in fh:
                last = max(last, _line_seq(line))
    except OSError:
        return 0
    return last


# --- the memoized summary of one run (#1569) -------------------------------------------------------------------------------
# The files a summary is made of, relative to the run directory. A change in any of them changes the stamp.
SUMMARY_INPUTS = ('state.json', 'events.jsonl', 'completion-receipt.json', 'execution-route.json',
                  'evidence-receipt.json', 'loop/watcher_state.json')
# Memory bound: at most SUMMARY_CACHE_MAX runs and SUMMARY_BYTES_MAX bytes of JSON in all (a summary is about 10 KB; a state.json
# of 850 KB is copied into it almost whole), and the least recently used run leaves first. A listing of more runs than the memo
# holds gets no hit, because the scan is in order. A summary larger than the whole budget is never remembered.
SUMMARY_CACHE_MAX = 4096
SUMMARY_BYTES_MAX = 64 * 1024 * 1024
# A file touched less than this long before the stamp was taken could still be rewritten inside the same timestamp tick with the
# same size, so the stamp cannot tell the rewrite apart: such a run is recomputed, not remembered. Disks that stamp whole seconds
# (ext3, HFS+, FAT at two seconds) get the coarse window.
RACY_NS = 100_000_000
RACY_COARSE_NS = 2_000_000_000
_NS = 1_000_000_000
_lstat = os.lstat
_now_ns = time.time_ns


class _Memo:
    __slots__ = ('blob', 'lock', 'stamp', 'tail')

    def __init__(self) -> None:
        self.lock = threading.Lock()  # one computation per run at a time: the pollers of a changed run wait for it, then reuse it
        self.stamp: tuple | None = None
        self.blob: str | None = None  # the summary as JSON, so no caller ever holds the memoized object
        self.tail = _Tail()  # where the last settled read of events.jsonl stopped; it lives and leaves with the memo


_SUMMARIES: OrderedDict[str, _Memo] = OrderedDict()
_SUMMARIES_BYTES = 0  # the length of the blobs of the memos in _SUMMARIES; both are guarded by _SUMMARIES_LOCK
_SUMMARIES_LOCK = threading.Lock()


def _stamp(run_dir: str, fallback_repo: str, began: int) -> tuple[tuple, bool]:
    '''(stamp, settled) of the files a summary reads: inode, size, mtime and ctime of each (None when absent).

    ``settled`` is False when any file changed less than the racy window before ``began`` (the clock read before the stat), or
    when any of them is a symlink: build_progress follows a link to a receipt, and the stat of the link cannot see its target
    change. The ctime cannot be set from user space, so a rewrite that restores size and mtime still changes the stamp.'''
    files: list[tuple | None] = []
    settled = True
    for name in SUMMARY_INPUTS:
        try:
            st = _lstat(run_dir + '/' + name)
        except OSError:
            files.append(None)
            continue
        files.append((st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
        if stat.S_ISLNK(st.st_mode):
            settled = False
        coarse = st.st_mtime_ns % _NS == 0 and st.st_ctime_ns % _NS == 0
        if max(st.st_mtime_ns, st.st_ctime_ns) > began - (RACY_COARSE_NS if coarse else RACY_NS):
            settled = False
    return (fallback_repo, tuple(files)), settled


def _trim() -> None:
    '''Drop the least recently used runs until the memo is inside both limits. The caller holds _SUMMARIES_LOCK.'''
    global _SUMMARIES_BYTES
    while len(_SUMMARIES) > SUMMARY_CACHE_MAX or _SUMMARIES_BYTES > SUMMARY_BYTES_MAX:
        _SUMMARIES_BYTES -= len(_SUMMARIES.popitem(last=False)[1].blob or '')


def _memo_for(key: str) -> _Memo:
    with _SUMMARIES_LOCK:
        memo = _SUMMARIES.pop(key, None) or _Memo()
        _SUMMARIES[key] = memo
        _trim()
    return memo


def _remember(key: str, memo: _Memo, stamp: tuple | None, blob: str | None) -> None:
    '''Set what the memo holds for a run. The bytes count only while the memo is still in _SUMMARIES (it may have left meanwhile).'''
    global _SUMMARIES_BYTES
    with _SUMMARIES_LOCK:
        if _SUMMARIES.get(key) is memo:
            _SUMMARIES_BYTES += len(blob or '') - len(memo.blob or '')
        memo.stamp, memo.blob = stamp, blob
        _trim()


def clear_summary_cache() -> None:
    global _SUMMARIES_BYTES
    with _SUMMARIES_LOCK:
        _SUMMARIES.clear()
        _SUMMARIES_BYTES = 0


def summary_cache_size() -> int:
    with _SUMMARIES_LOCK:
        return len(_SUMMARIES)


def summary_cache_bytes() -> int:
    with _SUMMARIES_LOCK:
        return _SUMMARIES_BYTES


def run_summary(ref: RunRef | Path) -> dict[str, Any]:
    '''Progress fields from ``build_progress`` plus identity, timing, last event seq and cost.

    ``status`` is the raw state status (for example ``running`` or ``done``); the progress verdict
    is kept under ``progress_status``. ``cost_usd`` is always None: no measured receipt exists yet.

    Memoized per run directory while the stamp of the files it reads (SUMMARY_INPUTS: inode, size, mtime, ctime) is unchanged and
    settled (see RACY_NS); the stamp is taken before the files are read, so a file that changes during the read is read again on
    the next call. A run with a symlinked input is never remembered. The memo holds SUMMARY_CACHE_MAX runs and SUMMARY_BYTES_MAX
    bytes at most, and every caller gets its own copy. Every recomputation reads only the bytes of events.jsonl written since the
    last one (see _tail_seq), settled or not: the tail is checked by file identity, size and content, not by timestamps. Only what
    the memo keeps needs a settled stamp.
    '''
    run_dir = Path(ref['run_dir'] if isinstance(ref, dict) else ref)
    fallback_repo = ref['repo'] if isinstance(ref, dict) else ''
    key = os.fspath(run_dir)
    memo = _memo_for(key)
    with memo.lock:
        stamp, settled = _stamp(key, fallback_repo, _now_ns())
        if settled and memo.stamp == stamp and memo.blob is not None:
            return json.loads(memo.blob)
        summary = _summarize(run_dir, fallback_repo, memo.tail)
        blob = json.dumps(summary) if settled else ''
        keep = settled and len(blob) <= SUMMARY_BYTES_MAX
        _remember(key, memo, stamp if keep else None, blob if keep else None)
        return summary


def _summarize(run_dir: Path, fallback_repo: str, tail: _Tail | None = None) -> dict[str, Any]:
    '''The summary of one run, computed from the files (no memo). ``tail`` is passed only by the memo; None reads events.jsonl whole.'''
    state = _load_state(run_dir)
    summary = dict(build_progress(state, run_dir=run_dir))
    summary.update({
        'run_id': run_dir.name,
        'status': str(state.get('status') or summary['status']),
        'progress_status': summary['status'],
        'repo': str(state.get('repo') or fallback_repo),
        'started_at': state.get('started_at'),
        'finished_at': state.get('finished_at'),
        'updated_at': state.get('updated_at'),
        'duration_s': _duration_s(state),
        'last_seq': _last_seq(run_dir, tail),
        'cost_usd': None,
    })
    return redact_json(summary)


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
    '''Files under ``receipts/``, top-level ``*receipt*.json`` and ``quality-matrix.json``: run-relative name, size and schema verdict.'''
    candidates: list[Path] = []
    receipts_dir = run_dir / 'receipts'
    if receipts_dir.is_dir() and not receipts_dir.is_symlink():
        candidates.extend(sorted(receipts_dir.iterdir()))
    candidates.extend(sorted(run_dir.glob('*receipt*.json')))
    quality = run_dir / 'quality-matrix.json'
    if quality.is_file():
        candidates.append(quality)
    index: list[dict[str, Any]] = []
    for path in candidates:
        if path.is_file() and not path.is_symlink():
            index.append({'name': path.relative_to(run_dir).as_posix(), 'size': path.stat().st_size,
                          'validation': redact_json(receipt_check.check_receipt(path))})
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
    '''Mask private key blocks, bearer tokens, API keys, password/token pairs and email addresses.

    Covers the secret shapes evidence.py already knows, plus Anthropic-style and project keys, GitHub
    fine-grained tokens, key blocks and any password=, token= or *_secret= pair of four or more characters.
    '''
    masked = _PRIVATE_KEY_RE.sub('[REDACTED_PRIVATE_KEY]', redact_sensitive_text(text))
    masked = _BEARER_RE.sub('Bearer [REDACTED_SECRET]', masked)
    masked = _OPENAI_STYLE_RE.sub('[REDACTED_SECRET]', masked)
    masked = _GITHUB_PAT_RE.sub('[REDACTED_SECRET]', masked)
    masked = _PAIR_RE.sub(r'\1\2[REDACTED]', masked)
    return _EMAIL_RE.sub('[REDACTED_EMAIL]', masked)


def redact_command(text: str, limit: int = COMMAND_SCAN_MAX) -> str:
    '''Mask secrets in one shell command line: ``redact_text`` plus URL credentials, auth headers, the value after a
    secret flag (``--token abc``, ``-p`` of mysql/sshpass/twine/docker login, ``-u user:pass``) and base64-looking blobs.

    Only the first ``limit`` characters are scanned, and the word the cut may have split is dropped after the masking, so
    the cut can never leave the head of a secret behind.
    '''
    cut = len(text) > limit
    masked = _URL_USERINFO_RE.sub(r'\1[REDACTED]@', text[:limit])
    masked = _HEADER_RE.sub(r'\1\2[REDACTED]', masked)
    for rx in (_SECRET_FLAG_RE, _USER_ARG_RE, _COOKIE_ARG_RE, _SHORT_PASS_RE, _PROGRAM_PASS_RE, _SMB_USER_RE, _VAULT_LOGIN_RE):
        masked = rx.sub(r'\1[REDACTED]', masked)
    masked = _JWT_RE.sub('[REDACTED]', masked)  # before the long-token rule masks its middle and leaves the rest
    masked = _LONG_TOKEN_RE.sub('[REDACTED]', _TOKEN_PREFIX_RE.sub('[REDACTED]', redact_text(masked)))
    if cut:
        tail = _CUT_WORD_RE.search(masked)
        masked = masked[:tail.start()] if tail else ''
    return masked


def _redact_bytes(data: bytes) -> bytes:
    '''Mask secrets in a byte payload; bytes that are not UTF-8 round-trip unchanged.'''
    return redact_text(data.decode('utf-8', 'surrogateescape')).encode('utf-8', 'surrogateescape')


def redact_json(value: Any) -> Any:
    '''Public entry for any JSON-shaped value: secret-shaped keys and strings are masked.'''
    return _redact_json(value)


def _redact_json(value: Any, sensitive: bool = False) -> Any:
    '''Recursively mask strings and keys; every string under a secret-looking key is masked whole.'''
    if isinstance(value, dict):
        return {redact_text(str(k)): _redact_json(v, sensitive or bool(_SENSITIVE_KEY_RE.search(str(k))))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(item, sensitive) for item in value]
    if isinstance(value, str):
        return '[REDACTED]' if sensitive else redact_text(value)
    return value
