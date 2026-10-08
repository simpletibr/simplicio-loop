'''Localhost HTTP server for the Simplicio Live dashboard (#1400).

Read-only JSON API and SSE stream over the run directories that ``simplicio_loop.dashboard.runs``
and ``tail`` expose. Binds 127.0.0.1 only. Every request passes ``guard()`` (Host, Origin, token,
method) before a route runs. Stdlib only.

    python -m simplicio_loop.dashboard.server --port 8765 --repo <repo>
'''
from __future__ import annotations

import argparse
import errno
import hmac
import http.client
import http.server
import importlib.util
import json
import mimetypes
import os
import re
import secrets
import socketserver
import sys
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any, Mapping

from simplicio_loop import __version__, stage_agents
from simplicio_loop.dashboard import STATIC_DIR, alerts, runs
from simplicio_loop.dashboard.tail import EventTail

HOST = '127.0.0.1'
EVENTS_FILE = 'events.jsonl'
HEARTBEAT_SECONDS = 15.0
RETRY_MS = 1000
EXEMPT_PATHS = frozenset({'/api/health'})
TERMINAL_STATUSES = frozenset({'done', 'failed', 'cancelled'})
CSP = "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'"
_CURSOR_RE = re.compile(r'[0-9]{1,18}')
_EVENTS_RE = re.compile(r'/api/runs/([^/]+)/events')
_ARTIFACT_RE = re.compile(r'/api/runs/([^/]+)/artifacts/(.+)')
_DETAIL_RE = re.compile(r'/api/runs/([^/]+)')
STATIC_TYPES = {
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.html': 'text/html; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8',
    '.woff2': 'font/woff2',
}


def security_headers() -> dict[str, str]:
    '''Headers on every response: a locked-down CSP, no sniffing, no referrer, no caching.'''
    return {
        'Content-Security-Policy': CSP,
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Cache-Control': 'no-store',
    }


def token_matches(given: str | None, expected: str) -> bool:
    '''Constant-time token comparison; an empty side never matches.'''
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode('utf-8'), expected.encode('utf-8'))


def _header(headers: Any, name: str) -> str | None:
    '''Case-insensitive header lookup for an email Message or a plain dict.'''
    value = headers.get(name)
    if value is not None:
        return value
    wanted = name.lower()
    for key, val in headers.items():
        if key.lower() == wanted:
            return val
    return None


def extract_token(query: Mapping[str, str], headers: Any) -> str | None:
    '''Token from ``?t=``, then ``Authorization: Bearer``, then ``X-Simplicio-Token``.'''
    if query.get('t'):
        return query['t']
    scheme, _, value = (_header(headers, 'Authorization') or '').partition(' ')
    if scheme.lower() == 'bearer' and value.strip():
        return value.strip()
    return _header(headers, 'X-Simplicio-Token') or None


def _host_allowed(host: str, port: int | None) -> bool:
    '''Host must be 127.0.0.1 or localhost; with a bound port it must also name that port.'''
    name, _, given = host.partition(':')
    if name not in (HOST, 'localhost'):
        return False
    if port is None:
        return given == '' or given.isdigit()
    return given == str(port)


def _is_public(path: str) -> bool:
    '''Paths served without the token: the health probe and the static kit, which holds no run data.'''
    return path in EXEMPT_PATHS or path.startswith('/static/')


def guard(method: str, path: str, headers: Any, query: Mapping[str, str], token: str,
          port: int | None = None) -> int:
    '''Gate for one request: 403 (Host, Origin), 401 (token), 405 (not GET), else 200.'''
    host = _header(headers, 'Host') or ''
    if not _host_allowed(host, port):
        return 403
    origin = _header(headers, 'Origin')
    if origin is not None and origin != 'http://' + host:
        return 403
    if not _is_public(path) and not token_matches(extract_token(query, headers), token):
        return 401
    return 200 if method == 'GET' else 405

