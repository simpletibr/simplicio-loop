'''Unit tests for simplicio_loop.dashboard.runs and simplicio_loop.dashboard.tail (dashboard TDD red).

The modules are imported inside each test so this file collects before they exist.
'''
import json
import os

import pytest


def _runs():
    from simplicio_loop.dashboard import runs
    return runs


def _tail():
    from simplicio_loop.dashboard import tail
    return tail


def _make_run(root, run_id, layout='loop-runs', **state):
    run_dir = root / '.simplicio-loop' / layout / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': 'running', 'phase': 'mapping', 'percent': 0,
            'repo': str(root), 'started_at': '2026-10-01T10:00:00Z',
            'updated_at': '2026-10-01T10:00:00Z'}
    body.update(state)
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    return run_dir


def test_discover_runs_finds_both_layouts(tmp_path):
    runs = _runs()
    _make_run(tmp_path, 'alpha', layout='loop-runs')
    _make_run(tmp_path, 'beta', layout='orchestrator/runs')
    found = runs.discover_runs(tmp_path)
    assert {r['run_id'] for r in found} == {'alpha', 'beta'}


def test_discover_runs_applies_run_id_pattern(tmp_path):
    runs = _runs()
    long_ok = 'a' * 128
    for name in ['ok.id_1', long_ok, 'a' * 129, '.hidden', '-leading', 'has space']:
        _make_run(tmp_path, name)
    found = runs.discover_runs(tmp_path)
    assert {r['run_id'] for r in found} == {'ok.id_1', long_ok}


def test_list_runs_filters_and_sorts_newest_first(tmp_path):
    runs = _runs()
    _make_run(tmp_path, 'old-done', status='done', repo='/x/a', updated_at='2026-10-01T10:00:00Z')
    _make_run(tmp_path, 'new-running', status='running', repo='/x/a', updated_at='2026-10-03T10:00:00Z')
    _make_run(tmp_path, 'mid-done-b', status='done', repo='/x/b', updated_at='2026-10-02T10:00:00Z')

    def ids(**filters):
        return [r['run_id'] for r in runs.list_runs(tmp_path, **filters)]

    assert ids() == ['new-running', 'mid-done-b', 'old-done']
    assert ids(status='done') == ['mid-done-b', 'old-done']
    assert ids(repo='/x/a') == ['new-running', 'old-done']
    assert ids(since='2026-10-02T00:00:00Z') == ['new-running', 'mid-done-b']


