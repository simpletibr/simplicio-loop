'''Contract tests of the Langfuse view of one run (issue #1610).

``simplicio_loop.dashboard.langfuse_view.panel(ref)`` reads only local files: the default branch's loop.toml (through git),
the exporter's outbox, dead letters and ledger, the run's execution report and events. It never opens a socket and never
reads a credential. Real exporter cycles (``export_once`` with a stub ``send``) fill the ledger, so the comparison runs
against what the exporter really recorded.
'''
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from simplicio_loop.langfuse_export.config import load_config
from simplicio_loop.langfuse_export.exporter import export_once
from simplicio_loop.langfuse_export.queue import Outbox
from simplicio_loop.langfuse_export.transport import Result

RUN_ID = 'run-1610-fixture'
OTHER_RUN = 'run-1610-other'
HOST = 'https://langfuse.example.test'
SECRET = 'sk-lf-canary-1610-do-not-leak'
PUBLIC = 'pk-lf-canary-1610-do-not-leak'
T0 = 1_800_000_000
OK = Result(ok=True, retryable=False, status=200, error='')
RETRY = Result(ok=False, retryable=True, status=503, error='503')
# sha256 of "trace\x1f<run id>" cut to 32 hex: pinned so a changed derivation (or a link built from another id) is caught.
TRACE_ID = hashlib.sha256(('trace\x1f' + RUN_ID).encode()).hexdigest()[:32]
GIT_ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@example.test', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@example.test', 'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '/')}


def _view():
    from simplicio_loop.dashboard import langfuse_view
    return langfuse_view


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, env=GIT_ENV)


def _report(run_id: str = RUN_ID, tokens_in: int = 1200) -> dict[str, Any]:
    return {'schema': 'simplicio.execution-report/v1', 'run_id': run_id, 'repo': '/work/repo', 'status': 'CLOSED',
            'started_at_unix': T0, 'finished_at_unix': T0 + 120, 'wall_ms': 120_000,
            'tasks': [{'task_id': 'T1', 'wall_ms': 90_000, 'outcome': 'COMPLETE',
                       'tokens': {'tokens_in': tokens_in, 'tokens_out': 340, 'source': 'cli_measured'},
                       'agent': {'model': 'claude-sonnet-5-5'}}],
            'consolidated': {}}


def _event(seq: int, kind: str, payload: dict[str, Any], run_id: str = RUN_ID) -> dict[str, Any]:
    return {'schema': 'simplicio.dashboard-event/v1', 'event_id': 'evt-%d' % seq, 'seq': seq,
            'ts': '2026-10-09T10:00:%02dZ' % seq, 'run_id': run_id, 'task_id': 'T1', 'scope': 'loop', 'source': 'runner',
            'kind': kind, 'phase': 'verify', 'lane': None, 'iteration': 1, 'severity': 'info', 'payload': payload,
            'refs': [], 'producer_version': 'test'}


def _write_events(run_dir: Path, gates: dict[str, bool]) -> None:
    lines = [_event(i + 1, 'gate_evaluated', {'gate': name, 'passed': passed}) for i, (name, passed) in enumerate(gates.items())]
    (run_dir / 'events.jsonl').write_text('\n'.join(json.dumps(line) for line in lines) + '\n', encoding='utf-8')


def make_repo(tmp_path: Path, toml: str | None, *, report: dict[str, Any] | None = None,
              gates: dict[str, bool] | None = None, run_id: str = RUN_ID) -> dict[str, Any]:
    '''A git repo whose first commit holds loop.toml, plus one run directory; returns the dashboard run ref.'''
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    base = repo / '.simplicio-loop'
    base.mkdir()
    if toml is not None:
        (base / 'loop.toml').write_text(toml, encoding='utf-8')
    (repo / 'README.md').write_text('x\n', encoding='utf-8')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-q', '-m', 'init')
    run_dir = base / 'loop-runs' / run_id
    run_dir.mkdir(parents=True)
    (run_dir / 'state.json').write_text(json.dumps({'run_id': run_id, 'status': 'running'}), encoding='utf-8')
    if report is not None:
        reports = base / 'runtime' / 'execution-reports'
        reports.mkdir(parents=True)
        (reports / ('%s.json' % report['run_id'])).write_text(json.dumps(report), encoding='utf-8')
    if gates is not None:
        _write_events(run_dir, gates)
    return {'repo': str(repo), 'run_id': run_id, 'run_dir': run_dir}


def on(host: str = HOST, **extra: Any) -> str:
    lines = ['langfuse_enabled = true', 'langfuse_host = "%s"' % host]
    lines += ['%s = %s' % (key, json.dumps(value)) for key, value in extra.items()]
    return '\n'.join(lines) + '\n'


def lf_dir(ref: dict[str, Any]) -> Path:
    return Path(ref['repo']) / '.simplicio-loop' / 'langfuse'


