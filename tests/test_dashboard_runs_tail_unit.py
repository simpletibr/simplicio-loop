'''The incremental read of events.jsonl behind the run summary (#1569 follow-up): the last seq of a run is read from the byte offset
where the previous read stopped, so a run that keeps receiving events costs the new bytes, not the whole file.

Every way the file can change on disk must give the answer a full scan gives: appends, a half-written line, truncation, a rewrite
that grows the file back past the old offset, rotation, replacement, removal and a symlink. The oracle is the full scan, which is
``_last_seq`` with no tail, and it is compared after every random change (150 seeds) at both levels: the reader and the summary.
'''
import json
import os
import random
import time

import pytest

from simplicio_loop.dashboard import runs

NS = 1_000_000_000
SEEDS = range(150)
STEPS = 14


@pytest.fixture(autouse=True)
def _fresh_memo(monkeypatch):
    runs.clear_summary_cache()
    monkeypatch.setattr(runs, '_now_ns', lambda: time.time_ns() + 60 * NS)  # every file is settled: the tail is what is tested
    yield
    runs.clear_summary_cache()


def _run(root, run_id='run-tail'):
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'percent': 40, 'repo': str(root),
             'started_at': '2026-10-01T10:00:00Z', 'updated_at': '2026-10-01T10:00:00Z'}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    return run_dir


def _line(seq, pad=0):
    return json.dumps({'seq': seq, 'kind': 'lane_progress', 'pad': 'p' * pad}) + '\n'


def _ref(run_dir, repo=''):
    return {'repo': repo, 'run_id': run_dir.name, 'run_dir': run_dir}


def _append(run_dir, text):
    with open(run_dir / 'events.jsonl', 'a', encoding='utf-8') as fh:
        fh.write(text)


# ---------------------------------------------------------------- the cost: only the new bytes are parsed

def test_an_append_parses_only_the_new_lines(tmp_path, monkeypatch):
    run_dir = _run(tmp_path)
    _append(run_dir, ''.join(_line(seq) for seq in range(1, 5001)))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 5000
    parsed = []
    real = runs._line_seq
    monkeypatch.setattr(runs, '_line_seq', lambda line: (parsed.append(line), real(line))[1])
    _append(run_dir, _line(5001) + _line(5002))
    assert runs._last_seq(run_dir, tail) == 5002
    assert len(parsed) == 2


def test_the_summary_of_a_run_that_keeps_growing_parses_only_the_new_lines(tmp_path, monkeypatch):
    run_dir = _run(tmp_path)
    _append(run_dir, ''.join(_line(seq, pad=200) for seq in range(1, 3001)))
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 3000
    parsed = []
    real = runs._line_seq
    monkeypatch.setattr(runs, '_line_seq', lambda line: (parsed.append(line), real(line))[1])
    for seq in range(3001, 3006):
        _append(run_dir, _line(seq))
        assert runs.run_summary(_ref(run_dir))['last_seq'] == seq
    assert len(parsed) == 5


# ---------------------------------------------------------------- the cases the offset cannot see by itself

def test_a_half_written_line_is_counted_once_it_is_complete(tmp_path):
    run_dir = _run(tmp_path)
    first = _line(1)
    second = _line(2)
    _append(run_dir, first + second[:10])
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 1
    assert tail.offset == len(first), 'the offset stops at the last newline, never inside a line'
    _append(run_dir, second[10:])
    assert runs._last_seq(run_dir, tail) == 2


def test_a_rotated_file_is_read_from_its_first_byte(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, _line(1) + _line(7))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 7
    (run_dir / 'events.jsonl').rename(run_dir / 'events.jsonl.1')
    _append(run_dir, _line(1))
    assert runs._last_seq(run_dir, tail) == 1


def test_a_file_truncated_and_rewritten_past_the_old_offset_is_read_again(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, ''.join(_line(seq) for seq in range(1, 40)))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 39
    # same inode, larger size, lower highest seq: the old offset is passed, only the window before it tells the rewrite apart
    (run_dir / 'events.jsonl').write_text(''.join(_line(seq, pad=200) for seq in range(1, 21)), encoding='utf-8')
    assert runs._last_seq(run_dir, tail) == 20


