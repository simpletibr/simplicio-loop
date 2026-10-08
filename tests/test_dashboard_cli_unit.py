'''Unit tests for the `simplicio-loop dashboard` CLI (issue #1401, slice 3b) - TDD red.

The CLI module is imported inside each test, never at module top, so this file collects while
simplicio_loop.dashboard.cli does not exist yet. Every state file lives under tmp_path through
SIMPLICIO_DASHBOARD_STATE, and every server binds 127.0.0.1 on port 0.
'''
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / 'contracts' / 'dashboard-status' / 'v1' / 'schema.json'
TOKEN = 'unit-token-0123456789'
FLAGS = ['--run', '--repo', '--port', '--no-browser', '--stop', '--status', '--snapshot', '--tui', '--tokens']


def _cli():
    from simplicio_loop.dashboard import cli
    return cli


def _call(argv):
    '''Run the dashboard CLI in-process and return the exit code, whether it returns or exits.'''
    cli = _cli()
    try:
        code = cli.main(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    return 0 if code is None else code


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('SIMPLICIO_DASHBOARD_STATE', str(tmp_path / 'state' / 'dashboard.json'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('SIMPLICIO_MONITOR_PORT', raising=False)


def _repo(tmp_path, name):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_run(root, run_id, status='running', ts='2026-10-03T10:00:00Z', phase='intake', percent=10):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': status, 'phase': phase, 'percent': percent,
            'repo': str(root), 'started_at': ts, 'updated_at': ts}
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    emitter.emit(run_dir, 'phase_entered', source='runner', phase=phase, strict=True)
    return run_dir


def _rid(ref):
    if ref is None:
        return None
    return ref['run_id'] if isinstance(ref, dict) else ref.run_id


def test_help_lists_all_nine_flags(capsys):
    cli = _cli()
    with pytest.raises(SystemExit) as exc:
        cli.main(['--help'])
    out = capsys.readouterr().out
    assert exc.value.code == 0
    missing = [flag for flag in FLAGS if flag not in out]
    assert not missing, 'dashboard --help misses %s:\n%s' % (missing, out)


def _fake_token_monitor(monkeypatch):
    from simplicio_loop import cli_impl
    signature = inspect.signature(cli_impl.dashboard)
    calls = []

    def fake(*args, **kwargs):
        calls.append(signature.bind(*args, **kwargs).arguments)
        return 0

    monkeypatch.setattr(cli_impl, 'dashboard', fake)
    return calls


def test_tokens_runs_the_token_monitor_on_the_default_port(monkeypatch):
    _cli()
    calls = _fake_token_monitor(monkeypatch)
    assert _call(['--tokens']) == 0
    assert len(calls) == 1, calls
    assert calls[0]['port'] == 9090
    assert calls[0].get('stop', False) is False


def test_tokens_passes_stop_through(monkeypatch):
    _cli()
    calls = _fake_token_monitor(monkeypatch)
    assert _call(['--tokens', '--stop']) == 0
    assert len(calls) == 1, calls
    assert calls[0].get('stop') is True


def test_tokens_with_status_is_a_usage_error(monkeypatch):
    _cli()
    calls = _fake_token_monitor(monkeypatch)
    assert _call(['--tokens', '--status']) == 2
    assert calls == []


def test_pick_run_returns_the_newest_active_run(tmp_path):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    _make_run(repo, 'older-live', ts='2026-10-01T10:00:00Z')
    _make_run(repo, 'newer-live', ts='2026-10-03T10:00:00Z')
    _make_run(repo, 'newest-done', status='done', ts='2026-10-05T10:00:00Z')
    assert _rid(cli.pick_run([str(repo)])) == 'newer-live'


def test_pick_run_returns_none_when_every_run_is_terminal(tmp_path):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    _make_run(repo, 'finished', status='done')
    _make_run(repo, 'broke', status='failed')
    assert cli.pick_run([str(repo)]) is None


def test_pick_run_raises_lookup_error_for_an_unknown_run_id(tmp_path):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    _make_run(repo, 'real-1')
    with pytest.raises(LookupError):
        cli.pick_run([str(repo)], run_id='no-such-run')


def test_pick_run_orders_across_repos_newest_first(tmp_path):
    cli = _cli()
    first = _repo(tmp_path, 'first')
    second = _repo(tmp_path, 'second')
    _make_run(first, 'first-old', ts='2026-10-01T10:00:00Z')
    _make_run(second, 'second-mid', ts='2026-10-03T10:00:00Z')
    _make_run(first, 'first-new', ts='2026-10-06T10:00:00Z')
    assert _rid(cli.pick_run([str(first), str(second)])) == 'first-new'
    assert _rid(cli.pick_run([str(second), str(first)])) == 'first-new'


def test_panel_url_is_tokenized_and_loopback_only():
    cli = _cli()
    assert cli.panel_url(9090, 'tok') == 'http://127.0.0.1:9090/?t=tok'


def test_panel_url_appends_the_run_id():
    cli = _cli()
    assert cli.panel_url(9090, 'tok', 'run-1') == 'http://127.0.0.1:9090/?t=tok&run=run-1'


def test_status_payload_when_nothing_runs():
    cli = _cli()
    payload = cli.status_payload()
    assert payload['running'] is False
    assert payload['url'] is None
    assert payload['port'] is None
    assert payload['pid'] is None


def test_status_payload_when_running_is_tokenless(tmp_path):
    cli = _cli()
    from simplicio_loop.dashboard import runs, server
    repo = _repo(tmp_path, 'repo')
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    try:
        runs.write_state_file({'pid': os.getpid(), 'port': handle.port, 'token': TOKEN, 'repos': [str(repo)]})
        payload = cli.status_payload()
    finally:
        handle.stop()
    assert payload['running'] is True
    assert payload['port'] == handle.port
    assert payload['pid'] == os.getpid()
    assert payload['url'] and 't=' not in payload['url']
    assert TOKEN not in json.dumps(payload)


def test_status_payload_flags_a_stale_state_file(tmp_path):
    cli = _cli()
    from simplicio_loop.dashboard import runs
    dead = subprocess.Popen([sys.executable, '-c', 'pass'])
    dead.wait()
    runs.write_state_file({'pid': dead.pid, 'port': 1, 'token': TOKEN, 'repos': []})
    payload = cli.status_payload()
    assert payload['stale'] is True
    assert payload['running'] is False


def _status_schema():
    return json.loads(SCHEMA.read_text(encoding='utf-8'))


def test_status_schema_is_valid_draft_2020_12():
    _cli()
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(_status_schema())


def test_status_schema_rejects_a_payload_without_running():
    cli = _cli()
    import jsonschema
    validator = jsonschema.Draft202012Validator(_status_schema())
    payload = cli.status_payload()
    assert validator.is_valid(payload), payload
    without_running = {key: value for key, value in payload.items() if key != 'running'}
    assert not validator.is_valid(without_running)


def test_status_schema_rejects_a_stopped_payload_with_a_url():
    cli = _cli()
    import jsonschema
    validator = jsonschema.Draft202012Validator(_status_schema())
    payload = cli.status_payload()
    assert payload['running'] is False, payload
    assert not validator.is_valid(dict(payload, url='http://127.0.0.1:9090/'))


def _record_kills(monkeypatch):
    kills = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: kills.append((pid, sig)))
    return kills


def test_stop_never_kills_a_pid_that_health_does_not_report(tmp_path, monkeypatch):
    _cli()
    from simplicio_loop.dashboard import runs, server
    repo = _repo(tmp_path, 'repo')
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    kills = _record_kills(monkeypatch)
    try:
        runs.write_state_file({'pid': os.getpid() + 1, 'port': handle.port, 'token': TOKEN, 'repos': [str(repo)]})
        _call(['--stop'])
    finally:
        handle.stop()
    terminating = [pid for pid, sig in kills if sig != 0]
    assert terminating == [], kills


def test_stop_removes_the_state_file_after_a_matching_kill(tmp_path, monkeypatch):
    _cli()
    from simplicio_loop.dashboard import runs, server
    repo = _repo(tmp_path, 'repo')
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    kills = _record_kills(monkeypatch)
    state = runs.state_file_path()
    runs.write_state_file({'pid': os.getpid(), 'port': handle.port, 'token': TOKEN, 'repos': [str(repo)]})
    try:
        rc = _call(['--stop'])
    finally:
        handle.stop()
    assert rc == 0
    assert os.getpid() in [pid for pid, sig in kills if sig != 0], kills
    assert not state.exists()


def test_run_with_an_unknown_id_exits_2(tmp_path):
    _cli()
    repo = _repo(tmp_path, 'repo')
    _make_run(repo, 'real-1')
    try:
        assert _call(['--run', 'no-such-run', '--repo', str(repo), '--no-browser']) == 2
    finally:
        _call(['--stop'])


@pytest.mark.parametrize('bad_port', ['abc', '70000'])
def test_a_bad_port_value_exits_2(bad_port):
    _cli()
    assert _call(['--port', bad_port, '--no-browser']) == 2


def _record_browser(monkeypatch):
    import webbrowser
    opened = []
    monkeypatch.setattr(webbrowser, 'open', lambda url, *args, **kwargs: opened.append(url) or True)
    return opened


def test_browser_opens_when_a_gui_is_available(tmp_path, monkeypatch):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    opened = _record_browser(monkeypatch)
    monkeypatch.setattr(cli, 'gui_available', lambda: True)
    try:
        assert _call(['--repo', str(repo), '--port', '0']) == 0
    finally:
        _call(['--stop'])
    assert len(opened) == 1, opened
    assert opened[0].startswith('http://127.0.0.1:') and '?t=' in opened[0]


def test_browser_stays_closed_without_a_gui(tmp_path, monkeypatch):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    opened = _record_browser(monkeypatch)
    monkeypatch.setattr(cli, 'gui_available', lambda: False)
    try:
        assert _call(['--repo', str(repo), '--port', '0']) == 0
    finally:
        _call(['--stop'])
    assert opened == []


def test_no_browser_flag_keeps_the_browser_closed(tmp_path, monkeypatch):
    cli = _cli()
    repo = _repo(tmp_path, 'repo')
    opened = _record_browser(monkeypatch)
    monkeypatch.setattr(cli, 'gui_available', lambda: True)
    try:
        assert _call(['--repo', str(repo), '--port', '0', '--no-browser']) == 0
    finally:
        _call(['--stop'])
    assert opened == []


def test_panel_hint_is_none_without_a_state_file():
    cli = _cli()
    assert cli.panel_hint() is None


def _install_lib(tmp_path, monkeypatch):
    from scripts import install_lib
    home = tmp_path / 'home'
    monkeypatch.setattr(install_lib, 'HOME', str(home))
    return install_lib, home


def test_open_once_marker_is_skipped_when_simplicio_no_dashboard_is_set(tmp_path, monkeypatch):
    install_lib, home = _install_lib(tmp_path, monkeypatch)
    monkeypatch.setenv('SIMPLICIO_NO_DASHBOARD', '1')
    opened = _record_browser(monkeypatch)
    install_lib._open_dashboard_first_run()
    assert not (home / '.simplicio-loop' / '.dashboard_shown').exists()
    assert opened == []


def test_open_once_marker_present_means_no_reopen(tmp_path, monkeypatch):
    install_lib, home = _install_lib(tmp_path, monkeypatch)
    monkeypatch.delenv('SIMPLICIO_NO_DASHBOARD', raising=False)
    marker = home / '.simplicio-loop' / '.dashboard_shown'
    marker.parent.mkdir(parents=True)
    marker.write_text('', encoding='utf-8')
    opened = _record_browser(monkeypatch)
    install_lib._open_dashboard_first_run()
    assert opened == []
    assert marker.exists()


def test_tui_live_falls_back_to_ascii_on_a_legacy_console(tmp_path, monkeypatch):
    import io

    from simplicio_loop.dashboard import cli

    class Console(io.TextIOWrapper):
        pass

    raw = io.BytesIO()
    console = Console(raw, encoding='cp1252', errors='strict')
    run = tmp_path / 'run'
    run.mkdir()
    (run / 'state.json').write_text('{"status": "COMPLETE", "phase": "verify", "percent": 100}', encoding='utf-8')
    monkeypatch.setattr(cli.sys, 'stdout', console)
    monkeypatch.setattr(cli, '_Keys', type('K', (), {'__enter__': lambda s: s, '__exit__': lambda s, *a: None,
                                                    'wait': lambda s, t: 'q'}))
    cli._tui_live(run)
    console.flush()
    assert b'quit' in raw.getvalue()
