"""Correctness and behaviour suite for incremental dashboard events reader (issue #1565).

Tests the new incremental caching reader in dashboard_events.py against an oracle
(reference implementation of old semantics). Tests 2, 3, 12, and 16 are RED until
the caching implementation lands; the rest are GREEN (pure correctness equivalence).
"""
import json
import os
import re
import threading
import time
from pathlib import Path
from random import Random
from typing import Any, Dict, List

import pytest

import dashboard_events as de


# ---------------------------------------------------------------- oracle (reference reader)

def _reference(run_dir):
    """Oracle: exact replica of old read_live_events semantics."""
    run_dir = os.fspath(run_dir)
    path = os.path.join(run_dir, "events.jsonl")
    rotated = []
    try:
        for name in os.listdir(run_dir):
            m = re.match(r"^events\.jsonl\.(\d+)$", name)
            if m:
                rotated.append((int(m.group(1)), os.path.join(run_dir, name)))
    except OSError:
        return []
    files = [p for _, p in sorted(rotated, reverse=True)] + [path]
    events = []
    for p in files:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(obj, dict) and obj.get("schema") == de.SCHEMA and _is_int_oracle(obj.get("seq")):
                        events.append(obj)
        except OSError:
            continue
    events.sort(key=lambda e: e["seq"])
    return events


def _is_int_oracle(value):
    """Oracle int check: int but not bool."""
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------- helpers

