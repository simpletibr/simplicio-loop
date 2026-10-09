'''The per-run summary memo of /api/runs (#1569): a run whose input files did not change is not read or parsed again, and every
change on disk (event appended, state or receipt written, run created, removed or rotated) shows in the next answer.

Cost tests count the reads and parses of the summary. Freshness tests compare the memoized answer with the uncached one after
each change. The clock and the file stamps are faked where a test needs a coarse-timestamp disk or a write inside the timestamp
tick (the racy window), which a real disk cannot be forced to produce.
'''
import json
import os
import threading
import time
import types

import pytest

from simplicio_loop.dashboard import runs

NS = 1_000_000_000
RUNS = 20


@pytest.fixture(autouse=True)
def _fresh_memo():
    runs.clear_summary_cache()
    yield
    runs.clear_summary_cache()


@pytest.fixture
def aged(monkeypatch):
    '''A clock one minute ahead of the disk: every file the test writes is far outside the racy window.'''
    monkeypatch.setattr(runs, '_now_ns', lambda: time.time_ns() + 60 * NS)


@pytest.fixture
def counted(monkeypatch):
    '''Counts of the three reads a summary is made of: state.json, the events scan and the progress build.'''
    calls = {'state': 0, 'seq': 0, 'progress': 0}
    for name, label in (('_load_state', 'state'), ('_last_seq', 'seq'), ('build_progress', 'progress')):
        def spy(*args, _real=getattr(runs, name), _label=label, **kwargs):
            calls[_label] += 1
            return _real(*args, **kwargs)
        monkeypatch.setattr(runs, name, spy)
    return calls


def _stamps(monkeypatch, mtime_ns, now_ns, ctime_ns=None):
    '''Freeze the timestamps every stat reports and the clock; the inode and the size stay real. Returns the mutable holder.'''
    holder = {'mtime': mtime_ns, 'ctime': mtime_ns if ctime_ns is None else ctime_ns, 'now': now_ns}
    real = os.lstat

    def fake(path):
        st = real(path)
        return types.SimpleNamespace(st_mode=st.st_mode, st_ino=st.st_ino, st_size=st.st_size,
                                     st_mtime_ns=holder['mtime'], st_ctime_ns=holder['ctime'])

    monkeypatch.setattr(runs, '_lstat', fake)
    monkeypatch.setattr(runs, '_now_ns', lambda: holder['now'])
    return holder


def _make_run(root, run_id, layout='loop-runs', events=0, **state):
    run_dir = root / '.simplicio-loop' / layout / run_id
    run_dir.mkdir(parents=True)
    body = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'percent': 40, 'repo': str(root),
            'started_at': '2026-10-01T10:00:00Z', 'updated_at': '2026-10-01T10:00:00Z'}
    body.update(state)
    (run_dir / 'state.json').write_text(json.dumps(body), encoding='utf-8')
    if events:
        _append(run_dir, range(1, events + 1))
    return run_dir


def _append(run_dir, seqs):
    with open(run_dir / 'events.jsonl', 'a', encoding='utf-8') as fh:
        for seq in seqs:
            fh.write(json.dumps({'seq': seq, 'kind': 'lane_progress'}) + '\n')


def _ref(run_dir, repo=''):
    return {'repo': repo, 'run_id': run_dir.name, 'run_dir': run_dir}


def _truth(run_dir, repo=''):
    '''The answer with no memo at all.'''
    return runs._summarize(run_dir, repo)


def _same_as_truth(run_dir, repo=''):
    got = runs.run_summary(_ref(run_dir, repo))
    assert got == _truth(run_dir, repo)
    return got


# ---------------------------------------------------------------- the cost of a listing

def test_a_second_listing_of_unchanged_runs_reads_and_parses_nothing(tmp_path, aged, counted):
    for index in range(RUNS):
        _make_run(tmp_path, 'run-%02d' % index, events=50)
    first = runs.list_runs(tmp_path)
    assert counted == {'state': RUNS, 'seq': RUNS, 'progress': RUNS}
    second = runs.list_runs(tmp_path)
    assert counted == {'state': RUNS, 'seq': RUNS, 'progress': RUNS}, 'the second listing read the files again'
    assert second == first and len(second) == RUNS