def test_a_file_truncated_to_nothing_resets_the_answer(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, _line(1) + _line(9))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 9
    (run_dir / 'events.jsonl').write_text('', encoding='utf-8')
    assert runs._last_seq(run_dir, tail) == 0


def test_a_replaced_file_of_the_same_size_is_read_again(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, _line(4) + _line(5))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 5
    other = run_dir / 'events.jsonl.tmp'
    other.write_text(_line(2) + _line(3), encoding='utf-8')
    os.replace(other, run_dir / 'events.jsonl')
    assert runs._last_seq(run_dir, tail) == 3


def test_a_removed_file_gives_zero_and_a_new_one_is_read_from_the_start(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, _line(6))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 6
    (run_dir / 'events.jsonl').unlink()
    assert runs._last_seq(run_dir, tail) == 0
    _append(run_dir, _line(2))
    assert runs._last_seq(run_dir, tail) == 2


def test_a_symlinked_events_file_counts_as_no_events(tmp_path):
    run_dir = _run(tmp_path)
    _append(run_dir, _line(1) + _line(3))
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 3
    target = tmp_path / 'elsewhere.jsonl'
    target.write_text(_line(50), encoding='utf-8')
    (run_dir / 'events.jsonl').unlink()
    os.symlink(target, run_dir / 'events.jsonl')
    assert runs._last_seq(run_dir, tail) == 0 == runs._last_seq(run_dir)


# ---------------------------------------------------------------- the oracle: tail and summary against a full scan

def _random_lines(rng):
    parts = []
    for _ in range(rng.randint(1, 4)):
        roll = rng.random()
        if roll < .70:
            parts.append(_line(rng.randint(-2, 60), pad=rng.choice([0, 0, 40, 300])))
        elif roll < .75:
            parts.append('not json\n')
        elif roll < .80:
            parts.append(json.dumps({'seq': True}) + '\n')
        elif roll < .84:
            parts.append('[1, 2]\n')
        elif roll < .88:
            parts.append('\n')
        elif roll < .92:
            parts.append(json.dumps({'seq': 'x'}) + '\n')
        elif roll < .96:
            parts.append(_line(rng.randint(1, 30)).replace('\n', '\r\n'))
        else:
            parts.append(_line(rng.randint(1, 30)).replace('\n', '\r') + _line(rng.randint(1, 30)))
    return ''.join(parts)