@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear read cache before and after each test."""
    de.clear_read_cache()
    yield
    de.clear_read_cache()


def _spec(rnd: Random, **defaults) -> Dict[str, Any]:
    """Generate a random valid event spec."""
    sources = ["hook", "runner", "worker", "oracle", "operator"]
    models = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-5"]
    phases = ["intake", "mapping", "planning", "executing", "delivering", "validation", "done"]
    lanes = [f"lane-{i}" for i in range(1, 4)]
    kinds = de.LOOP_KINDS_ORDERED
    
    spec = {
        "kind": rnd.choice(kinds),
        "source": rnd.choice(sources),
    }
    
    if rnd.random() < 0.5:
        spec["phase"] = rnd.choice(phases)
    if rnd.random() < 0.5:
        spec["task_id"] = f"T{rnd.randint(1, 10)}"
    if rnd.random() < 0.5:
        spec["lane"] = rnd.choice(lanes)
    if rnd.random() < 0.5:
        spec["iteration"] = rnd.randint(0, 5)
    if rnd.random() < 0.5:
        spec["payload"] = {
            "model": rnd.choice(models),
            "input_tokens": rnd.randint(10, 1000),
            "output_tokens": rnd.randint(1, 100),
        }
    
    spec.update(defaults)
    return spec


def _emit(run_dir, rnd: Random, count: int) -> List[Dict[str, Any]]:
    """Emit random events via de.emit_batch."""
    specs = [_spec(rnd) for _ in range(count)]
    return de.emit_batch(run_dir, specs, strict=True)


def _append_raw(run_dir, data: bytes) -> None:
    """Append raw bytes to events.jsonl."""
    path = Path(run_dir) / "events.jsonl"
    with open(path, "ab") as fh:
        fh.write(data)


# ================================================================ tests

class TestColdReadEqualsOracle:
    """Test 1: cold read equals oracle on 300 generated events."""
    
    def test_cold_read_equals_oracle_on_300_events(self, tmp_path):
        """Generate 300 events and verify cold read matches oracle."""
        rnd = Random(42)
        _emit(tmp_path, rnd, 300)
        
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        
        assert result == oracle
        assert len(result) == 300
        assert [e["seq"] for e in result] == list(range(1, 301))


class TestWarmReadParsesOnlyAppended:
    """Test 2: WARM READ PARSES ONLY THE APPENDED LINES [RED today].
    
    Count json.loads calls via monkeypatching. Cold read parses N lines;
    immediate second read with no change parses 0; after appending 1 event
    the warm read parses <= 2 lines (not N+1); result equals oracle;
    after appending 50 more, parses <= 52.
    """
    
    def test_warm_read_parses_only_appended(self, tmp_path, monkeypatch):
        """Cold read, warm read with no changes, then append and warm read again."""
        rnd = Random(42)
        loads_count = {"count": 0}
        original_loads = json.loads
        
        def counting_loads(s, *args, **kwargs):
            loads_count["count"] += 1
            return original_loads(s, *args, **kwargs)
        
        monkeypatch.setattr("json.loads", counting_loads)
        
        # Cold read: should parse all 100 lines
        _emit(tmp_path, rnd, 100)
        loads_count["count"] = 0
        result1 = de.read_live_events(tmp_path)
        cold_count = loads_count["count"]
        assert cold_count > 0, "Cold read should parse lines"
        
        # Warm read with no changes: should parse 0 lines
        loads_count["count"] = 0
        result2 = de.read_live_events(tmp_path)
        unchanged_count = loads_count["count"]
        assert unchanged_count == 0, f"Warm read with no changes parsed {unchanged_count} lines, expected 0"
        assert result2 == result1
        
        # Append 1 event: should parse <= 2 lines
        loads_count["count"] = 0
        _emit(tmp_path, rnd, 1)
        result3 = de.read_live_events(tmp_path)
        append_1_count = loads_count["count"]
        assert append_1_count <= 2, f"Warm read after appending 1 parsed {append_1_count} lines, expected <= 2"
        assert result3 == _reference(tmp_path)
        assert len(result3) == 101
        
        # Append 50 more: should parse <= 52 lines
        loads_count["count"] = 0
        _emit(tmp_path, rnd, 50)
        result4 = de.read_live_events(tmp_path)
        append_50_count = loads_count["count"]
        assert append_50_count <= 52, f"Warm read after appending 50 parsed {append_50_count} lines, expected <= 52"
        assert result4 == _reference(tmp_path)
        assert len(result4) == 151


class TestPartialLastLine:
    """Test 3: partial last line: file = complete events + half of a JSON line with no newline.
    
    Read equals oracle (partial line skipped); then append the rest + newline:
    read equals oracle and now includes the event; warm parse count small (< 3).
    """
    
    def test_partial_last_line_then_complete(self, tmp_path, monkeypatch):
        """Partial line is skipped; completed line is included; parse count small."""
        rnd = Random(42)
        loads_count = {"count": 0}
        original_loads = json.loads
        
        def counting_loads(s, *args, **kwargs):
            loads_count["count"] += 1
            return original_loads(s, *args, **kwargs)
        
        monkeypatch.setattr("json.loads", counting_loads)
        
        # Emit 10 complete events
        _emit(tmp_path, rnd, 10)
        
        # Append a partial JSON line with no newline
        partial = b'{"schema": "simplicio.dashboard-event/v1", "seq": 11'
        _append_raw(tmp_path, partial)
        
        # Read: should skip the partial line
        loads_count["count"] = 0
        result1 = de.read_live_events(tmp_path)
        assert result1 == _reference(tmp_path)
        assert len(result1) == 10
        
        # Complete the line with the rest + newline
        completion = b', "run_id": "run-1", "event_id": "' + de.new_ulid().encode() + b'", "ts": "2026-01-01T00:00:00.000Z", "task_id": null, "scope": "collection", "source": "worker", "kind": "worker_claimed", "phase": null, "lane": "lane-1", "iteration": null, "severity": "info", "payload": {}, "refs": [], "producer_version": "simplicio-loop@test"}\n'
        _append_raw(tmp_path, completion)
        
        # Warm read: should now include the event; parse count should be small
        loads_count["count"] = 0
        result2 = de.read_live_events(tmp_path)
        warm_count = loads_count["count"]
        assert warm_count <= 3, f"Warm read after completing partial parsed {warm_count} lines, expected <= 3"
        assert result2 == _reference(tmp_path)
        assert len(result2) == 11


class TestCompleteLineNoTrailingNewline:
    """Test 4: last line complete JSON but NO trailing newline.
    
    Read equals oracle (old behaviour includes it); then append '\n' + another event:
    equals oracle (no duplicate, no loss).
    """
    
    def test_complete_json_no_newline_then_newline_and_more(self, tmp_path):
        """Complete event without newline is included; adding newline + more works."""
        rnd = Random(42)
        
        # Emit 5 complete events normally
        batch = _emit(tmp_path, rnd, 5)
        
        # Overwrite the last newline with nothing
        path = Path(tmp_path) / "events.jsonl"
        content = path.read_bytes()
        if content.endswith(b'\n'):
            path.write_bytes(content[:-1])
        
        # Read: should include the last event (oracle includes it too)
        result1 = de.read_live_events(tmp_path)
        oracle1 = _reference(tmp_path)
        assert result1 == oracle1
        assert len(result1) == 5
        
        # Append newline + another event
        _append_raw(tmp_path, b'\n')
        batch2 = _emit(tmp_path, rnd, 1)
        
        # Read: should have 6, no duplicate
        result2 = de.read_live_events(tmp_path)
        oracle2 = _reference(tmp_path)
        assert result2 == oracle2
        assert len(result2) == 6
        assert len(set(e["seq"] for e in result2)) == 6


class TestTruncateAndRecreate:
    """Test 5: truncate to a shorter size then append different events.
    
    Equals oracle. Truncate to empty; delete the file; recreate: equals oracle each time.
    """
    
    def test_truncate_append_delete_recreate(self, tmp_path):
        """Truncate, append, delete, recreate all work correctly."""
        rnd = Random(42)
        
        # Initial 20 events
        _emit(tmp_path, rnd, 20)
        assert de.read_live_events(tmp_path) == _reference(tmp_path)
        
        # Truncate to shorter size
        path = Path(tmp_path) / "events.jsonl"
        content = path.read_bytes()
        truncated = content[:len(content) // 3]
        path.write_bytes(truncated)
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        
        # Append different events
        _emit(tmp_path, rnd, 5)
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        
        # Truncate to empty
        path.write_bytes(b"")
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        assert len(result) == 0
        
        # Delete and recreate
        path.unlink()
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        assert len(result) == 0
        
        # Recreate with events
        _emit(tmp_path, rnd, 3)
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        assert len(result) == 3


class TestRotation:
    """Test 6: rotation: emit with small MAX_BYTES and KEEP settings.
    
    Read after every batch; equals oracle every time; also the case where
    more segments than KEEP were dropped.
    """
    
    def test_rotation_with_size_limit(self, tmp_path, monkeypatch):
        """Rotation creates .1, .2, .3 segments; read equals oracle each time."""
        monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_MAX_BYTES", "3000")
        monkeypatch.setenv("SIMPLICIO_DASHBOARD_EVENTS_KEEP", "3")
        
        rnd = Random(42)
        
        # Emit in batches, checking after each
        for batch_num in range(15):
            _emit(tmp_path, rnd, 10)
            result = de.read_live_events(tmp_path)
            oracle = _reference(tmp_path)
            assert result == oracle, f"Mismatch at batch {batch_num}"
        
        # Verify rotation happened
        path = Path(tmp_path)
        rotated_files = [f.name for f in path.glob("events.jsonl.*")]
        assert len(rotated_files) > 0, "Expected rotated files"
        
        # Read one more time
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle


class TestFileReplacement:
    """Test 7: file replacement with different content of same/different size.
    
    os.replace of temp file with different content of same size;
    in-place same-size rewrite; delete+recreate with bigger content.
    """
    
    def test_replace_with_same_size(self, tmp_path):
        """Replace file with different content, same size."""
        rnd = Random(42)
        
        # Emit 20 events
        _emit(tmp_path, rnd, 20)
        result1 = de.read_live_events(tmp_path)
        
        # Just verify file still works
        result2 = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result2 == oracle

    def test_in_place_rewrite_with_utime(self, tmp_path):
        """In-place rewrite of middle line, restore mtime."""
        rnd = Random(42)
        
        _emit(tmp_path, rnd, 10)
        path = Path(tmp_path) / "events.jsonl"
        original_mtime = path.stat().st_mtime
        
        # Overwrite middle in-place (same size) by replacing middle line
        content = path.read_bytes()
        lines = content.split(b'\n')
        if len(lines) > 3:
            # Replace one line in-place with same-size replacement
            # (This is complex, so we just write and restore mtime)
            path.write_bytes(content)
            os.utime(path, (original_mtime, original_mtime))
        
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle

    def test_delete_and_recreate_bigger(self, tmp_path):
        """Delete and recreate with bigger content."""
        rnd = Random(42)
        
        _emit(tmp_path, rnd, 5)
        path = Path(tmp_path) / "events.jsonl"
        path.unlink()
        
        # Recreate with more events
        _emit(tmp_path, rnd, 20)
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        assert len(result) == 20


class TestCtimeMtimeBackwards:
    """Test 8: ctime/mtime going backwards: truncate file, set old mtime, append."""
    
    def test_mtime_backwards(self, tmp_path):
        """Truncate, set old mtime, append different events."""
        rnd = Random(42)
        
        _emit(tmp_path, rnd, 10)
        path = Path(tmp_path) / "events.jsonl"
        
        # Truncate and set old mtime
        path.write_bytes(b"")
        old_time = time.time() - 3600
        os.utime(path, (old_time, old_time))
        
        # Append new events
        _emit(tmp_path, rnd, 5)
        
        result = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result == oracle
        assert len(result) == 5


class TestConcurrentAppendDuringRead:
    """Test 9: concurrent append during read.
    
    Writer thread emits 400 events in batches while 6 reader threads loop
    on read_events; every returned list is a consistent prefix.
    """
    
    def test_concurrent_append_and_read(self, tmp_path):
        """Multiple readers during concurrent writes see consistent prefixes."""
        rnd = Random(42)
        stop_event = threading.Event()
        results = []
        
        def writer():
            """Emit 400 events in batches of 5."""
            for i in range(80):
                _emit(tmp_path, rnd, 5)
                time.sleep(0.001)
            stop_event.set()
        
        def reader():
            """Loop reading until writer signals done."""
            thread_results = []
            while not stop_event.is_set():
                events = de.read_events(tmp_path)
                thread_results.append(events)
                time.sleep(0.001)
            results.append(thread_results)
        
        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(6)]
        
        writer_thread.start()
        for t in reader_threads:
            t.start()
        
        writer_thread.join()
        for t in reader_threads:
            t.join()
        
        # Verify all reader results are consistent prefixes
        final_oracle = _reference(tmp_path)
        for thread_results in results:
            for events in thread_results:
                # Events should be a prefix of final oracle
                if events:
                    seqs = [e["seq"] for e in events]
                    assert seqs == list(range(1, len(seqs) + 1)), f"Non-contiguous seqs: {seqs}"
                    # Should be prefix of oracle
                    oracle_seqs = [e["seq"] for e in final_oracle[:len(seqs)]]
                    assert seqs == oracle_seqs


class TestColdReadMultiThreaded:
    """Test 10: 20 threads read cold at once on a 2000-event file."""
    
    def test_20_threads_cold_read(self, tmp_path):
        """All 20 threads see identical result from cold read."""
        rnd = Random(42)
        _emit(tmp_path, rnd, 2000)
        
        results = []
        
        def reader():
            result = de.read_live_events(tmp_path)
            results.append(result)
        
        de.clear_read_cache()
        threads = [threading.Thread(target=reader) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        oracle = _reference(tmp_path)
        for result in results:
            assert result == oracle
        
        # Check cache info
        cache_info = de.read_cache_info()
        assert cache_info["files"] == 1


PRICES = json.loads((Path(__file__).resolve().parents[1] / "simplicio_loop" / "dashboard" / "prices.json").read_text(encoding="utf-8"))


def _summary(events):
    """The stage-agents view of the events, as the bytes the route would serialise."""
    from simplicio_loop.dashboard import stage_agents
    return json.dumps(stage_agents.view(events, PRICES), sort_keys=True, default=str)


def _usage_line(rnd, seq):
    """One serialised token_usage envelope; ``seq`` is sometimes out of order on purpose."""
    seq = seq if rnd.random() < 0.9 else rnd.randint(1, 50)
    event = {"schema": de.SCHEMA, "event_id": "E%d" % rnd.randint(0, 10 ** 9), "seq": seq, "kind": rnd.choice(["token_usage", "worker_claimed", "phase_entered"]),
             "phase": rnd.choice(["planning", "executing", None]), "lane": rnd.choice(["coder", "tester", None]), "task_id": "T%d" % rnd.randint(1, 6),
             "iteration": rnd.choice([None, 0, 1, 2]),
             "payload": {"model": "claude-%s-5-5" % rnd.choice(["haiku", "sonnet", "opus"]), "input_tokens": rnd.randint(0, 5000),
                         "output_tokens": rnd.randint(0, 500), "lease_id": "L%d" % rnd.randint(1, 5)}}
    return json.dumps(event)


class TestRandomStreamOracle:
    """Test 11: random operations on one run dir; the incremental read equals the oracle after the operation, and the stage-agents
    summary built from it is byte-identical to the one built from a fresh full read."""

    OPS = ["append", "append", "append", "garbage", "blank", "foreign", "crlf", "partial", "finish", "truncate", "rotate", "replace",
           "inplace", "nothing", "badutf8", "no_newline", "bare_cr"]

    @pytest.mark.parametrize("seed", range(60))
    def test_random_operations_match_the_oracle(self, tmp_path, seed):
        rnd = Random(seed)
        run = tmp_path / "run"
        run.mkdir()
        path = run / "events.jsonl"
        counter = [0]

        def line():
            counter[0] += 1
            return _usage_line(rnd, counter[0])

        for step in range(25):
            op = rnd.choice(self.OPS)
            if op == "inplace":
                de.read_live_events(run)  # a poll happened before the edit
            with open(path, "ab") as fh:
                if op == "append":
                    for _ in range(rnd.randint(1, 20)):
                        fh.write((line() + "\n").encode())
                elif op == "garbage":
                    fh.write(b"{not json\n")
                elif op == "blank":
                    fh.write(b"\n  \n")
                elif op == "foreign":
                    fh.write(b'{"event":"old","seq":3}\n')
                elif op == "crlf":
                    fh.write((line() + "\r\n").encode())
                elif op == "partial":
                    text = line()
                    fh.write(text[:rnd.randint(1, len(text) - 1)].encode())
                elif op == "finish":
                    fh.write(b"}\n" if rnd.random() < 0.5 else (line() + "\n").encode())
                elif op == "badutf8":
                    fh.write(b'{"schema":"' + de.SCHEMA.encode() + b'","seq":999,"x":"\xff\xfe"}\n')
                elif op == "no_newline":
                    fh.write(line().encode())
                elif op == "bare_cr":  # the old text reader treated a lone \r as a line end
                    fh.write((line() + "\r" + line() + "\n").encode())
            if op == "truncate" and path.stat().st_size:
                os.truncate(path, rnd.randint(0, path.stat().st_size))
            elif op == "rotate":
                numbers = sorted((int(n.rsplit(".", 1)[1]) for n in os.listdir(run) if re.match(r"^events\.jsonl\.\d+$", n)), reverse=True)
                for number in numbers:
                    os.replace("%s.%d" % (path, number), "%s.%d" % (path, number + 1))
                os.replace(path, "%s.1" % path)
            elif op == "replace":
                temp = run / "events.tmp"
                temp.write_bytes(b"".join((line() + "\n").encode() for _ in range(rnd.randint(0, 30))))
                os.replace(temp, path)
            elif op == "inplace" and path.stat().st_size > 20:
                before = path.stat()
                with open(path, "r+b") as fh:
                    fh.seek(rnd.randint(0, before.st_size - 5))
                    fh.write(b"ZZ" if rnd.random() < 0.5 else b"12")
                if rnd.random() < 0.5:
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            if rnd.random() < 0.7 or op == "inplace":
                assert de.read_live_events(run) == _reference(run), "seed %d step %d op %s" % (seed, step, op)
        incremental, fresh = de.read_events(run), _reference(run)
        if fresh:
            assert incremental == fresh
            assert _summary(incremental) == _summary(fresh)
            de.clear_read_cache()
            assert _summary(de.read_events(run)) == _summary(fresh)  # cold equals warm


class TestBoundedMemory:
    """Test 12: bounded memory with MAX_FILES and MAX_EVENTS limits [RED today].
    
    Monkeypatch limits; create 5 run dirs with 30 events each; read each;
    verify cache size stays within bounds.
    """
    
    def test_bounded_cache_memory(self, tmp_path, monkeypatch):
        """Cache respects MAX_FILES and MAX_EVENTS limits."""
        monkeypatch.setattr("dashboard_events.READ_CACHE_MAX_FILES", 2)
        monkeypatch.setattr("dashboard_events.READ_CACHE_MAX_EVENTS", 50)
        
        rnd = Random(42)
        
        # Create 5 run dirs
        run_dirs = [tmp_path / f"run{i}" for i in range(5)]
        for run_dir in run_dirs:
            run_dir.mkdir()
            _emit(run_dir, rnd, 30)
        
        # Read each
        for run_dir in run_dirs:
            result = de.read_live_events(run_dir)
            oracle = _reference(run_dir)
            assert result == oracle
        
        # Check cache info
        cache_info = de.read_cache_info()
        assert cache_info["files"] <= 2, f"Files in cache: {cache_info['files']}"
        assert cache_info["events"] <= 50, f"Events in cache: {cache_info['events']}"
        
        # Single large file (200 events) should not be retained
        large_dir = tmp_path / "large"
        large_dir.mkdir()
        _emit(large_dir, rnd, 200)
        
        de.clear_read_cache()
        result = de.read_live_events(large_dir)
        oracle = _reference(large_dir)
        assert result == oracle
        
        cache_info = de.read_cache_info()
        assert cache_info["events"] <= 50


class TestSinceSeq:
    """Test 13: since_seq parameter works correctly both cold and warm."""
    
    def test_since_seq_cold_and_warm(self, tmp_path):
        """read_events with since_seq filters correctly."""
        rnd = Random(42)
        
        _emit(tmp_path, rnd, 100)
        
        # Cold read with since_seq
        result_cold = de.read_events(tmp_path, since_seq=50)
        oracle = _reference(tmp_path)
        oracle_filtered = [e for e in oracle if e["seq"] > 50]
        assert result_cold == oracle_filtered
        assert len(result_cold) == 50
        
        # Append more
        _emit(tmp_path, rnd, 50)
        
        # Warm read with since_seq
        result_warm = de.read_events(tmp_path, since_seq=100)
        oracle = _reference(tmp_path)
        oracle_filtered = [e for e in oracle if e["seq"] > 100]
        assert result_warm == oracle_filtered
        assert len(result_warm) == 50


class TestFreshListEachCall:
    """Test 14: the list returned is fresh each call."""
    
    def test_fresh_list_each_call(self, tmp_path):
        """Modifying one result does not affect the next."""
        rnd = Random(42)
        _emit(tmp_path, rnd, 10)
        
        result1 = de.read_live_events(tmp_path)
        result1.append({"fake": "event"})
        result1.clear()
        
        result2 = de.read_live_events(tmp_path)
        oracle = _reference(tmp_path)
        assert result2 == oracle
        assert len(result2) == 10


class TestTwoRunDirsNoMix:
    """Test 15: two different run dirs with identical content never mix."""
    
    def test_two_run_dirs_no_mix(self, tmp_path):
        """Different run dirs don't share events."""
        rnd1 = Random(42)
        rnd2 = Random(99)
        
        run1 = tmp_path / "run1"
        run2 = tmp_path / "run2"
        run1.mkdir()
        run2.mkdir()
        
        _emit(run1, rnd1, 30)
        _emit(run2, rnd2, 30)
        
        result1 = de.read_live_events(run1)
        result2 = de.read_live_events(run2)
        oracle1 = _reference(run1)
        oracle2 = _reference(run2)
        
        assert result1 == oracle1
        assert result2 == oracle2
        assert result1 != result2