class HttpError(Exception):
    '''A route failure that becomes an HTTP status with a JSON error body.'''

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _ts(value: Any) -> datetime:
    '''An ISO timestamp as aware UTC, for ordering runs from several repos; the epoch when unusable.'''
    text = value if isinstance(value, str) else ''
    try:
        parsed = datetime.fromisoformat(text[:-1] + '+00:00' if text.endswith('Z') else text)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _find_run(server: Any, run_id: str) -> dict[str, Any]:
    '''The discovered ref for ``run_id`` in any watched repo; HttpError 404 when absent or malformed.'''
    if runs.RUN_ID_RE.fullmatch(run_id):
        for ref in runs.discover_runs(server.repos):
            if ref['run_id'] == run_id:
                return ref
    raise HttpError(404, 'run not found')


def _list_runs(server: Any, query: Mapping[str, str]) -> list[dict[str, Any]]:
    '''Run summaries from every watched repo, filtered by status, repo and since; newest first.'''
    rows: list[dict[str, Any]] = []
    for root in server.repos:
        try:
            rows.extend(runs.list_runs(root, status=query.get('status'), repo=query.get('repo'),
                                       since=query.get('since')))
        except ValueError as exc:
            raise HttpError(400, str(exc)) from None
    rows.sort(key=lambda row: (_ts(row.get('updated_at')), row['run_id']), reverse=True)
    return rows


def _cursor(query: Mapping[str, str], headers: Any) -> int:
    '''Resume seq: the larger of the Last-Event-ID header and the since_seq query; 400 on garbage.'''
    cursor = 0
    for raw in (_header(headers, 'Last-Event-ID'), query.get('since_seq')):
        text = (raw or '').strip()
        if not text:
            continue
        if not _CURSOR_RE.fullmatch(text):
            raise HttpError(400, 'cursor must be a non-negative integer')
        cursor = max(cursor, int(text))
    return cursor


def _is_terminal(ref: dict[str, Any]) -> bool:
    return runs.run_summary(ref)['status'] in TERMINAL_STATUSES


RECEIPT_READY_VERDICTS = ('COMPLETE', 'DRAINED', 'VERIFIED')


def _now_ms() -> int:
    return int(time.time() * 1000)


def _receipt_ready(ref: Mapping[str, Any]) -> bool:
    '''Whether the run has a ready completion receipt. Read only when the alert rules ask, once the run is done.'''
    completion = runs.run_summary(ref).get('completion') or {}
    return completion.get('ready') is True and str(completion.get('verdict') or '').upper() in RECEIPT_READY_VERDICTS


def _load_hook() -> Any:
    '''The legacy token monitor from hooks/ in a checkout, else from the installed bundle.'''
    here = Path(__file__).resolve()
    candidates = (here.parents[2] / 'hooks' / 'simplicio_dashboard.py',
                  here.parents[1] / '_bundle' / 'hooks' / 'simplicio_dashboard.py')
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location('simplicio_dashboard_hook', path)
            if spec is None or spec.loader is None:
                break
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise ImportError('simplicio_dashboard.py not found')


PRICES_FILE = Path(__file__).resolve().with_name('prices.json')
STAGES_FILE = stage_agents.STAGES_FILE


def price_table() -> dict[str, Any]:
    '''The price source the cost estimate reads: prices.json, or UNVERIFIED when it cannot be read.'''
    try:
        return json.loads(PRICES_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'UNVERIFIED', 'reason': 'tabela de preços indisponível'}


def _tokens() -> dict[str, Any]:
    '''Token monitor status read through the legacy hook; any failure is UNVERIFIED, never a 500.'''
    try:
        status = _load_hook().get_status()
    except Exception as exc:  # fail open: the dashboard keeps serving
        return {'status': 'UNVERIFIED', 'reason': 'token monitor unavailable: %s' % exc.__class__.__name__,
                'cost_usd': 'UNVERIFIED'}
    return {'status': 'MEASURED', 'source': 'hooks/simplicio_dashboard.py get_status',
            'cost_usd': 'UNVERIFIED', 'data': status, 'pricing': price_table()}