def test_only_the_run_that_changed_is_read_again(tmp_path, aged, counted):
    dirs = [_make_run(tmp_path, 'run-%02d' % index, events=5) for index in range(RUNS)]
    runs.list_runs(tmp_path)
    _append(dirs[7], [6])
    rows = runs.list_runs(tmp_path)
    assert counted == {'state': RUNS + 1, 'seq': RUNS + 1, 'progress': RUNS + 1}
    assert {row['run_id']: row['last_seq'] for row in rows}['run-07'] == 6


def test_a_run_written_inside_the_racy_window_is_not_trusted(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'fresh', events=3)
    _stamps(monkeypatch, mtime_ns=1_000 * NS + 123_000_000, now_ns=1_000 * NS + 124_000_000)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 2, 'a file touched 1 ms ago was served from memory'


def test_a_run_settled_longer_than_the_window_is_served_from_memory(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'quiet', events=3)
    _stamps(monkeypatch, mtime_ns=1_000 * NS + 123_000_000, now_ns=1_000 * NS + 123_000_000 + runs.RACY_NS)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 1


def test_whole_second_timestamps_get_the_coarse_window(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'coarse', events=3)
    holder = _stamps(monkeypatch, mtime_ns=1_000 * NS, now_ns=1_000 * NS + 1_500_000_000)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 2, 'a whole-second stamp 1.5 s old is still inside a 1 s or 2 s granularity tick'
    holder['now'] = 1_000 * NS + runs.RACY_COARSE_NS
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 3, 'once outside the coarse window the run is stored and then served from memory'


def test_a_timestamp_in_the_future_is_not_trusted(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'skewed', events=3)
    _stamps(monkeypatch, mtime_ns=2_000 * NS + 7, now_ns=1_000 * NS)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 2


# ---------------------------------------------------------------- freshness: every change on disk shows

def test_an_appended_event_shows_in_the_next_answer(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'grow', events=10)
    assert _same_as_truth(run_dir)['last_seq'] == 10
    _append(run_dir, [11])
    assert _same_as_truth(run_dir)['last_seq'] == 11


def test_appends_are_seen_one_after_another_on_a_settled_clock(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'live', events=1)
    for seq in range(2, 40):
        _append(run_dir, [seq])
        assert runs.run_summary(_ref(run_dir))['last_seq'] == seq


def test_a_replaced_state_file_shows(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'swap', events=3)
    assert _same_as_truth(run_dir)['status'] == 'running'
    tmp = run_dir / 'state.json.tmp'
    tmp.write_text(json.dumps({'run_id': 'swap', 'status': 'failed', 'phase': 'blocked', 'repo': 'r'}), encoding='utf-8')
    os.replace(tmp, run_dir / 'state.json')
    got = _same_as_truth(run_dir)
    assert got['status'] == 'failed' and got['phase'] == 'blocked'


def test_a_same_size_rewrite_that_restores_the_mtime_still_shows(tmp_path, aged):
    '''The ctime cannot be set from user space, so restoring size and mtime does not hide a rewrite.'''
    run_dir = _make_run(tmp_path, 'quiet', status='done')
    path = run_dir / 'state.json'
    before = path.stat()
    assert _same_as_truth(run_dir)['status'] == 'done'
    path.write_text(path.read_text(encoding='utf-8').replace('"done"', '"fail"'), encoding='utf-8')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns)
    assert _same_as_truth(run_dir)['status'] == 'fail'


def test_a_change_of_size_alone_shows_on_a_disk_with_coarse_timestamps(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path, 'coarse-disk', events=10)
    _stamps(monkeypatch, mtime_ns=1_000 * NS, now_ns=1_000 * NS + 60 * NS)
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 10
    _append(run_dir, [11])
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 11


def test_a_same_size_rewrite_inside_the_timestamp_tick_shows(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path, 'tick', status='done')
    _stamps(monkeypatch, mtime_ns=1_000 * NS + 5_000_000, now_ns=1_000 * NS + 6_000_000)
    assert runs.run_summary(_ref(run_dir))['status'] == 'done'
    path = run_dir / 'state.json'
    path.write_text(path.read_text(encoding='utf-8').replace('"done"', '"fail"'), encoding='utf-8')
    assert runs.run_summary(_ref(run_dir))['status'] == 'fail'