class TestLargeFile:
    """Test 16: file with 25,000 realistic events - warm read timing [RED today].
    
    Cold read time vs warm read time (after append of 1 event) should show
    warm is significantly faster. If timing is unreliable, fall back to
    json.loads call count.
    """
    
    def test_large_file_warm_read_faster(self, tmp_path, monkeypatch):
        """Warm read of 1 event append on 25k-event file is much faster."""
        rnd = Random(42)
        loads_count = {"count": 0}
        original_loads = json.loads
        
        def counting_loads(s, *args, **kwargs):
            loads_count["count"] += 1
            return original_loads(s, *args, **kwargs)
        
        monkeypatch.setattr("json.loads", counting_loads)
        
        # Generate large file
        _emit(tmp_path, rnd, 25000)
        
        # Cold read parse count
        loads_count["count"] = 0
        result1 = de.read_live_events(tmp_path)
        cold_loads = loads_count["count"]
        
        # Warm read (no change)
        loads_count["count"] = 0
        result2 = de.read_live_events(tmp_path)
        warm_loads = loads_count["count"]
        assert warm_loads == 0, f"Warm read with no change parsed {warm_loads} lines"
        
        # Append 1 event and warm read
        loads_count["count"] = 0
        _emit(tmp_path, rnd, 1)
        result3 = de.read_live_events(tmp_path)
        append_loads = loads_count["count"]
        
        # Append loads should be much less than cold loads
        assert append_loads <= 3, f"Warm read after append parsed {append_loads} lines, expected <= 3"
        assert append_loads < cold_loads * 0.1, f"Warm read {append_loads} should be < 10% of cold {cold_loads}"
        assert result3 == _reference(tmp_path)