def _agents() -> dict[str, Any]:
    '''The roles the stage-agents contract declares, with the stages each one runs. No instance is measured yet.'''
    try:
        graph = stage_agents.load_graph(STAGES_FILE)
    except Exception as exc:  # fail open: the panel keeps serving
        return {'status': 'UNVERIFIED', 'roles': [],
                'reason': 'contrato de agentes ilegível: %s' % exc.__class__.__name__}
    stages: dict[str, list[str]] = {}
    for stage in graph['stages']:
        stages.setdefault(stage['role_id'], []).append(stage['stage_id'])
    roles = [{'role_id': role['role_id'], 'title': role['title'], 'stages': stages.get(role['role_id'], [])}
             for role in graph['roles']]
    return {'status': 'UNVERIFIED', 'roles': roles,
            'reason': 'instâncias ativas não medidas: nenhum produtor de agentes escreve estado ainda'}


def _queue(server: Any) -> dict[str, Any]:
    '''Runs that have not reached a terminal status.'''
    active = [row for row in _list_runs(server, {}) if row.get('status') not in TERMINAL_STATUSES]
    return {'queue': active}


def _health(server: Any) -> dict[str, Any]:
    return {'status': 'ok', 'version': __version__, 'pid': os.getpid(),
            'uptime_s': round(time.monotonic() - server.started_at, 1),
            'observed_runs': len(runs.discover_runs(server.repos))}


def _api(server: Any, path: str, query: Mapping[str, str]) -> Any:
    '''JSON payload of one read route; HttpError 404 for an unknown path.'''
    if path == '/api/health':
        return _health(server)
    if path == '/api/runs':
        return {'runs': _list_runs(server, query)}
    if path == '/api/queue':
        return _queue(server)
    if path == '/api/agents':
        return _agents()
    if path == '/api/tokens':
        return _tokens()
    detail = _DETAIL_RE.fullmatch(path)
    if detail:
        ref = _find_run(server, urllib.parse.unquote(detail.group(1)))
        return {'run_id': ref['run_id'], **runs.run_detail(ref)}
    raise HttpError(404, 'no such route')

class _Server(http.server.ThreadingHTTPServer):
    '''Threaded server bound to 127.0.0.1 with no address reuse, so a second instance fails loudly.'''

    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self) -> None:
        # HTTPServer.server_bind resolves the FQDN, which a fixed loopback address does not need.
        socketserver.TCPServer.server_bind(self)
        self.server_name = str(self.server_address[0])
        self.server_port = int(self.server_address[1])


