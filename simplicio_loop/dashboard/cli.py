'''Command-line front end of the Simplicio Live dashboard: ``simplicio-loop dashboard`` (issue #1401).

``main(argv)`` takes the arguments after the word ``dashboard``. It starts or reuses one loopback
server (``simplicio_loop.dashboard.server``), reports its status, stops it, writes a static snapshot,
streams one run in the terminal, or hands ``--tokens`` to the legacy token monitor.
Exit codes: 0 ok, 1 start failure, 2 usage error, unknown run, repo mismatch or no runs, 3 port in use.
'''
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from simplicio_loop import __version__, progress
from simplicio_loop.dashboard import runs, server
from simplicio_loop.dashboard.snapshot import SnapshotError, ranked_runs, write_history_snapshot, write_snapshot

DEFAULT_PORT = 8765
TOKEN_MONITOR_PORT = 9090
STATUS_SCHEMA = 'simplicio.dashboard-status/v1'
LOG_NAME = 'server.log'
STARTUP_TIMEOUT_S = 10.0
STOP_TIMEOUT_S = 3.0
_STARTUP_RE = re.compile(r'simplicio-live: http://127\.0\.0\.1:([0-9]{1,5})/\?t=([A-Za-z0-9_-]+)')


def gui_available() -> bool:
    '''True when a browser can open here: macOS and Windows have a desktop, Linux needs a display.'''
    if sys.platform in ('darwin', 'win32'):
        return True
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


def panel_url(port: int, token: str, run_id: str | None = None) -> str:
    '''Loopback panel URL with the access token, plus the run to focus when ``run_id`` is given.'''
    url = 'http://127.0.0.1:%d/?t=%s' % (port, urllib.parse.quote(token, safe=''))
    if run_id:
        url += '&run=' + urllib.parse.quote(run_id, safe='')
    return url


def pick_run(repos: list[str], run_id: str | None = None, active_only: bool = True) -> runs.RunRef | None:
    '''The run to show. ``run_id`` picks that run in any status (LookupError when unknown). Without it,
    the newest run that is not terminal; None when every run is terminal and ``active_only`` is set.'''
    rows = ranked_runs(repos)
    if run_id is not None:
        for ref, _ in rows:
            if ref['run_id'] == run_id:
                return ref
        raise LookupError('no run %s under the watched repos' % run_id)
    for ref, summary in rows:
        if not active_only or summary['status'] not in server.TERMINAL_STATUSES:
            return ref
    return None


def _state_repos(state: dict[str, Any]) -> list[str]:
    raw = state.get('repos')
    return [str(repo) for repo in raw] if isinstance(raw, list) else []


def _forget_state() -> None:
    try:
        runs.state_file_path().unlink()
    except OSError:
        pass


def _health(port: int) -> dict[str, Any] | None:
    '''The /api/health answer of a dashboard on loopback ``port``, or None when nothing healthy answers.'''
    try:
        status, body = server._request(port, 'GET', '/api/health', {'Host': '127.0.0.1:%d' % port})
        info = json.loads(body)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return info if status == 200 and isinstance(info, dict) and 'pid' in info else None


def _live(state: dict[str, Any]) -> dict[str, Any] | None:
    '''The health answer when the state file names a live dashboard whose pid matches; None otherwise.'''
    port, pid = state.get('port'), state.get('pid')
    if not isinstance(port, int) or not isinstance(pid, int) or not state.get('token'):
        return None
    info = _health(port)
    return info if info is not None and info.get('pid') == pid else None


def status_payload() -> dict[str, Any]:
    '''The ``--status`` payload. It never carries the access token; url is the tokenless loopback address.'''
    path = runs.state_file_path()
    state = runs.read_state_file(path)
    info = _live(state)
    base = {'schema': STATUS_SCHEMA, 'version': __version__, 'repos': _state_repos(state),
            'state_file': str(path) if path.exists() else None}
    if info is None:
        return dict(base, running=False, stale=bool(state), url=None, port=None, pid=None, uptime_s=None,
                    observed_runs=None)
    port = int(state['port'])
    return dict(base, running=True, stale=False, url='http://127.0.0.1:%d/' % port, port=port,
                pid=int(info['pid']), uptime_s=info.get('uptime_s'), observed_runs=info.get('observed_runs'))


