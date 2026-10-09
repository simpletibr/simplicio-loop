'''Load bench for the Simplicio Live server (#1400): latency and RSS/CPU under fixture runs.

Run on Windows or macOS and paste the output in issue #1400 (standard library only, no psutil):
    python -m simplicio_loop.dashboard.bench --runs 50 --events 10000 --idle-seconds 30 --json
Paste the whole JSON (or the one-line summary without --json), plus the OS name and version, CPU model and Python version.
The server runs as a thread of THIS process, so the numbers below are the server's: RSS and CPU come from the OS
(Linux /proc; macOS getrusage, where RSS is the PEAK, see rss_kind; Windows GetProcessMemoryInfo + process_time).
If a reader fails the field says UNVERIFIED with a reason; never edit the numbers. Not run by the test suite.

Fixture events go straight into each run's events.jsonl (not through the emitter, for speed).
'''
from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from simplicio_loop.dashboard import server

SCHEMA = 'simplicio.dashboard-bench/v1'
EVENT_SCHEMA = 'simplicio.dashboard-event/v1'
RUN_ROOT = '.simplicio-loop/loop-runs'
EVENTS_FILE = 'events.jsonl'
SOCKET_TIMEOUT_S = 120
SETTLE_SECONDS = 3.0  # the replay's alert pass over 10k events finishes after the drain (~0.1 s CPU)


def _read_linux() -> dict[str, Any]:
    with open('/proc/self/status', encoding='utf-8') as fh:
        rss_kib = next(int(line.split()[1]) for line in fh if line.startswith('VmRSS:'))
    with open('/proc/self/stat', encoding='utf-8') as fh:
        fields = fh.read().rsplit(')', 1)[1].split()
    cpu_s = (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK')  # utime, stime
    return {'rss_kib': rss_kib, 'cpu_s': round(cpu_s, 3), 'rss_kind': 'current'}


def _read_posix() -> dict[str, Any]:
    import resource
    usage = resource.getrusage(resource.RUSAGE_SELF)
    divisor = 1024 if sys.platform == 'darwin' else 1  # ru_maxrss: bytes on macOS, KiB elsewhere
    return {'rss_kib': int(usage.ru_maxrss) // divisor, 'cpu_s': round(usage.ru_utime + usage.ru_stime, 3),
            'rss_kind': 'peak'}


def _read_windows() -> dict[str, Any]:
    import ctypes  # lazy: Linux and macOS never load the Windows bindings
    from ctypes import wintypes

    class Counters(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t), ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t), ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t), ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t), ('PeakPagefileUsage', ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)  # type: ignore[attr-defined]
    psapi = ctypes.WinDLL('psapi', use_last_error=True)  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise OSError('GetProcessMemoryInfo failed (error %d)' % ctypes.get_last_error())
    return {'rss_kib': counters.WorkingSetSize // 1024, 'cpu_s': round(time.process_time(), 3),  # user + kernel
            'rss_kind': 'current'}


def read_process_stats() -> tuple[dict[str, Any] | None, str]:
    '''RSS in KiB and CPU seconds of this process, read by the platform's reader.

    Returns ``(stats, source)`` on success and ``(None, reason)`` when the reader fails: no number is invented.
    '''
    if sys.platform.startswith('linux'):
        reader, source = _read_linux, 'Linux /proc: VmRSS and utime + stime'
    elif sys.platform == 'darwin':
        reader, source = _read_posix, 'macOS getrusage: ru_maxrss (peak RSS) and ru_utime + ru_stime'
    elif sys.platform == 'win32':
        reader, source = _read_windows, 'Windows GetProcessMemoryInfo WorkingSetSize and process_time'
    else:
        return None, 'no RSS/CPU reader for platform %s' % sys.platform
    try:
        return reader(), source
    except (OSError, ValueError, StopIteration, IndexError, AttributeError, ImportError) as exc:
        return None, '%s reader failed: %s: %s' % (sys.platform, type(exc).__name__, exc)


def proc_stats() -> dict[str, Any] | None:
    '''RSS in KiB and CPU seconds of this process, or None when the platform's reader fails.'''
    return read_process_stats()[0]