def test_a_replaced_file_of_the_same_size_shows_on_a_disk_with_coarse_timestamps(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path, 'replaced', status='done')
    _stamps(monkeypatch, mtime_ns=1_000 * NS, now_ns=1_000 * NS + 60 * NS)
    assert runs.run_summary(_ref(run_dir))['status'] == 'done'
    path = run_dir / 'state.json'
    other = run_dir / 'state.json.tmp'
    other.write_text(path.read_text(encoding='utf-8').replace('"done"', '"fail"'), encoding='utf-8')
    assert other.stat().st_size == path.stat().st_size
    os.replace(other, path)
    assert runs.run_summary(_ref(run_dir))['status'] == 'fail'


def test_an_event_appended_while_the_summary_is_read_shows_in_the_next_answer(tmp_path, aged, monkeypatch):
    run_dir = _make_run(tmp_path, 'during', events=10)
    real = runs._summarize
    late = []

    def append_after_reading(*args, **kwargs):
        summary = real(*args, **kwargs)
        if not late:
            late.append(1)
            _append(run_dir, [11])
        return summary

    monkeypatch.setattr(runs, '_summarize', append_after_reading)
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 10
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 11


def _route_receipt():
    from simplicio_loop import execution_route
    body = {'schema': 'simplicio.execution-route/v1', 'route': 'direct'}
    return dict(body, receipt_sha=execution_route._stable_hash(body))


INPUT_FILES = {
    'completion-receipt.json': ({'ready': True, 'verdict': 'COMPLETE'}, lambda s: s['completion']['ready']),
    'evidence-receipt.json': ({'status': 'VERIFIED'}, lambda s: s['gates']['evidence']),
    'loop/watcher_state.json': ({'status': 'MATCH'}, lambda s: s['gates']['watcher']),
    'execution-route.json': (_route_receipt(), lambda s: s['route_receipt_status'] == 'MEASURED'),
}


@pytest.mark.parametrize('name', sorted(INPUT_FILES))
def test_every_file_the_summary_reads_invalidates_it(tmp_path, aged, name):
    body, seen = INPUT_FILES[name]
    run_dir = _make_run(tmp_path, 'receipts', events=3)
    assert not seen(_same_as_truth(run_dir))
    target = run_dir / name
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(body), encoding='utf-8')
    assert seen(_same_as_truth(run_dir)), name + ' was written and the summary did not notice'
    target.unlink()
    assert not seen(_same_as_truth(run_dir)), name + ' was removed and the summary did not notice'


def test_a_removed_events_file_resets_the_last_seq(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'gone', events=10)
    assert _same_as_truth(run_dir)['last_seq'] == 10
    (run_dir / 'events.jsonl').unlink()
    assert _same_as_truth(run_dir)['last_seq'] == 0


def test_a_rotated_event_file_shows(tmp_path, aged, monkeypatch):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    monkeypatch.setenv('SIMPLICIO_DASHBOARD_EVENTS_MAX_BYTES', '4096')
    run_dir = _make_run(tmp_path, 'rot')
    spec = {'kind': 'lane_progress', 'source': 'worker', 'phase': 'executing', 'severity': 'info',
            'payload': {'message': 'x' * 100}}
    seen = []
    for _ in range(12):
        emitter.emit_batch(run_dir, [dict(spec) for _ in range(10)], strict=True)
        seen.append(_same_as_truth(run_dir)['last_seq'])
    assert (run_dir / 'events.jsonl.1').exists(), 'the fixture never rotated the event file'
    assert seen == sorted(seen) and seen[-1] == 120


def test_a_new_run_is_listed_at_once_and_a_removed_run_is_gone(tmp_path, aged):
    first = _make_run(tmp_path, 'one', events=2)
    assert [row['run_id'] for row in runs.list_runs(tmp_path)] == ['one']
    _make_run(tmp_path, 'two', events=2)
    assert {row['run_id'] for row in runs.list_runs(tmp_path)} == {'one', 'two'}
    for child in first.iterdir():
        child.unlink()
    first.rmdir()
    assert [row['run_id'] for row in runs.list_runs(tmp_path)] == ['two']