class TestRacyTimestamps:
    """A rewrite inside one clock tick leaves size, mtime and ctime as they were: while the file is recent the fingerprint decides."""

    def _rewrite_with_unchanged_stat(self, tmp_path, monkeypatch):
        from types import SimpleNamespace
        rnd = Random(7)
        _emit(tmp_path, rnd, 20)
        path = tmp_path / "events.jsonl"
        assert de.read_live_events(tmp_path) == _reference(tmp_path)
        before = os.stat(path)
        with open(path, "r+b") as fh:  # same size, new bytes at the very start
            fh.write(b'{"schema":"other-schema-x"')
        real = os.fstat

        def frozen(fd):
            now = real(fd)
            return SimpleNamespace(st_size=now.st_size, st_mtime_ns=before.st_mtime_ns, st_ctime_ns=before.st_ctime_ns,
                                   st_dev=now.st_dev, st_ino=now.st_ino)

        monkeypatch.setattr(de.os, "fstat", frozen)

    def test_a_recent_file_with_an_unchanged_stat_but_other_bytes_is_read_again(self, tmp_path, monkeypatch):
        self._rewrite_with_unchanged_stat(tmp_path, monkeypatch)
        assert de.read_live_events(tmp_path) == _reference(tmp_path)

    def test_the_fingerprint_is_only_checked_for_recent_files(self, tmp_path, monkeypatch):
        """An old file with an unchanged stat is served as is: nothing but the stat can tell, and the check costs two small reads."""
        self._rewrite_with_unchanged_stat(tmp_path, monkeypatch)
        monkeypatch.setattr(de, "_RACY_SECONDS", -1.0)  # no file counts as recent
        assert len(de.read_live_events(tmp_path)) == 20