def build_fixture(root: Path, runs: int, events: int) -> list[str]:
    '''Write ``runs`` run directories, each with ``events`` envelopes (seq 1..events); returns the run ids.'''
    base = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
    run_ids: list[str] = []
    for index in range(runs):
        run_id = 'bench-%03d' % index
        run_dir = root / RUN_ROOT / run_id
        run_dir.mkdir(parents=True)
        stamp = (base + timedelta(seconds=index)).strftime('%Y-%m-%dT%H:%M:%SZ')
        state = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'percent': 50,
                 'repo': str(root), 'started_at': stamp, 'updated_at': stamp}
        (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        with (run_dir / EVENTS_FILE).open('w', encoding='utf-8') as fh:
            for seq in range(1, events + 1):
                envelope = {'schema': EVENT_SCHEMA, 'event_id': '%s-%06d' % (run_id, seq), 'seq': seq,
                            'ts': stamp, 'run_id': run_id, 'kind': 'phase_entered', 'source': 'bench',
                            'phase': 'executing'}
                fh.write(json.dumps(envelope, separators=(',', ':')) + '\n')
        run_ids.append(run_id)
    return run_ids


def timed_get(port: int, path: str, token: str) -> dict[str, Any]:
    '''One authorized GET: status, body bytes and wall time in milliseconds.'''
    conn = http.client.HTTPConnection(server.HOST, port, timeout=SOCKET_TIMEOUT_S)
    try:
        started = time.perf_counter()
        conn.request('GET', path, headers={'Authorization': 'Bearer ' + token})
        resp = conn.getresponse()
        body = resp.read()
        elapsed = (time.perf_counter() - started) * 1000
        return {'http_status': resp.status, 'bytes': len(body), 'ms': round(elapsed, 2)}
    finally:
        conn.close()


def sse_replay(port: int, run_id: str, token: str, expected: int) -> dict[str, Any]:
    '''Replay one run from seq 0 over SSE and count the data frames received.'''
    conn = http.client.HTTPConnection(server.HOST, port, timeout=SOCKET_TIMEOUT_S)
    try:
        started = time.perf_counter()
        conn.request('GET', '/api/runs/%s/events' % run_id,
                     headers={'Authorization': 'Bearer ' + token, 'Accept': 'text/event-stream'})
        resp = conn.getresponse()
        frames = 0
        while frames < expected:
            line = resp.readline()
            if not line:
                break
            if line.startswith(b'data:'):
                frames += 1
        elapsed = (time.perf_counter() - started) * 1000
        return {'frames': frames, 'expected': expected, 'frames_match': frames == expected,
                'ms': round(elapsed, 2)}
    finally:
        conn.close()

def idle_cpu(port: int, run_id: str, token: str, seconds: float,
             settle_seconds: float = SETTLE_SECONDS) -> dict[str, Any]:
    '''CPU share of this process (server included) while one SSE stream stays open and nothing is written.

    The stream is opened and its backlog drained first, so the sample covers only the idle tail:
    ``cpu_percent`` is the utime + stime delta over ``sample_s`` wall seconds, as a share of one core.
    The sample starts ``settle_seconds`` after the drain, so the server's one-off replay work is not counted.
    '''
    conn = http.client.HTTPConnection(server.HOST, port, timeout=SOCKET_TIMEOUT_S)
    try:
        conn.request('GET', '/api/runs/%s/events' % run_id,
                     headers={'Authorization': 'Bearer ' + token, 'Accept': 'text/event-stream'})
        resp = conn.getresponse()
        resp.fp.raw._sock.settimeout(0.5)  # type: ignore[union-attr]
        try:
            while resp.readline():
                pass
        except OSError:
            pass  # backlog drained: the stream is now idle
        time.sleep(settle_seconds)
        before, reason = read_process_stats()
        started = time.perf_counter()
        time.sleep(seconds)
        wall = time.perf_counter() - started
        after, reason_after = read_process_stats()
        reason = reason if before is None else reason_after
    finally:
        conn.close()
    if before is None or after is None:
        return {'status': 'UNVERIFIED', 'sample_s': seconds, 'settle_s': settle_seconds, 'reason': 'CPU not readable: ' + reason}
    return {'status': 'MEASURED', 'sample_s': seconds, 'settle_s': settle_seconds, 'wall_s': round(wall, 3),
            'cpu_s': round(after['cpu_s'] - before['cpu_s'], 3),
            'cpu_percent': round((after['cpu_s'] - before['cpu_s']) / wall * 100, 2), 'open_streams': 1}


def run_bench(runs: int, events: int, idle_seconds: float = 30.0,
              settle_seconds: float = SETTLE_SECONDS) -> dict[str, Any]:
    '''Build the fixture, serve it, time the list, detail and SSE replay, and sample this process.'''
    root = Path(tempfile.mkdtemp(prefix='simplicio-live-bench-'))
    token = secrets.token_urlsafe(24)
    handle = None
    try:
        before, source = read_process_stats()
        run_ids = build_fixture(root, runs, events)
        handle = server.start(root, port=0, token=token)
        listing = timed_get(handle.port, '/api/runs', token)
        detail = timed_get(handle.port, '/api/runs/%s' % run_ids[0], token)
        replay = sse_replay(handle.port, run_ids[0], token, events)
        idle = idle_cpu(handle.port, run_ids[0], token, idle_seconds, settle_seconds)
        after, source_after = read_process_stats()
    finally:
        if handle is not None:
            handle.stop()
        shutil.rmtree(root, ignore_errors=True)
    if before is not None and after is not None:
        process = {'status': 'MEASURED', 'source': source, 'platform': sys.platform,
                   'before': before, 'after': after}
    else:
        process = {'status': 'UNVERIFIED', 'platform': sys.platform,
                   'reason': 'RSS and CPU not readable: ' + (source if before is None else source_after),
                   'before': None, 'after': None}
    return {'schema': SCHEMA, 'runs': runs, 'events_per_run': events, 'process': process,
            'requests': {'list_runs': listing, 'run_detail': detail, 'sse_replay': replay}, 'idle_cpu': idle}


def summary_line(result: dict[str, Any]) -> str:
    req = result['requests']
    rss = result['process']['after'] or {}
    return ('runs=%d events/run=%d list_runs=%.1fms sse_replay=%d/%d in %.1fms rss_kib=%s (%s) cpu_s=%s idle_cpu=%s%% over %ss (%s)'
            % (result['runs'], result['events_per_run'], req['list_runs']['ms'], req['sse_replay']['frames'],
               req['sse_replay']['expected'], req['sse_replay']['ms'],
               rss.get('rss_kib', 'UNVERIFIED'), rss.get('rss_kind', 'UNVERIFIED'), rss.get('cpu_s', 'UNVERIFIED'),
               result['idle_cpu'].get('cpu_percent', 'UNVERIFIED'), result['idle_cpu']['sample_s'],
               result['process']['status']))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='python -m simplicio_loop.dashboard.bench',
                                     description='Measure the dashboard server under fixture runs.')
    parser.add_argument('--runs', type=int, default=50, help='fixture runs to serve (default 50)')
    parser.add_argument('--events', type=int, default=10000, help='events per run (default 10000)')
    parser.add_argument('--idle-seconds', type=float, default=30.0, help='idle CPU sample length (default 30)')
    parser.add_argument('--settle-seconds', type=float, default=SETTLE_SECONDS,
                        help='quiet time after the replay drain, before the idle sample (default 3)')
    parser.add_argument('--json', action='store_true', help='print one JSON document')
    args = parser.parse_args(argv)
    if args.runs < 1 or args.events < 1:
        parser.error('--runs and --events must be at least 1')
    result = run_bench(args.runs, args.events, args.idle_seconds, args.settle_seconds)
    print(json.dumps(result, indent=2) if args.json else summary_line(result))
    return 0 if result['requests']['sse_replay']['frames_match'] else 1


if __name__ == '__main__':
    sys.exit(main())