def test_run_summary_reports_phase_percent_duration_and_last_seq(tmp_path):
    runs = _runs()
    run_dir = _make_run(tmp_path, 'sum-1', status='done', phase='building', percent=42,
                        repo='/x/a', started_at='2026-10-01T10:00:00Z',
                        finished_at='2026-10-01T10:01:30Z', updated_at='2026-10-01T10:01:30Z')
    lines = [json.dumps({'seq': n, 'kind': 'phase_entered'}) for n in (1, 2, 3)]
    (run_dir / 'events.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    summary = runs.run_summary(run_dir)

    assert summary['phase'] == 'building'
    assert summary['percent'] == 42
    assert summary['duration_s'] == 90
    assert summary['last_seq'] == 3
    assert summary['updated_at'] == '2026-10-01T10:01:30Z'
    assert summary['repo'] == '/x/a'
    assert summary['cost_usd'] is None


def test_read_artifact_returns_bytes_inside_run(tmp_path):
    runs = _runs()
    run_dir = _make_run(tmp_path, 'art-1')
    (run_dir / 'logs').mkdir()
    (run_dir / 'logs' / 'out.txt').write_bytes(b'hello')
    assert runs.read_artifact(run_dir, 'logs/out.txt') == b'hello'


@pytest.mark.parametrize('rel', [
    '..',
    '../state.json',
    'logs/../../state.json',
    '%2e%2e/state.json',
    '%2E%2E%2Fstate.json',
    'logs%5c..%5cstate.json',
    'logs%5Cout.txt',
    '/etc/passwd',
    'nul' + chr(0) + 'byte.txt',
])
def test_read_artifact_rejects_traversal_encoding_absolute_and_nul(tmp_path, rel):
    runs = _runs()
    run_dir = _make_run(tmp_path, 'art-2')
    with pytest.raises(runs.ArtifactForbidden):
        runs.read_artifact(run_dir, rel)


def test_read_artifact_rejects_symlink_escaping_run_dir(tmp_path):
    if os.name == 'nt':
        pytest.skip('symlink escape case is POSIX-only')
    runs = _runs()
    run_dir = _make_run(tmp_path, 'art-3')
    secret = tmp_path / 'outside-secret.txt'
    secret.write_text('top secret', encoding='utf-8')
    os.symlink(secret, run_dir / 'escape.txt')
    with pytest.raises(runs.ArtifactForbidden):
        runs.read_artifact(run_dir, 'escape.txt')


def test_read_artifact_missing_file_raises_not_found(tmp_path):
    runs = _runs()
    run_dir = _make_run(tmp_path, 'art-4')
    with pytest.raises(runs.ArtifactNotFound):
        runs.read_artifact(run_dir, 'logs/missing.txt')


def test_read_artifact_oversize_raises_too_large(tmp_path):
    runs = _runs()
    run_dir = _make_run(tmp_path, 'art-5')
    with open(run_dir / 'big.log', 'wb') as fh:
        fh.truncate(runs.MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(runs.ArtifactTooLarge):
        runs.read_artifact(run_dir, 'big.log')


@pytest.mark.parametrize('raw, secret', [
    ('Authorization: Bearer abc123TOKENxyz', 'abc123TOKENxyz'),
    ('key sk-abcdefghijklmnopqrstuvwx leaked', 'sk-abcdefghijklmnopqrstuvwx'),
    ('token ghp_abcdefghijklmnopqrstuvwxyz0123456789 leaked', 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'),
    ('contact dev@example.com now', 'dev@example.com'),
    ('api_key=supersecretvalue', 'supersecretvalue'),
])
def test_redact_text_masks_each_secret_shape(raw, secret):
    runs = _runs()
    out = runs.redact_text(raw)
    assert secret not in out
    assert out != raw


def test_redact_text_leaves_plain_text_alone():
    runs = _runs()
    assert runs.redact_text('plain words 123, nothing secret') == 'plain words 123, nothing secret'


def _line(seq):
    return json.dumps({'seq': seq, 'kind': 'phase_entered'}) + '\n'


def test_tail_holds_partial_last_line_until_newline(tmp_path):
    tail = _tail()
    path = tmp_path / 'events.jsonl'
    full = json.dumps({'seq': 2, 'kind': 'phase_entered'})
    path.write_text(_line(1) + full[:-1], encoding='utf-8')
    reader = tail.EventTail(path)
    assert [e['seq'] for e in reader.poll()] == [1]
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(full[-1:] + '\n')
    assert [e['seq'] for e in reader.poll()] == [2]


def test_tail_detects_rotation_by_inode_change(tmp_path):
    tail = _tail()
    path = tmp_path / 'events.jsonl'
    path.write_text(_line(1), encoding='utf-8')
    reader = tail.EventTail(path)
    assert [e['seq'] for e in reader.poll()] == [1]
    os.replace(path, tmp_path / 'events.jsonl.1')
    path.write_text(_line(2), encoding='utf-8')
    assert [e['seq'] for e in reader.poll()] == [2]


def test_tail_truncation_resets_offset(tmp_path):
    tail = _tail()
    path = tmp_path / 'events.jsonl'
    path.write_text(_line(1) + _line(2), encoding='utf-8')
    reader = tail.EventTail(path)
    assert [e['seq'] for e in reader.poll()] == [1, 2]
    path.write_text(json.dumps({'seq': 3}) + '\n', encoding='utf-8')
    assert [e['seq'] for e in reader.poll()] == [3]


def test_tail_skips_duplicate_seq(tmp_path):
    tail = _tail()
    path = tmp_path / 'events.jsonl'
    path.write_text(_line(1) + _line(2), encoding='utf-8')
    reader = tail.EventTail(path)
    assert [e['seq'] for e in reader.poll()] == [1, 2]
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(_line(2) + _line(3))
    assert [e['seq'] for e in reader.poll()] == [3]
