'''Randomized oracle for the run summary memo (#1569): after every random change on disk the memoized listing must equal the listing
made with no memo at all. The clock is one minute ahead of the disk, so every file is settled and only the stamp can tell the
change. Receipts that are symlinks, rewrites that restore the mtime and rotated event files are among the changes.
'''
import json
import os
import random
import shutil
import time

import pytest

from simplicio_loop import execution_route
from simplicio_loop.dashboard import runs

SEEDS = range(12)
STEPS = 16
RECEIPTS = ('completion-receipt.json', 'evidence-receipt.json', 'loop/watcher_state.json', 'execution-route.json')


@pytest.fixture(autouse=True)
def _aged_and_fresh(monkeypatch):
    monkeypatch.setattr(runs, '_now_ns', lambda: time.time_ns() + 60 * 10**9)
    runs.clear_summary_cache()
    yield
    runs.clear_summary_cache()


def _state(rng, run_id, repo):
    return {'run_id': run_id, 'status': rng.choice(['running', 'done', 'blocked']), 'phase': rng.choice(['executing', 'validating', 'done']),
            'percent': rng.randint(0, 99), 'repo': repo if rng.random() < .7 else '', 'updated_at': '2026-10-01T10:%02d:00Z' % rng.randint(0, 59),
            'current_action': rng.choice(['a', 'token=abcdef123456', 'me@example.com']), 'blockers': rng.choice([[], ['b1']]),
            'task_count': rng.randint(0, 5)}


def _receipt(rng, name):
    if name == 'execution-route.json':
        body = {'schema': 'simplicio.execution-route/v1', 'route': rng.choice(['worker', 'agent']), 'reason': 'r%d' % rng.randint(0, 9)}
        if rng.random() < .7:
            body['receipt_sha'] = execution_route._stable_hash(body)
        return json.dumps(body)
    return json.dumps({'ready': rng.random() < .5, 'verdict': rng.choice(['COMPLETE', 'DRAINED', 'NO']), 'status': rng.choice(['VERIFIED', 'MATCH', 'x']),
                       'match': rng.random() < .5, 'reason_code': 'rc%d' % rng.randint(0, 9)})


def _put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        path.unlink()
    path.write_text(text, encoding='utf-8')


def _change(rng, root, shared):
    base = root / '.simplicio-loop' / 'loop-runs'
    kind = rng.choice(['append', 'same_size_state', 'truncate', 'rotate', 'newrun', 'delrun', 'recreate', 'state', 'receipt', 'receipt_rm',
                       'link_receipt', 'edit_link_target', 'corrupt', 'link_state', 'link_events', 'replace_inode'])
    existing = sorted(p for p in base.iterdir() if p.is_dir() and not p.is_symlink()) if base.exists() else []
    if kind == 'newrun' or not existing:
        run_id = 'r%02d' % rng.randint(0, 6)
        run_dir = base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        _put(run_dir / 'state.json', json.dumps(_state(rng, run_id, str(root))))
        return
    run_dir = rng.choice(existing)
    state, events = run_dir / 'state.json', run_dir / 'events.jsonl'
    if kind == 'append':
        with open(events, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'seq': rng.randint(1, 10**4), 'kind': 'k'}) + '\n')
    elif kind == 'same_size_state' and state.exists() and not state.is_symlink():
        before = state.stat().st_mtime_ns
        body = json.loads(state.read_text(encoding='utf-8'))
        percent = int(body.get('percent', 0))
        body['percent'] = percent // 10 * 10 + (percent % 10 + 1) % 10
        state.write_text(json.dumps(body), encoding='utf-8')
        os.utime(state, ns=(before, before))
    elif kind == 'truncate' and events.is_file() and not events.is_symlink():
        with open(events, 'r+', encoding='utf-8') as fh:
            fh.truncate(rng.choice([0, events.stat().st_size // 2]))
    elif kind == 'rotate' and events.is_file() and not events.is_symlink():
        os.replace(events, run_dir / 'events.jsonl.1')
        events.write_text(json.dumps({'seq': rng.randint(1, 3), 'kind': 'k'}) + '\n', encoding='utf-8')
    elif kind == 'delrun':
        shutil.rmtree(run_dir)
    elif kind == 'recreate':
        name = run_dir.name
        shutil.rmtree(run_dir)
        run_dir.mkdir()
        _put(run_dir / 'state.json', json.dumps(_state(rng, name, str(root))))
    elif kind == 'state':
        _put(state, json.dumps(_state(rng, run_dir.name, str(root))))
    elif kind == 'receipt':
        name = rng.choice(RECEIPTS)
        _put(run_dir / name, _receipt(rng, name))
    elif kind == 'receipt_rm':
        path = run_dir / rng.choice(RECEIPTS)
        if path.exists() or path.is_symlink():
            path.unlink()
    elif kind in ('link_receipt', 'edit_link_target'):
        name = rng.choice(RECEIPTS)
        target = shared / name.replace('/', '_')
        link = run_dir / name
        if kind == 'link_receipt' or not link.is_symlink():
            target.write_text(_receipt(rng, name), encoding='utf-8')
            _put(link, '')
            link.unlink()
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, link)
        else:
            target.write_text(_receipt(rng, name), encoding='utf-8')
    elif kind == 'corrupt':
        _put(run_dir / rng.choice(('state.json',) + RECEIPTS), '{not json' + 'x' * rng.randint(0, 3))
    elif kind in ('link_state', 'link_events'):
        target = shared / ('elsewhere-' + kind)
        target.write_text(json.dumps({'seq': 77, 'kind': 'k'}) + '\n', encoding='utf-8')
        link = state if kind == 'link_state' else events
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink(target, link)
    elif kind == 'replace_inode' and state.exists() and not state.is_symlink():
        before = state.stat().st_mtime_ns
        other = run_dir / 'state.json.tmp'
        other.write_bytes(state.read_bytes())
        os.utime(other, ns=(before, before))
        os.replace(other, state)


def _uncached(root):
    return {ref['run_id']: runs._summarize(ref['run_dir'], ref['repo']) for ref in runs.discover_runs(root)}


def test_the_memoized_listing_equals_the_listing_with_no_memo_after_every_change(tmp_path, monkeypatch):
    computed = []
    real = runs._summarize

    def spy(*args, **kwargs):
        computed.append(1)
        return real(*args, **kwargs)

    first_turn = second_turn = 0
    for seed in SEEDS:
        rng = random.Random(seed)
        root = tmp_path / ('repo%d' % seed)
        shared = tmp_path / ('shared%d' % seed)
        shared.mkdir()
        runs.clear_summary_cache()
        for _ in range(rng.randint(1, 3)):
            _change(rng, root, shared)
        for step in range(STEPS):
            _change(rng, root, shared)
            want = _uncached(root)
            monkeypatch.setattr(runs, '_summarize', spy)
            for turn in range(2):
                computed.clear()
                got = {row['run_id']: row for row in runs.list_runs(root)}
                assert got == want, 'seed %d step %d turn %d' % (seed, step, turn)
                if turn:
                    second_turn += len(computed)
                else:
                    first_turn += len(computed)
            monkeypatch.setattr(runs, '_summarize', real)
    assert second_turn < first_turn, 'the second listing after a change computed as much as the first (%d vs %d)' % (second_turn, first_turn)