def panel_hint(run_id: str | None = None) -> str | None:
    '''The panel URL (with its token) of a live dashboard, for the progress command to print; else None.'''
    try:
        state = runs.read_state_file()
        if _live(state) is None:
            return None
        return panel_url(int(state['port']), str(state['token']), run_id)
    except Exception:  # fail-open: a hint must never break the progress command
        return None


def _holder_pid(port: int) -> int | None:
    '''PID listening on loopback ``port``, read from /proc on Linux; None when it cannot be found.'''
    if not sys.platform.startswith('linux'):
        return None
    inodes = set()
    for table in ('/proc/net/tcp', '/proc/net/tcp6'):
        try:
            with open(table, encoding='utf-8') as fh:
                next(fh, None)
                for line in fh:
                    fields = line.split()
                    if fields[3] == '0A' and int(fields[1].rsplit(':', 1)[1], 16) == port:
                        inodes.add('socket:[%s]' % fields[9])
        except (OSError, ValueError, IndexError):
            continue
    if not inodes:
        return None
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        fd_dir = '/proc/%s/fd' % entry
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(fd_dir, fd)) in inodes:
                    return int(entry)
            except OSError:
                continue
    return None


def _log_tail(log: Path, lines: int = 20) -> str:
    try:
        return '\n'.join(log.read_text(encoding='utf-8', errors='replace').splitlines()[-lines:])
    except OSError:
        return ''


def _startup(log: Path) -> tuple[int, str] | None:
    '''Port and token from the server's startup line, or None before the server has printed it.'''
    try:
        match = _STARTUP_RE.search(log.read_text(encoding='utf-8', errors='replace'))
    except OSError:
        return None
    return (int(match.group(1)), match.group(2)) if match else None


def _spawn(port: int, repos: list[str], log: Path) -> subprocess.Popen:
    '''Start the server detached. The token stays out of argv: the server makes it and prints it to the log.'''
    argv = [sys.executable, '-m', 'simplicio_loop.dashboard.server', '--port', str(port)]
    for repo in repos:
        argv += ['--repo', repo]
    if os.name == 'posix':
        detach = {'start_new_session': True}
    else:
        detach = {'creationflags': getattr(subprocess, 'DETACHED_PROCESS', 0)
                  | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)}
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fd, stderr=fd, close_fds=True, **detach)
    finally:
        os.close(fd)