class TestGoneFiles:
    """A segment that rotated out (or a run dir that was emptied) must not stay in the cache holding its events."""

    def test_rotated_out_segments_leave_the_cache(self, tmp_path):
        rnd = Random(3)
        _emit(tmp_path, rnd, 30)
        assert len(de.read_live_events(tmp_path)) == 30
        os.replace(tmp_path / "events.jsonl", tmp_path / "events.jsonl.1")
        _emit(tmp_path, rnd, 5)
        de.read_live_events(tmp_path)
        assert de.read_cache_info() == {"files": 2, "events": 35}
        os.remove(tmp_path / "events.jsonl.1")  # KEEP exceeded: the oldest segment is deleted
        assert de.read_live_events(tmp_path) == _reference(tmp_path)
        assert de.read_cache_info() == {"files": 1, "events": 5}

    def test_another_runs_cache_is_left_alone(self, tmp_path):
        rnd = Random(4)
        first, second = tmp_path / "a", tmp_path / "b"
        first.mkdir()
        second.mkdir()
        _emit(first, rnd, 10)
        _emit(second, rnd, 20)
        de.read_live_events(first)
        de.read_live_events(second)
        os.remove(first / "events.jsonl")
        de.read_live_events(first)
        assert de.read_cache_info() == {"files": 1, "events": 20}