def test_a_run_removed_and_created_again_under_the_same_id_shows_the_new_one(tmp_path, aged):
    old = _make_run(tmp_path, 'again', events=2, status='done')
    assert runs.list_runs(tmp_path)[0]['status'] == 'done'
    for child in old.iterdir():
        child.unlink()
    old.rmdir()
    _make_run(tmp_path, 'again', events=9, status='running')
    row = runs.list_runs(tmp_path)[0]
    assert (row['status'], row['last_seq']) == ('running', 9)


def test_equal_run_ids_in_two_repos_do_not_share_a_summary(tmp_path, aged, counted):
    left = _make_run(tmp_path / 'left', 'same', events=2, status='done')
    right = _make_run(tmp_path / 'right', 'same', events=7, status='failed')
    for _ in range(3):
        assert runs.run_summary(_ref(left))['last_seq'] == 2
        assert runs.run_summary(_ref(right))['last_seq'] == 7
        assert runs.run_summary(_ref(left))['status'] == 'done'
    assert counted['seq'] == 2, 'the two runs evict each other: each is read again on every turn'


def test_the_fallback_repo_of_the_ref_is_part_of_the_answer(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'norepo', events=1)
    state = json.loads((run_dir / 'state.json').read_text(encoding='utf-8'))
    state.pop('repo')
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    assert runs.run_summary(_ref(run_dir, '/repo/a'))['repo'] == '/repo/a'
    assert runs.run_summary(_ref(run_dir, '/repo/b'))['repo'] == '/repo/b'


# ---------------------------------------------------------------- the memo itself

def test_a_caller_that_edits_its_summary_does_not_change_the_next_answer(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'shared', events=3)
    first = runs.run_summary(_ref(run_dir))
    first['status'] = 'tampered'
    first['events'].append({'kind': 'tampered'})
    first['gates']['oracle'] = True
    second = runs.run_summary(_ref(run_dir))
    assert second == _truth(run_dir)
    assert second['status'] != 'tampered'


def test_the_memo_holds_a_bounded_number_of_runs(tmp_path, aged, monkeypatch):
    monkeypatch.setattr(runs, 'SUMMARY_CACHE_MAX', 4)
    for index in range(10):
        _make_run(tmp_path, 'run-%02d' % index, events=2)
    assert len(runs.list_runs(tmp_path)) == 10
    assert runs.summary_cache_size() == 4


def test_concurrent_requests_for_a_cold_run_compute_it_once(tmp_path, aged, monkeypatch):
    run_dir = _make_run(tmp_path, 'hot', events=5)
    computed = []
    real = runs._summarize

    def slow(*args, **kwargs):
        computed.append(1)
        time.sleep(0.15)
        return real(*args, **kwargs)

    monkeypatch.setattr(runs, '_summarize', slow)
    barrier = threading.Barrier(8)
    answers = []

    def poll():
        barrier.wait()
        answers.append(runs.run_summary(_ref(run_dir)))

    threads = [threading.Thread(target=poll) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(answers) == 8 and all(answer == answers[0] for answer in answers)
    assert len(computed) == 1, 'eight pollers of one cold run computed it %d times' % len(computed)


def test_the_route_serves_fresh_data_after_an_append_and_no_stale_data(tmp_path, aged):
    import urllib.request
    from simplicio_loop.dashboard import server
    run_dir = _make_run(tmp_path, 'http', events=4)
    handle = server.start(repo_root=tmp_path, host='127.0.0.1', port=0, token='memo-token-0123', heartbeat_seconds=0.2)
    try:
        def get():
            request = urllib.request.Request('http://127.0.0.1:%d/api/runs' % handle.port,
                                             headers={'Authorization': 'Bearer memo-token-0123'})
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode('utf-8'))['runs']
        assert [row['last_seq'] for row in get()] == [4]
        for seq in range(5, 25):
            _append(run_dir, [seq])
            assert [row['last_seq'] for row in get()] == [seq]
    finally:
        handle.stop()


# ---------------------------------------------------------------- audit of #1586: symlinked receipts, ordering, limits