def _parent_pid(pid: int) -> int | None:
    '''Parent of ``pid`` on Linux, read from /proc; None when it cannot be found.'''
    try:
        with open('/proc/%d/stat' % pid, encoding='utf-8') as fh:
            return int(fh.read().rsplit(')', 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return None


def _server_pid(health: dict[str, Any] | None, spawned: int) -> int:
    '''The pid to record for the server that was just started as process ``spawned``.

    A one-file binary starts a bootloader first, and the bootloader starts the server, so Popen.pid is the
    bootloader. --stop and the reuse check compare the recorded pid with the pid that health reports, and
    --stop sends it SIGTERM. So take the reported pid only when it is a real pid (not a bool, not 1) and, on
    Linux, a child of the spawned process. Otherwise record the spawned pid.
    '''
    reported = health.get('pid') if health is not None else None
    if type(reported) is not int or reported <= 1:
        return spawned
    if reported != spawned and sys.platform.startswith('linux') and _parent_pid(reported) != spawned:
        return spawned
    return reported


def _announce(port: int, token: str, run_id: str | None, pid: int, open_browser: bool, reused: bool) -> int:
    '''Print the panel URL (with its token) on stdout, and open it when a browser can open.'''
    if reused:
        print('simplicio-live: reusing the dashboard already running (pid %d)' % pid, file=sys.stderr)
    url = panel_url(port, token, run_id)
    print('simplicio-live: ' + url, flush=True)
    if open_browser and gui_available():
        webbrowser.open(url)
    return 0


def _start_failed(code: int | None, port: int, log: Path) -> int:
    print(_log_tail(log), file=sys.stderr)
    if code == 3:
        holder = _holder_pid(port)
        who = ' by pid %d' % holder if holder else ''
        print('error: port %d is in use on 127.0.0.1%s' % (port, who), file=sys.stderr)
        return 3
    print('error: the dashboard exited with code %s before it started' % code, file=sys.stderr)
    return code if code in (1, 2) else 1


def _serve(port: int | None, repos: list[str], run_id: str | None, open_browser: bool) -> int:
    '''Start the dashboard for ``repos``, or reuse the one already running. Exit codes are in the module doc.'''
    if run_id is not None:
        try:
            pick_run(repos, run_id)
        except LookupError as exc:
            print('error: %s' % exc, file=sys.stderr)
            return 2
    state = runs.read_state_file()
    if _live(state) is not None:
        if {os.path.abspath(repo) for repo in _state_repos(state)} != set(repos):
            print('error: the dashboard running as pid %s watches other repos; run --stop first' % state['pid'],
                  file=sys.stderr)
            return 2
        if port not in (None, 0) and port != state['port']:
            print('error: the dashboard already runs on port %s; run --stop first' % state['port'], file=sys.stderr)
            return 2
        return _announce(int(state['port']), str(state['token']), run_id, int(state['pid']), open_browser, True)
    _forget_state()
    log = runs.state_file_path().parent / LOG_NAME
    log.parent.mkdir(parents=True, exist_ok=True)
    wanted = DEFAULT_PORT if port is None else port
    proc = _spawn(wanted, repos, log)
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    started = _startup(log)
    while started is None:
        if proc.poll() is not None:
            return _start_failed(proc.returncode, wanted, log)
        if time.monotonic() > deadline:
            proc.kill()
            print('error: the dashboard gave no address within %d seconds' % STARTUP_TIMEOUT_S, file=sys.stderr)
            print(_log_tail(log), file=sys.stderr)
            return 1
        time.sleep(0.05)
        started = _startup(log)
    server_port, token = started
    pid = _server_pid(_health(server_port), proc.pid)
    runs.write_state_file({'pid': pid, 'port': server_port, 'token': token, 'repos': repos})
    return _announce(server_port, token, run_id, pid, open_browser, False)


def _wait_gone(port: int) -> None:
    deadline = time.monotonic() + STOP_TIMEOUT_S
    while _health(port) is not None and time.monotonic() < deadline:
        time.sleep(0.05)


def _stop() -> int:
    '''Kill the recorded pid only when the health answer on its port reports that same pid.'''
    state = runs.read_state_file()
    port, pid = state.get('port'), state.get('pid')
    health = _health(port) if isinstance(port, int) else None
    if health is None:
        _forget_state()
        print('dashboard is not running')
        return 0
    if health.get('pid') != pid:
        print('error: port %s answers as pid %s, not the recorded pid %s; nothing was stopped'
              % (port, health.get('pid'), pid), file=sys.stderr)
        return 1
    try:
        os.kill(pid, signal.SIGTERM)  # Windows maps this to TerminateProcess
    except ProcessLookupError:
        pass  # it exited between the health check and the kill
    except OSError as exc:
        print('error: could not stop pid %s: %s' % (pid, exc), file=sys.stderr)
        return 1
    _wait_gone(port)
    _forget_state()
    print('dashboard stopped (pid %d)' % pid)
    return 0


def _status() -> int:
    print(json.dumps(status_payload(), indent=2, sort_keys=True))
    return 0


def _snapshot(out: str, repos: list[str], run_id: str | None, history: bool = False) -> int:
    try:
        path = write_history_snapshot(out, repos) if history else write_snapshot(out, repos, run_id)
    except SnapshotError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 2
    print('snapshot written: %s' % path)
    return 0


def _tui(repos: list[str], run_id: str | None) -> int:
    '''Stream one run in the terminal: the newest active run, else the newest run of any status.'''
    try:
        ref = pick_run(repos, run_id)
        if ref is None and run_id is None:
            ref = pick_run(repos, active_only=False)
    except LookupError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 2
    if ref is None:
        print('error: no runs found under %s' % ', '.join(repos), file=sys.stderr)
        return 2
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        progress.stream(ref['run_dir'], fmt='ansi', once=True)
        return 0
    try:
        _tui_live(Path(ref['run_dir']))
    except KeyboardInterrupt:
        pass
    return 0


class _Keys:
    '''Non-blocking single-key reads from a terminal; Ctrl-C keeps raising KeyboardInterrupt.'''

    def __enter__(self) -> '_Keys':
        self._saved = None
        if os.name == 'posix':
            import termios
            import tty
            fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(fd)
            tty.setcbreak(fd)  # cbreak, not raw: ISIG stays on, so Ctrl-C still interrupts
        return self

    def __exit__(self, *exc: object) -> None:
        if self._saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)

    def wait(self, seconds: float) -> str:
        '''The key pressed within ``seconds`` (lowercased), or '' on timeout.'''
        if os.name == 'posix':
            import select
            ready, _, _ = select.select([sys.stdin], [], [], seconds)
            return os.read(sys.stdin.fileno(), 1).decode('latin-1').lower() if ready else ''
        import msvcrt
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            time.sleep(0.05)
        return ''


def _enable_windows_vt() -> None:
    '''Turn on ANSI escape processing for the Windows console; fail-open (a redraw glitch beats a crash).'''
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except (AttributeError, OSError, ImportError):
        pass


def _prepare_console() -> None:
    if sys.platform == 'win32':
        _enable_windows_vt()


def _tui_live(run_dir: Path, interval: float = 0.25) -> None:
    '''Redraw the run in place until it ends or the user presses q.'''
    out, frame = sys.stdout, 0
    _prepare_console()
    out.write('\x1b[?25l')  # hide cursor; restored below
    try:
        with _Keys() as keys:
            while True:
                event = progress.build_progress(progress.load_state(run_dir), run_dir=run_dir, frame=frame)
                body = progress.render_text(event)
                try:  # a legacy console (Windows cp1252) cannot print the box glyphs
                    body.encode(getattr(out, 'encoding', None) or 'ascii')
                except (LookupError, UnicodeEncodeError):
                    body = progress.render_text(event, ascii_only=True).encode('ascii', 'replace').decode('ascii')
                out.write('\x1b[H\x1b[J' + body + '\n\nq: quit\n')
                out.flush()
                if event['status'] in ('COMPLETE', 'BLOCKED', 'CANCELLED') or keys.wait(interval) == 'q':
                    return
                frame += 1
    finally:
        out.write('\x1b[?25h')
        out.flush()


def _tokens(port: int | None, open_browser: bool, stop: bool) -> int:
    '''The legacy token monitor on its own port, looked up on cli_impl at call time.'''
    from simplicio_loop import cli_impl
    return cli_impl.dashboard(TOKEN_MONITOR_PORT if port is None else port, open_browser, stop)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('port must be a whole number from 0 to 65535') from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError('port must be a whole number from 0 to 65535')
    return port


def add_arguments(parser: argparse.ArgumentParser) -> None:
    '''Define every dashboard flag on ``parser``. cli_impl mounts these on its own dashboard subparser.'''
    parser.add_argument('--run', metavar='RUN_ID', help='run to show (default: the newest active run)')
    parser.add_argument('--repo', action='append', metavar='PATH',
                        help='repository root to watch; repeatable (default: the current directory)')
    parser.add_argument('--port', type=_port, default=None,
                        help='loopback port for the server (default: %d; 0 picks a free port)' % DEFAULT_PORT)
    parser.add_argument('--no-browser', action='store_true', help='do not open the panel in a browser')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--stop', action='store_true', help='stop the running dashboard')
    modes.add_argument('--status', action='store_true', help='print the dashboard status as JSON (never the token)')
    modes.add_argument('--snapshot', metavar='OUT',
                       help='write a static HTML snapshot of a run to OUT, without starting a server')
    parser.add_argument('--history', action='store_true',
                        help='with --snapshot: write the run history, trends and heatmap page instead of one run')
    modes.add_argument('--tui', action='store_true', help='stream a run in the terminal')
    parser.add_argument('--tokens', action='store_true',
                        help='open the legacy token monitor on port 9090; goes only with --port, --no-browser, --stop')


def run(args: argparse.Namespace) -> int:
    if args.tokens:
        if args.status or args.snapshot is not None or args.tui or args.run or args.repo:
            print('error: --tokens goes only with --port, --no-browser and --stop', file=sys.stderr)
            return 2
        return _tokens(args.port, not args.no_browser, args.stop)
    if args.history and args.snapshot is None:
        print('error: --history requires --snapshot', file=sys.stderr)
        return 2
    repos = [os.path.abspath(repo) for repo in (args.repo or [os.getcwd()])]
    if args.stop:
        return _stop()
    if args.status:
        return _status()
    if args.snapshot is not None:
        return _snapshot(args.snapshot, repos, args.run, args.history)
    if args.tui:
        return _tui(repos, args.run)
    return _serve(args.port, repos, args.run, not args.no_browser)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='simplicio-loop dashboard',
        description='Simplicio Live: the run dashboard on 127.0.0.1, read-only and token-gated.')
    add_arguments(parser)
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