class _Handler(http.server.BaseHTTPRequestHandler):
    '''One request: guard, then route. Every response carries security_headers().'''

    server_version = 'SimplicioLive'
    sys_version = ''

    def log_message(self, format: str, *args: Any) -> None:
        return  # the dashboard polls constantly; keep the terminal quiet

    def do_GET(self) -> None:
        self._dispatch()

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

    def _dispatch(self) -> None:
        raw_path, _, raw_query = self.path.partition('?')
        query = {key: values[0] for key, values in urllib.parse.parse_qs(raw_query).items()}
        status = guard(self.command, raw_path, self.headers, query, self.server.token, self.server.server_port)
        if status != 200:
            self._send_json(status, {'error': HTTPStatus(status).phrase})
            return
        try:
            self._route(raw_path, query)
        except HttpError as exc:
            self._send_json(exc.status, {'error': exc.message})
        except runs.ArtifactError as exc:
            self._send_json(exc.status, {'error': exc.__class__.__name__})

    def _route(self, raw_path: str, query: dict[str, str]) -> None:
        if raw_path.startswith('/static/'):
            self._static(raw_path[len('/static/'):])
            return
        if raw_path == '/':
            self._send(200, (STATIC_DIR / 'live' / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            return
        events = _EVENTS_RE.fullmatch(raw_path)
        if events:
            self._stream(urllib.parse.unquote(events.group(1)), query)
            return
        artifact = _ARTIFACT_RE.fullmatch(raw_path)
        if artifact:
            self._artifact(urllib.parse.unquote(artifact.group(1)), artifact.group(2))
            return
        self._send_json(200, _api(self.server, raw_path, query))

    def _static(self, encoded: str) -> None:
        rel = urllib.parse.unquote(encoded)
        if any(part in ('', '.', '..') for part in rel.split('/')) or '\\' in rel or '\x00' in rel:
            raise HttpError(403, 'forbidden path')
        ctype = STATIC_TYPES.get(os.path.splitext(rel)[1].lower())
        if ctype is None:
            raise HttpError(404, 'no such file')
        root = STATIC_DIR.resolve()
        try:
            target = (root / rel).resolve(strict=True)
        except (OSError, RuntimeError):
            raise HttpError(404, 'no such file') from None
        if root not in target.parents or not target.is_file():
            raise HttpError(404, 'no such file')
        self._send(200, target.read_bytes(), ctype)

    def _artifact(self, run_id: str, rel: str) -> None:
        ref = _find_run(self.server, run_id)
        data = runs.read_artifact(ref['run_dir'], rel)  # rel stays encoded: read_artifact decodes it once
        ctype = mimetypes.guess_type(urllib.parse.unquote(rel))[0] or 'application/octet-stream'
        if ctype in ('text/html', 'image/svg+xml'):  # served as text, never as an active document
            ctype = 'text/plain'
        if ctype.startswith('text/'):
            ctype += '; charset=utf-8'
        self._send(200, data, ctype)

    def _stream(self, run_id: str, query: dict[str, str]) -> None:
        cursor = _cursor(query, self.headers)
        ref = _find_run(self.server, run_id)
        tail = EventTail(Path(ref['run_dir']) / EVENTS_FILE, terminal=_is_terminal(ref))
        watch = alerts.AlertWatch()

        def receipt_ready() -> bool:
            return _receipt_ready(ref)

        self._start(200, 'text/event-stream; charset=utf-8')
        heartbeat = self.server.heartbeat_seconds
        try:
            self.wfile.write(('retry: %d\n\n' % RETRY_MS).encode('utf-8'))
            # The watch reads the stream from its first event, so the snapshot covers history the client already has.
            history = tail.poll()
            self._write_events(history, cursor)
            watch.update(history, _now_ms(), receipt_ready)
            self._write_frame('alert_snapshot', {'alerts': watch.snapshot()})
            last_write = time.monotonic()
            while not self.server.stop_event.is_set():
                new = tail.poll()
                self._write_events(new, cursor)
                raised, cleared = watch.update(new, _now_ms(), receipt_ready)
                for alert in raised:
                    self._write_frame('alert_raised', alert)
                for alert_id in cleared:
                    self._write_frame('alert_cleared', {'id': alert_id})
                if new or raised or cleared:
                    last_write = time.monotonic()
                if time.monotonic() - last_write >= heartbeat:
                    self.wfile.write(b': heartbeat\n\n')
                    last_write = time.monotonic()
                time.sleep(min(tail.next_delay(), heartbeat))
        except OSError:
            return  # the client went away

    def _write_events(self, events: list[dict[str, Any]], cursor: int) -> None:
        for event in events:
            if event['seq'] <= cursor:
                continue
            data = json.dumps(event, separators=(',', ':'), default=str)
            self.wfile.write(('id: %d\ndata: %s\n\n' % (event['seq'], data)).encode('utf-8'))

    def _write_frame(self, name: str, payload: Any) -> None:
        data = json.dumps(payload, separators=(',', ':'), default=str)
        self.wfile.write(('event: %s\ndata: %s\n\n' % (name, data)).encode('utf-8'))

    def _start(self, status: int, ctype: str, length: int | None = None) -> None:
        self.send_response(status)
        for name, value in security_headers().items():
            self.send_header(name, value)
        self.send_header('Content-Type', ctype)
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self._start(status, ctype, len(body))
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload, default=str).encode('utf-8'), 'application/json; charset=utf-8')

class ServerHandle:
    '''A running server. ``port`` is the bound port; ``stop()`` ends streams, the listener and the thread.'''

    def __init__(self, server: Any, thread: threading.Thread) -> None:
        self._server = server
        self._thread = thread
        self.port: int = server.server_port

    def wait(self) -> None:
        while self._thread.is_alive():
            self._thread.join(1.0)

    def stop(self) -> None:
        self._server.stop_event.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(5.0)