@pytest.mark.parametrize('name', sorted(INPUT_FILES))
def test_edit_of_the_target_of_a_symlinked_receipt_shows(tmp_path, aged, name):
    '''build_progress follows a link; a stat of the link alone cannot see the target change.'''
    body, seen = INPUT_FILES[name]
    run_dir = _make_run(tmp_path, 'linked', events=3)
    target = tmp_path / 'shared.json'
    target.write_text(json.dumps({'ready': False, 'verdict': 'NO', 'status': 'x', 'match': False}), encoding='utf-8')
    link = run_dir / name
    link.parent.mkdir(exist_ok=True)
    os.symlink(target, link)
    assert not seen(_same_as_truth(run_dir))
    target.write_text(json.dumps(body), encoding='utf-8')
    assert seen(_same_as_truth(run_dir)), 'the target of the symlinked ' + name + ' changed and the summary did not'
    target.write_text(json.dumps({'ready': False}), encoding='utf-8')
    assert not seen(_same_as_truth(run_dir))


@pytest.mark.parametrize('name', sorted(INPUT_FILES))
def test_a_receipt_link_that_points_nowhere_shows_its_target_once_it_exists(tmp_path, aged, name):
    body, seen = INPUT_FILES[name]
    run_dir = _make_run(tmp_path, 'dangling', events=3)
    target = tmp_path / 'later.json'
    link = run_dir / name
    link.parent.mkdir(exist_ok=True)
    os.symlink(target, link)
    assert not seen(_same_as_truth(run_dir))
    target.write_text(json.dumps(body), encoding='utf-8')
    assert seen(_same_as_truth(run_dir))


def test_a_run_with_a_linked_input_is_computed_on_every_call(tmp_path, aged, counted):
    run_dir = _make_run(tmp_path, 'linked-cost', events=3)
    target = tmp_path / 'shared.json'
    target.write_text('{"ready": false}', encoding='utf-8')
    os.symlink(target, run_dir / 'completion-receipt.json')
    for _ in range(3):
        runs.run_summary(_ref(run_dir))
    assert counted['progress'] == 3


@pytest.mark.parametrize('where', ['_load_state', 'build_progress', '_last_seq'])
def test_a_write_in_the_middle_of_the_computation_shows_in_the_next_answer(tmp_path, aged, monkeypatch, where):
    run_dir = _make_run(tmp_path, 'mid', events=5)
    real = getattr(runs, where)
    fired = []

    def inject(*args, **kwargs):
        out = real(*args, **kwargs)
        if not fired:
            fired.append(1)
            _append(run_dir, [6])
            (run_dir / 'completion-receipt.json').write_text(json.dumps({'ready': True, 'verdict': 'COMPLETE'}), encoding='utf-8')
        return out

    monkeypatch.setattr(runs, where, inject)
    runs.run_summary(_ref(run_dir))
    assert fired
    monkeypatch.setattr(runs, where, real)
    got = _same_as_truth(run_dir)
    assert got['last_seq'] == 6 and got['completion']['ready'] is True


def test_a_same_size_rewrite_that_restores_the_mtime_in_the_middle_of_the_computation_shows(tmp_path, aged, monkeypatch):
    run_dir = _make_run(tmp_path, 'mid-same', events=5, status='done')
    path = run_dir / 'state.json'
    before = path.stat()
    real = runs._last_seq
    fired = []

    def rewrite(*args, **kwargs):
        out = real(*args, **kwargs)
        if not fired:
            fired.append(1)
            path.write_text(path.read_text(encoding='utf-8').replace('"done"', '"fail"'), encoding='utf-8')
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return out

    monkeypatch.setattr(runs, '_last_seq', rewrite)
    runs.run_summary(_ref(run_dir))
    monkeypatch.setattr(runs, '_last_seq', real)
    assert runs.run_summary(_ref(run_dir))['status'] == 'fail'


def test_an_old_mtime_with_a_recent_ctime_is_not_remembered(tmp_path, monkeypatch, counted):
    '''tar -p, rsync -t and cp -p restore the mtime; the ctime then is the time of the copy.'''
    run_dir = _make_run(tmp_path, 'restored', events=3)
    _stamps(monkeypatch, mtime_ns=1_000 * NS + 123_000_000, ctime_ns=5_000 * NS + 50_000_000, now_ns=5_000 * NS + 51_000_000)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 2