def outbox(ref: dict[str, Any]) -> Outbox:
    return Outbox(lf_dir(ref) / 'queue', lf_dir(ref) / 'dead')


def export(ref: dict[str, Any], send=lambda kind, body: OK, now: float = float(T0 + 600)) -> dict[str, Any]:
    config = load_config({'langfuse_enabled': True, 'langfuse_host': HOST, 'langfuse_batch_seconds': 60}, env={})
    return export_once(Path(ref['repo']), config=config, env={}, run_dir=ref['run_dir'], now=now, send=send, force=True)


# --- AC: desligado ---------------------------------------------------------------------------------------------------

OFF = {'schema': 'simplicio.dashboard-langfuse/v1', 'chip': {'state': 'off', 'label': 'desligado', 'reason': None}}


@pytest.mark.parametrize('toml', [None, '', 'langfuse_enabled = false\n',
                                   'langfuse_enabled = false\nlangfuse_host = "http://evil.example"\n', 'verify = "x"\n'])
def test_off_is_only_the_chip_with_no_link_queue_or_scores(tmp_path, toml):
    ref = make_repo(tmp_path, toml, report=_report(), gates={'tests': True})
    export(ref)  # even with exporter files on disk, an off loop.toml shows nothing but the chip
    assert _view().panel(ref) == OFF


def test_a_directory_that_is_not_a_git_repo_is_off_not_an_error(tmp_path):
    run_dir = tmp_path / 'plain' / '.simplicio-loop' / 'loop-runs' / RUN_ID
    run_dir.mkdir(parents=True)
    ref = {'repo': str(tmp_path / 'plain'), 'run_id': RUN_ID, 'run_dir': run_dir}
    assert _view().panel(ref) == OFF


# --- AC: link correto -------------------------------------------------------------------------------------------------

def test_trace_link_uses_the_loop_toml_host_and_the_deterministic_trace_id(tmp_path):
    ref = make_repo(tmp_path, on())
    trace = _view().panel(ref)['trace']
    assert trace['id'] == TRACE_ID
    assert trace['url'] == '%s/trace/%s' % (HOST, TRACE_ID)


def test_the_link_of_another_run_differs_and_a_trailing_slash_in_the_host_is_dropped(tmp_path):
    ref = make_repo(tmp_path, on(HOST + '/'), run_id=OTHER_RUN)
    trace = _view().panel(ref)['trace']
    assert trace['id'] != TRACE_ID
    assert trace['url'] == '%s/trace/%s' % (HOST, trace['id'])


def test_loopback_http_host_is_accepted(tmp_path):
    ref = make_repo(tmp_path, on('http://localhost:3000'))
    assert _view().panel(ref)['trace']['url'] == 'http://localhost:3000/trace/%s' % TRACE_ID


def test_no_host_in_loop_toml_uses_the_exporter_default_host(tmp_path):
    ref = make_repo(tmp_path, 'langfuse_enabled = true\n')
    assert _view().panel(ref)['trace']['url'] == 'https://cloud.langfuse.com/trace/%s' % TRACE_ID


@pytest.mark.parametrize('host', ['http://langfuse.example.test', 'ftp://langfuse.example.test', 'langfuse.example.test', 'https://'])
def test_a_host_that_fails_the_exporter_check_is_an_error_chip_without_link_or_host(tmp_path, host):
    ref = make_repo(tmp_path, on(host))
    view = _view().panel(ref)
    assert view['chip']['state'] == 'error' and view['chip']['label'] == 'erro'
    assert 'https' in view['chip']['reason']
    assert view['trace']['url'] is None
    assert 'langfuse.example.test' not in json.dumps(view)


def test_the_environment_host_override_does_not_change_the_link(tmp_path, monkeypatch):
    monkeypatch.setenv('LANGFUSE_HOST', 'https://other-host.example.test')
    ref = make_repo(tmp_path, on())
    assert _view().panel(ref)['trace']['url'].startswith(HOST + '/trace/')


def test_loop_toml_comes_from_the_default_branch_not_the_working_tree(tmp_path):
    ref = make_repo(tmp_path, on())
    path = Path(ref['repo']) / '.simplicio-loop' / 'loop.toml'
    # a plan edits the clone's loop.toml after the commit: neither the host nor the switch may follow it
    path.write_text(on('https://attacker.example.test'), encoding='utf-8')
    assert _view().panel(ref)['trace']['url'] == '%s/trace/%s' % (HOST, TRACE_ID)
    path.write_text('langfuse_enabled = false\n', encoding='utf-8')
    assert _view().panel(ref)['chip']['state'] != 'off'


def test_a_bad_value_in_loop_toml_is_an_error_not_off(tmp_path):
    ref = make_repo(tmp_path, 'langfuse_enabled = true\nlangfuse_batch_seconds = 0\n')
    view = _view().panel(ref)
    assert view['chip']['state'] == 'error' and 'langfuse_batch_seconds' in view['chip']['reason']