def start(repo_root: Any, host: str = HOST, port: int = 0, token: str = '',
          heartbeat_seconds: float = HEARTBEAT_SECONDS) -> ServerHandle:
    '''Serve one repo root or several on 127.0.0.1:``port`` (0 picks a free port) in a daemon thread.

    Raises OSError with EADDRINUSE when the port is taken.
    '''
    if host != HOST:
        raise ValueError('the dashboard binds 127.0.0.1 only')
    if not token:
        raise ValueError('a token is required')
    roots = [repo_root] if isinstance(repo_root, (str, os.PathLike)) else list(repo_root)
    server = _Server((HOST, port), _Handler)
    server.repos = tuple(str(Path(root)) for root in roots)
    server.token = token
    server.started_at = time.monotonic()
    server.stop_event = threading.Event()
    server.heartbeat_seconds = heartbeat_seconds
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
    thread.start()
    return ServerHandle(server, thread)


def _request(port: int, method: str, path: str, headers: Mapping[str, str] | None = None) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection(HOST, port, timeout=5)
    try:
        conn.request(method, path, headers=dict(headers or {}))
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def probe_holder(port: int) -> str:
    '''What answers on the port: a dashboard reports its pid and version on /api/health.'''
    try:
        status, body = _request(port, 'GET', '/api/health', {'Host': '%s:%d' % (HOST, port)})
    except (OSError, http.client.HTTPException):
        return 'no HTTP answer on the port'
    try:
        info = json.loads(body)
    except ValueError:
        info = None
    if status == 200 and isinstance(info, dict) and 'pid' in info:
        return 'simplicio dashboard pid %s, version %s' % (info['pid'], info.get('version'))
    return 'another service answered HTTP %d' % status


def selftest() -> int:
    '''Start on a free port over an empty repo, check the gate and one read route, then stop.'''
    auth_token = secrets.token_urlsafe(16)
    auth = {'Authorization': 'Bearer ' + auth_token}
    cases = [
        ('health', 'GET', '/api/health', {}, 200),
        ('runs without token', 'GET', '/api/runs', {}, 401),
        ('runs with token', 'GET', '/api/runs', auth, 200),
        ('foreign host', 'GET', '/api/health', {'Host': 'evil.example'}, 403),
        ('mutating method', 'POST', '/api/runs', auth, 405),
    ]
    bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        handle = start(tmp, token=auth_token)
        try:
            for name, method, path, headers, want in cases:
                got, _ = _request(handle.port, method, path, headers)
                bad += got != want
                print('selftest %-20s got %d want %d %s' % (name, got, want, 'ok' if got == want else 'FAIL'))
        finally:
            handle.stop()
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='simplicio_loop.dashboard.server',
                                     description='Simplicio Live dashboard server: read-only, 127.0.0.1 only.')
    parser.add_argument('--port', type=int, default=8765, help='TCP port on 127.0.0.1 (0 picks a free port)')
    parser.add_argument('--repo', action='append', help='repository root to watch; repeatable (default: current directory)')
    parser.add_argument('--host', default=HOST, help='bind address; only 127.0.0.1 is accepted')
    parser.add_argument('--token', default='', help='access token (default: a random one, printed at start)')
    parser.add_argument('--selftest', action='store_true', help='check the gate and one read route, then exit')
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.host != HOST:
        parser.error('--host must be 127.0.0.1')
    token = args.token or secrets.token_urlsafe(24)
    try:
        handle = start(args.repo or [os.getcwd()], port=args.port, token=token)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print('simplicio-live: port %d is in use on %s; holder: %s'
              % (args.port, HOST, probe_holder(args.port)), file=sys.stderr)
        return 3
    print('simplicio-live: http://%s:%d/?t=%s' % (HOST, handle.port, token), flush=True)
    try:
        handle.wait()
    except KeyboardInterrupt:
        pass
    finally:
        handle.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