def test_the_window_edge_is_inclusive_and_one_nanosecond_less_is_not_trusted(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'edge', events=3)
    holder = _stamps(monkeypatch, mtime_ns=1_000 * NS + 123_000_000, now_ns=1_000 * NS + 123_000_000 + runs.RACY_NS)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 1, 'a file exactly one window old is settled'
    runs.clear_summary_cache()
    holder['now'] -= 1
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 3, 'a file one nanosecond younger than the window is not'


def test_the_coarse_window_needs_both_timestamps_to_be_whole_seconds(tmp_path, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'fine-ctime', events=3)
    _stamps(monkeypatch, mtime_ns=1_000 * NS, ctime_ns=1_000 * NS + 5_000_000, now_ns=1_000 * NS + 5_000_000 + 150_000_000)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 1, 'a sub-second ctime shows a disk that stamps finely: the 100 ms window applies'


def test_an_exception_while_recomputing_never_serves_the_previous_summary(tmp_path, aged):
    run_dir = _make_run(tmp_path, 'raises', events=3)
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 3
    (run_dir / 'state.json').write_text(json.dumps({'run_id': 'raises', 'task_count': 'not-a-number'}), encoding='utf-8')
    for _ in range(3):
        with pytest.raises(ValueError):
            runs.run_summary(_ref(run_dir))
        with pytest.raises(ValueError):
            _truth(run_dir)


def test_the_least_recently_used_run_is_the_one_that_leaves(tmp_path, aged, monkeypatch):
    monkeypatch.setattr(runs, 'SUMMARY_CACHE_MAX', 3)
    dirs = [_make_run(tmp_path, 'e%d' % index, events=2) for index in range(5)]
    for run_dir in dirs[:3]:
        runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(dirs[0]))  # e0 is now the most recently used
    runs.run_summary(_ref(dirs[3]))  # e1, the least recently used, leaves
    kept = list(runs._SUMMARIES)
    assert os.fspath(dirs[1]) not in kept
    assert os.fspath(dirs[0]) in kept and os.fspath(dirs[3]) in kept and len(kept) == 3


def test_six_hundred_runs_are_all_served_from_memory_on_the_second_listing(tmp_path, aged, counted):
    for index in range(600):
        _make_run(tmp_path, 'run-%04d' % index, events=2)
    assert len(runs.list_runs(tmp_path)) == 600
    assert counted['seq'] == 600
    assert len(runs.list_runs(tmp_path)) == 600
    assert counted == {'state': 600, 'seq': 600, 'progress': 600}, 'a listing longer than the memo evicts every run before its turn'


def test_a_summary_over_the_byte_limit_is_not_remembered(tmp_path, aged, counted):
    run_dir = _make_run(tmp_path, 'big', events=3, technical_debts=[{'id': index, 'note': 'd' * 40} for index in range(13000)])
    assert (run_dir / 'state.json').stat().st_size > 800_000
    first = runs.run_summary(_ref(run_dir))
    assert first['technical_debt_count'] == 13000
    runs.run_summary(_ref(run_dir))
    assert counted['progress'] == 2
    assert runs._SUMMARIES[os.fspath(run_dir)].blob is None, 'a megabyte summary sits in memory'


def test_the_byte_limit_is_inclusive(tmp_path, aged, monkeypatch, counted):
    run_dir = _make_run(tmp_path, 'edge-size', events=3)
    size = len(json.dumps(_truth(run_dir)))
    counted['seq'] = 0
    monkeypatch.setattr(runs, 'SUMMARY_BLOB_MAX', size)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 1, 'a summary of exactly the limit is remembered'
    runs.clear_summary_cache()
    monkeypatch.setattr(runs, 'SUMMARY_BLOB_MAX', size - 1)
    runs.run_summary(_ref(run_dir))
    runs.run_summary(_ref(run_dir))
    assert counted['seq'] == 3, 'a summary one byte over the limit is not'


def test_the_limits_are_the_documented_ones():
    assert runs.SUMMARY_CACHE_MAX == 4096
    assert runs.SUMMARY_BLOB_MAX == 32 * 1024