def test_unparseable_loop_toml_is_an_error_chip(tmp_path):
    ref = make_repo(tmp_path, 'langfuse_enabled = = true\n')
    assert _view().panel(ref)['chip']['state'] == 'error'


# --- chip e fila --------------------------------------------------------------------------------------------------------

def test_empty_queue_is_em_dia_never_enviando(tmp_path):
    ref = make_repo(tmp_path, on())
    view = _view().panel(ref, now=time.time())
    assert view['chip'] == {'state': 'ok', 'label': 'em dia', 'reason': None}
    assert view['queue'] == 0


def test_queued_items_are_enviando_and_counted(tmp_path):
    ref = make_repo(tmp_path, on())
    for _ in range(3):
        outbox(ref).enqueue('traces', {'x': 1})
    view = _view().panel(ref, now=time.time() + 1)
    assert view['chip'] == {'state': 'sending', 'label': 'enviando', 'reason': None}
    assert view['queue'] == 3


def test_the_oldest_item_older_than_two_batch_windows_is_atrasado_with_its_minutes(tmp_path):
    ref = make_repo(tmp_path, on(langfuse_batch_seconds=60))
    outbox(ref).enqueue('traces', {'x': 1})
    late = _view().panel(ref, now=time.time() + 10 * 60 + 5)
    assert late['chip'] == {'state': 'late', 'label': 'atrasado 10 min', 'reason': None}
    assert late['queue'] == 1


def test_lateness_starts_exactly_at_two_windows(tmp_path):
    ref = make_repo(tmp_path, on(langfuse_batch_seconds=100))
    path = outbox(ref).enqueue('traces', {'x': 1})
    path.rename(path.with_name('%020d-aaaaaaaa.traces.json' % (T0 * 10**9)))  # an exact integer second: no float noise at the edge
    assert _view().panel(ref, now=T0 + 199)['chip']['state'] == 'sending'
    assert _view().panel(ref, now=T0 + 200)['chip']['state'] == 'late'


def test_a_dead_letter_is_an_error_with_its_count(tmp_path):
    ref = make_repo(tmp_path, on())
    box = outbox(ref)
    box.enqueue('traces', {'x': 1})
    box.dead_letter(box.pending()[0])
    view = _view().panel(ref, now=time.time())
    assert view['chip']['state'] == 'error' and '1' in view['chip']['reason']
    assert view['queue'] == 0