def _text_mode_scan(run_dir):
    '''The full scan as it was before the byte-level reader: text mode, universal newlines. The reference of the oracle.'''
    path = run_dir / 'events.jsonl'
    if not path.exists() or path.is_symlink():
        return 0
    last = 0
    with path.open('r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            try:
                seq = json.loads(line).get('seq')
            except (ValueError, AttributeError):
                continue
            if isinstance(seq, int) and seq > last:
                last = seq
    return last


def _regular(path):
    return path.is_file() and not path.is_symlink()


def _change(rng, run_dir, pending):
    path = run_dir / 'events.jsonl'
    op = rng.choice(['append', 'append', 'append', 'partial', 'finish', 'truncate', 'regrow', 'rotate', 'replace', 'remove',
                     'symlink', 'rewrite_last', 'noop'])
    if op == 'append':
        _append(run_dir, _random_lines(rng))
    elif op == 'partial':
        line = _line(rng.randint(1, 80), pad=rng.choice([0, 30]))
        cut = rng.randint(1, len(line) - 1)
        pending.append(line[cut:])
        _append(run_dir, line[:cut])
    elif op == 'finish':
        if pending:
            _append(run_dir, pending.pop())
    elif op == 'truncate' and _regular(path) and path.stat().st_size:
        os.truncate(path, rng.randint(0, path.stat().st_size))
    elif op == 'regrow' and _regular(path):
        path.write_text(''.join(_line(rng.randint(0, 60), pad=300) for _ in range(rng.randint(1, 25))), encoding='utf-8')
    elif op == 'rotate' and _regular(path):
        os.replace(path, run_dir / 'events.jsonl.1')
        _append(run_dir, _random_lines(rng))
    elif op == 'replace':
        other = run_dir / 'events.jsonl.tmp'
        other.write_text(_random_lines(rng), encoding='utf-8')
        os.replace(other, path)
    elif op == 'remove' and (path.exists() or path.is_symlink()):
        path.unlink()
    elif op == 'symlink':
        if path.exists() or path.is_symlink():
            path.unlink()
        target = run_dir.parent.parent / 'elsewhere.jsonl'
        target.write_text(_random_lines(rng), encoding='utf-8')
        os.symlink(target, path)
    elif op == 'rewrite_last' and _regular(path):
        data = path.read_bytes()
        if data.endswith(b'\n'):
            start = data.rfind(b'\n', 0, len(data) - 1) + 1
            old = data[start:-1]
            # padded with spaces (valid JSON whitespace) to the old size when shorter, so a rewrite of the same size is among the cases
            new = _line(rng.randint(-2, 60)).rstrip('\n').encode('utf-8').ljust(len(old))
            path.write_bytes(data[:start] + new + b'\n')
    return op


@pytest.mark.parametrize('clock', ['settled', 'racy'])
@pytest.mark.parametrize('seed', SEEDS)
def test_the_tail_and_the_summary_equal_a_full_scan_after_every_change(tmp_path, monkeypatch, seed, clock):
    if clock == 'racy':  # the disk's own clock: the stamp is never settled, so the summary is recomputed on every call
        monkeypatch.setattr(runs, '_now_ns', time.time_ns)
    rng = random.Random(seed)
    root = tmp_path / f'repo{seed}'
    run_dir = _run(root)
    repo = str(root)
    tail = runs._Tail()
    pending = []
    for step in range(STEPS):
        _change(rng, run_dir, pending)
        want = runs._last_seq(run_dir)
        assert want == _text_mode_scan(run_dir), f'seed {seed} step {step}: the full scan drifted from universal newlines'
        assert runs._last_seq(run_dir, tail) == want, f'seed {seed} step {step}'
        truth = runs._summarize(run_dir, repo)
        assert truth['last_seq'] == want
        for _ in range(2):  # the second call is a memo hit: it must give the same answer too
            assert runs.run_summary(_ref(run_dir, repo)) == truth, f'seed {seed} step {step}'


def test_a_run_written_inside_the_racy_window_still_parses_only_the_new_lines(tmp_path, monkeypatch):
    # the disk's own clock: every write is inside the racy window, so the stamp is never settled and nothing is remembered
    monkeypatch.setattr(runs, '_now_ns', time.time_ns)
    run_dir = _run(tmp_path)
    _append(run_dir, ''.join(_line(seq, pad=200) for seq in range(1, 3001)))
    assert runs.run_summary(_ref(run_dir))['last_seq'] == 3000
    parsed = []
    real = runs._line_seq
    monkeypatch.setattr(runs, '_line_seq', lambda line: (parsed.append(line), real(line))[1])
    for seq in range(3001, 3004):
        _append(run_dir, _line(seq))
        assert runs.run_summary(_ref(run_dir))['last_seq'] == seq
    assert len(parsed) == 3


def test_a_line_rewritten_in_place_at_the_same_size_is_read_again(tmp_path):
    # the seq sits in the first bytes of a line longer than the window, so only the head of the file shows the rewrite
    run_dir = _run(tmp_path)
    path = run_dir / 'events.jsonl'
    path.write_text(json.dumps({'seq': 50, 'pad': 'p' * 5000}) + '\n', encoding='utf-8')
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 50
    path.write_text(json.dumps({'seq': 40, 'pad': 'p' * 5000}) + '\n', encoding='utf-8')
    assert runs._last_seq(run_dir, tail) == 40 == runs._last_seq(run_dir)


def test_a_lone_carriage_return_ends_a_line_as_it_did_before_the_byte_reader(tmp_path):
    # universal newlines (the reader before this change) split on a lone CR too
    run_dir = _run(tmp_path)
    _append(run_dir, '{"seq": 1}\r{"seq": 2}\n')
    tail = runs._Tail()
    assert runs._last_seq(run_dir) == 2
    assert runs._last_seq(run_dir, tail) == 2


@pytest.mark.parametrize('seed', range(40))
def test_line_ends_split_across_read_chunks_give_the_same_answer(tmp_path, monkeypatch, seed):
    monkeypatch.setattr(runs, '_READ_CHUNK', 3)  # a CR at a chunk's end, a line longer than a chunk, a CRLF cut in two
    rng = random.Random(seed)
    run_dir = _run(tmp_path, run_id=f'chunks{seed}')
    tail = runs._Tail()
    for _ in range(12):
        _append(run_dir, _random_lines(rng))
        assert runs._last_seq(run_dir, tail) == _text_mode_scan(run_dir), f'seed {seed}'


def test_a_new_inode_with_the_same_ends_is_read_again(tmp_path):
    run_dir = _run(tmp_path)
    events = run_dir / 'events.jsonl'
    events.write_text(''.join(_line(n, 600) for n in range(1, 301)), encoding='utf-8')
    tail = runs._Tail()
    assert runs._last_seq(run_dir, tail) == 300
    lines = events.read_bytes().split(b'\n')
    lines[150] = _line(50000, 596).rstrip().encode()  # the middle changes, the size, the head and the last 4 KiB do not
    replacement = run_dir / 'events.tmp'
    replacement.write_bytes(b'\n'.join(lines))
    os.utime(replacement, ns=(events.stat().st_mtime_ns,) * 2)
    os.replace(replacement, events)
    assert runs._last_seq(run_dir, tail) == runs._last_seq(run_dir) == 50000


def test_an_append_hashes_at_most_the_two_windows(tmp_path, monkeypatch):
    run_dir = _run(tmp_path)
    (run_dir / 'events.jsonl').write_text(''.join(_line(n, 600) for n in range(1, 3001)), encoding='utf-8')
    tail = runs._Tail()
    runs._last_seq(run_dir, tail)
    fed = []
    real = runs.hashlib.blake2b

    def spy(*args, **kwargs):
        digest = real(*args, **kwargs)
        update = digest.update
        fed.append(0)
        return type('Spy', (), {'update': lambda self, data: (fed.__setitem__(-1, fed[-1] + len(data)), update(data))[1],
                                'digest': lambda self: digest.digest()})()

    monkeypatch.setattr(runs.hashlib, 'blake2b', spy)
    _append(run_dir, _line(3001))
    assert runs._last_seq(run_dir, tail) == 3001
    assert fed and max(fed) <= 2 * runs.TAIL_WINDOW_BYTES


def test_an_append_reads_the_file_without_a_second_pass(tmp_path, monkeypatch):
    run_dir = _run(tmp_path)
    (run_dir / 'events.jsonl').write_text(''.join(_line(n, 600) for n in range(1, 301)), encoding='utf-8')
    tail = runs._Tail()
    runs._last_seq(run_dir, tail)
    _append(run_dir, _line(301))
    real = runs._ends_before
    calls = []
    monkeypatch.setattr(runs, '_ends_before', lambda fh, offset: (calls.append(offset), real(fh, offset))[1])
    assert runs._last_seq(run_dir, tail) == 301
    assert len(calls) == 1  # the fingerprint of the new offset comes from the consumed bytes, not from a re-read


def test_a_rewrite_between_the_read_and_the_fingerprint_is_not_certified(tmp_path, monkeypatch):
    run_dir = _run(tmp_path)
    events = run_dir / 'events.jsonl'
    events.write_text(''.join(_line(n) for n in range(10, 20)), encoding='utf-8')
    tail = runs._Tail()
    real = runs._fingerprint

    def rewrite_then_fingerprint(head, window):
        events.write_text(_line(10) * 10, encoding='utf-8')  # same inode and size, rewritten after it was counted
        return real(head, window)

    monkeypatch.setattr(runs, '_fingerprint', rewrite_then_fingerprint)
    assert runs._last_seq(run_dir, tail) == 19
    monkeypatch.setattr(runs, '_fingerprint', real)
    assert runs._last_seq(run_dir, tail) == runs._last_seq(run_dir) == 10