def test_a_corrupt_ledger_is_an_error_chip_and_the_panel_still_answers(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    lf_dir(ref).mkdir(parents=True)
    (lf_dir(ref) / 'ledger.json').write_text('{not json', encoding='utf-8')
    view = _view().panel(ref)
    assert view['chip']['state'] == 'error'
    assert view['trace']['id'] == TRACE_ID


def test_a_report_the_exporter_never_picked_up_is_atrasado_once_it_is_old_enough(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    fresh = _view().panel(ref, now=T0 + 120 + 30)
    assert fresh['chip']['state'] == 'ok' and fresh['trace']['exported'] is False
    late = _view().panel(ref, now=T0 + 120 + 3 * 60)
    assert late['chip'] == {'state': 'late', 'label': 'atrasado 3 min', 'reason': None}


def test_an_exported_run_is_em_dia_and_marked_exported(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    assert export(ref)['status'] == 'ok'
    view = _view().panel(ref, now=T0 + 3600)
    assert view['chip']['state'] == 'ok'
    assert view['trace']['exported'] is True
    assert view['queue'] == 0


# --- comparação com o que o exportador gravou -----------------------------------------------------------------------------

def _gate_map(compare: dict[str, Any]) -> dict[str, str]:
    return {row['name']: row['langfuse'] for row in compare['gates']}


def test_exported_gates_and_tokens_match_what_the_loop_records(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True, 'lint': False})
    export(ref)
    compare = _view().panel(ref, now=T0 + 3600)['compare']
    assert compare['state'] == 'OK'
    assert compare['gates'] == [{'name': 'tests', 'passed': True, 'langfuse': 'igual'},
                                {'name': 'lint', 'passed': False, 'langfuse': 'igual'}]
    assert compare['tokens'] == {'loop': {'input': 1200, 'output': 340}, 'langfuse': {'input': 1200, 'output': 340}, 'diverge': False}
    assert compare['cost']['state'] == 'UNVERIFIED' and compare['cost']['reason']


def test_a_gate_that_changed_after_the_export_diverges_and_the_panel_warns(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True, 'lint': False})
    export(ref)
    _write_events(Path(ref['run_dir']), {'tests': False, 'lint': False})  # the loop now says the tests failed
    compare = _view().panel(ref, now=T0 + 3600)['compare']
    assert compare['state'] == 'DIVERGE'
    assert _gate_map(compare) == {'tests': 'diverge', 'lint': 'igual'}
    assert compare['gates'][0]['passed'] is False  # the value shown is the loop's, read from the loop itself


def test_tokens_that_changed_after_the_export_diverge(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    export(ref)
    path = Path(ref['repo']) / '.simplicio-loop' / 'runtime' / 'execution-reports' / ('%s.json' % RUN_ID)
    path.write_text(json.dumps(_report(tokens_in=9999)), encoding='utf-8')
    compare = _view().panel(ref, now=T0 + 3600)['compare']
    assert compare['state'] == 'DIVERGE'
    # the ledger keeps a digest, not the old value: the Langfuse side of a diverged number cannot be shown
    assert compare['tokens'] == {'loop': {'input': 9999, 'output': 340}, 'langfuse': None, 'diverge': True}


def test_queued_and_unsent_gates_are_not_divergence(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    assert export(ref, send=lambda kind, body: RETRY)['sent'] == 0  # transient failure: everything stays queued
    queued = _view().panel(ref, now=T0 + 3600)['compare']
    assert queued['state'] == 'OK' and _gate_map(queued) == {'tests': 'na fila'}
    assert queued['tokens']['langfuse'] is None and queued['tokens']['diverge'] is False
    (tmp_path / 'never').mkdir()
    never = make_repo(tmp_path / 'never', on(), report=_report(), gates={'tests': True})
    assert _gate_map(_view().panel(never, now=T0 + 3600)['compare']) == {'tests': 'não enviado'}


def test_a_run_without_a_report_or_events_has_an_unverified_comparison(tmp_path):
    ref = make_repo(tmp_path, on())
    compare = _view().panel(ref)['compare']
    assert compare['state'] == 'UNVERIFIED' and compare['reason'] and compare['gates'] == [] and compare['tokens'] is None
    assert compare['cost']['state'] == 'UNVERIFIED'


def test_the_report_of_another_run_is_not_used(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(OTHER_RUN), gates={'tests': True})
    assert _view().panel(ref)['compare']['state'] == 'UNVERIFIED'


def test_a_report_without_a_start_time_is_an_unverified_comparison_not_a_crash(tmp_path):
    broken = _report()
    del broken['started_at_unix']
    ref = make_repo(tmp_path, on(), report=broken, gates={'tests': True})
    compare = _view().panel(ref)['compare']
    assert compare['state'] == 'UNVERIFIED' and compare['reason']


def test_unmeasured_tokens_give_no_token_comparison(tmp_path):
    report = _report()
    report['tasks'][0]['tokens']['source'] = 'estimated'
    ref = make_repo(tmp_path, on(), report=report, gates={'tests': True})
    export(ref)
    assert _view().panel(ref, now=T0 + 3600)['compare']['tokens'] is None


# --- nenhuma chave chega ao navegador; o Langfuse fora do ar não derruba nada -------------------------------------------------

def test_no_key_reaches_the_payload_even_when_keys_exist_on_disk_and_in_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('LANGFUSE_SECRET_KEY', SECRET)
    monkeypatch.setenv('LANGFUSE_PUBLIC_KEY', PUBLIC)
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    lf_dir(ref).mkdir(parents=True)
    creds = lf_dir(ref) / 'credentials.json'
    creds.write_text(json.dumps({'public_key': PUBLIC, 'secret_key': SECRET}), encoding='utf-8')
    creds.chmod(0o600)
    export(ref)
    text = json.dumps(_view().panel(ref, now=T0 + 3600))
    assert SECRET not in text and PUBLIC not in text and 'sk-lf-' not in text and 'pk-lf-' not in text


def test_the_panel_never_opens_a_connection_to_the_langfuse_host(tmp_path):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(5)
    listener.settimeout(1.0)
    accepted = []

    def watch():
        try:
            accepted.append(listener.accept())
        except OSError:
            pass

    thread = threading.Thread(target=watch)
    thread.start()
    ref = make_repo(tmp_path, on('http://127.0.0.1:%d' % listener.getsockname()[1]), report=_report(), gates={'tests': True})
    outbox(ref).enqueue('traces', {'x': 1})
    try:
        _view().panel(ref, now=time.time() + 1)
        thread.join()
    finally:
        listener.close()
    assert accepted == []


def test_panel_reads_never_write_into_the_exporter_directory(tmp_path):
    ref = make_repo(tmp_path, on(), report=_report(), gates={'tests': True})
    export(ref)
    before = sorted((str(p), p.stat().st_mtime_ns) for p in lf_dir(ref).rglob('*'))
    _view().panel(ref, now=T0 + 3600)
    assert sorted((str(p), p.stat().st_mtime_ns) for p in lf_dir(ref).rglob('*')) == before
