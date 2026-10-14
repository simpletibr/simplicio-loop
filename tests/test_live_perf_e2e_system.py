'''Performance budget for the Simplicio Live page and the server read routes, measured over loopback.

Four budgets, each measured for real and recorded in ``REPORT``:

1. LCP of ``/?t=<token>&run=<id>`` with the lifecycle fixture already on disk: median of 5 cold loads < 1500 ms.
2. Event stream stress: 1000 events burst into one run. The page reaches the final seq within 15 s, its long-task
   total is under 1000 ms, no single long task exceeds 500 ms, and the page raises no console or page error.
3. Client memory: 3000 events streamed in batches. After HeapProfiler.collectGarbage the JS heap is sampled at
   checkpoints. Mean heap of the second-half checkpoints minus the mean of the first-half ones stays under 10 MB, and
   mean DOM node and listener counts of the second half stay within 10% of the first half.
4. Server read routes: 50 sequential GETs per route (urllib, Bearer token) with 20 runs and 1000 events on disk.
   p95 < 100 ms. Percentiles are nearest-rank over the 50 samples. A few untimed warm-up GETs come first, and the
   verdict uses the BEST of up to 3 independent 50-sample p95 measurements per route (it stops at the first one
   under budget): a real regression is slower in all three, a burst of host load (another process, a GC pause) is not.

When ``SL_PERF_REPORT`` names a path, every measurement is written there as JSON as soon as it is taken.
Chromium comes from /opt/pw-browsers/chromium, a default Playwright install, or a system Chrome or Edge; without one
the browser tests skip. The route test needs no browser.
'''
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from simplicio_loop.dashboard import server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
CHROMIUM_PATH = Path('/opt/pw-browsers/chromium')
TOKEN = 'perf-e2e-token-0123'
RUN_ID = 'run-perf'
TIMEOUT_MS = 15000
SETTLE_MS = 300
SPEC_KEYS = ('task_id', 'scope', 'phase', 'lane', 'iteration', 'severity', 'payload', 'refs')
LANE_KINDS = ('lane_progress', 'gate_evaluated')
GATE_NAMES = ('evidence', 'watcher', 'oracle', 'dod', 'quality', 'action')
STRESS_LANES = 8
# Budgets.
LCP_LOADS = 5
LCP_BUDGET_MS = 1500
STRESS_EVENTS = 1000
STRESS_BATCH = 50
STRESS_SEQ_BUDGET_S = 15
LONGTASK_TOTAL_BUDGET_MS = 1000
LONGTASK_MAX_BUDGET_MS = 500
MEMORY_EVENTS = 3000
MEMORY_BATCH = 100
FIRST_HALF_CHECKPOINTS = (500, 1000)
SECOND_HALF_CHECKPOINTS = (2500, 3000)
HEAP_GROWTH_BUDGET_BYTES = 10 * 1024 * 1024
DOM_GROWTH_RATIO = 1.10
ROUTE_RUNS = 20
ROUTE_EVENTS = 1000
ROUTE_SAMPLES = 50
ROUTE_WARMUP = 5
ROUTE_ATTEMPTS = 3
ROUTE_P95_BUDGET_MS = 100
ROUTE_RUN_FIRST = 'run-route-00'

PERF_INIT_JS = r'''
window.__lcp = [];
window.__longtasks = [];
try {
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__lcp.push(e.renderTime || e.loadTime || e.startTime);
  }).observe({ type: 'largest-contentful-paint', buffered: true });
} catch (err) { window.__lcpError = String(err); }
try {
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__longtasks.push(e.duration);
  }).observe({ type: 'longtask', buffered: true });
} catch (err) { window.__longtaskError = String(err); }
'''

REPORT: dict = {}


def _record(section, value):
    REPORT[section] = value
    print('\nPERF %s: %s' % (section, json.dumps(value, sort_keys=True)))
    target = os.environ.get('SL_PERF_REPORT')
    if target:
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(REPORT, indent=2, sort_keys=True), encoding='utf-8')


def _fixture_events():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]


def _run_dir(repo):
    return repo / '.simplicio-loop' / 'loop-runs' / RUN_ID


def _url(port):
    return 'http://127.0.0.1:%d/?t=%s&theme=dark&run=%s' % (port, TOKEN, RUN_ID)


def _specs(events):
    return [dict({key: event[key] for key in SPEC_KEYS if key in event}, kind=event['kind'], source=event['source'])
            for event in events]


def _emit_batch(run_dir, specs):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    written = emitter.emit_batch(run_dir, specs, strict=True)
    assert len(written) == len(specs), 'emitter wrote %d of %d events' % (len(written), len(specs))
    return written


def _stress_specs(count, offset=0):
    '''Lane progress and gate verdicts spread over eight lanes, the shape of a busy executing phase.'''
    specs = []
    for number in range(offset, offset + count):
        lane = 'lane-%d' % (number % STRESS_LANES + 1)
        task = 'T%d' % (number % STRESS_LANES + 1)
        if number % 10 == 9:
            gate = GATE_NAMES[(number // 10) % len(GATE_NAMES)]
            specs.append({'kind': 'gate_evaluated', 'source': 'runner', 'phase': 'executing', 'task_id': task,
                          'lane': lane, 'severity': 'info',
                          'payload': {'gate': gate, 'verdict': 'pass', 'message': 'gate %d' % number}})
        else:
            specs.append({'kind': 'lane_progress', 'source': 'worker', 'phase': 'executing', 'task_id': task,
                          'lane': lane, 'severity': 'info', 'payload': {'message': 'passo %d' % number}})
    return specs


def _wait_seq(page, seq, timeout=TIMEOUT_MS):
    page.wait_for_function("(seq) => Number(document.body.getAttribute('data-last-seq')) >= seq", arg=seq,
                           timeout=timeout)


def _percentile(values, pct):
    '''Nearest-rank percentile: the smallest sample with at least pct% of the samples at or below it.'''
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100.0 * len(ordered)) - 1)]


@pytest.fixture(scope='module')
def browser():
    sync_api = pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')
    with sync_api.sync_playwright() as pw:
        launched = None
        errors = []
        options = []
        if CHROMIUM_PATH.exists():
            options.append({'executable_path': str(CHROMIUM_PATH)})
        options += [{}, {'channel': 'chrome'}, {'channel': 'msedge'}]
        for option in options:
            try:
                launched = pw.chromium.launch(**option)
                break
            except Exception as exc:  # browser binary not installed for this option
                errors.append(str(exc).splitlines()[0])
        if launched is None:
            pytest.skip('no Chromium/Chrome available: ' + ' | '.join(errors))
        yield launched
        launched.close()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True)
    state = {'run_id': RUN_ID, 'status': 'running', 'phase': 'intake', 'percent': 0, 'repo': str(root),
             'started_at': '2026-10-02T22:08:04Z', 'updated_at': '2026-10-02T22:08:04Z'}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    return root


@pytest.fixture
def live_server(repo):
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    yield handle
    handle.stop()


@pytest.fixture
def open_page(browser, live_server):
    contexts = []

    def _open():
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.add_init_script(PERF_INIT_JS)
        page.goto(_url(live_server.port))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


def _measure_lcp(browser, port, expected_seq):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    try:
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.add_init_script(PERF_INIT_JS)
        page.goto(_url(port), wait_until='load')
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        _wait_seq(page, expected_seq)
        page.wait_for_timeout(SETTLE_MS)
        candidates = page.evaluate('() => window.__lcp')
    finally:
        context.close()
    assert candidates, 'no largest-contentful-paint entry was recorded'
    return max(candidates)


def test_lcp_median_of_five_cold_loads_is_under_budget(browser, live_server, repo):
    expected = len(_fixture_events())
    _emit_batch(_run_dir(repo), _specs(_fixture_events()))
    values = [round(_measure_lcp(browser, live_server.port, expected), 1) for _ in range(LCP_LOADS)]
    median = round(statistics.median(values), 1)
    _record('lcp', {'loads_ms': values, 'median_ms': median, 'budget_ms': LCP_BUDGET_MS, 'events_on_disk': expected})
    assert median < LCP_BUDGET_MS, 'LCP median %.1f ms over budget %d ms (loads %s)' % (median, LCP_BUDGET_MS, values)


def test_thousand_event_burst_keeps_the_page_responsive(open_page, repo):
    page = open_page()
    page.evaluate('() => { window.__longtasks.length = 0; }')
    run_dir = _run_dir(repo)
    specs = _stress_specs(STRESS_EVENTS)
    burst_start = time.perf_counter()
    for start in range(0, STRESS_EVENTS, STRESS_BATCH):
        _emit_batch(run_dir, specs[start:start + STRESS_BATCH])
    emit_s = time.perf_counter() - burst_start
    reach_start = time.perf_counter()
    _wait_seq(page, STRESS_EVENTS, timeout=STRESS_SEQ_BUDGET_S * 1000)
    reach_s = time.perf_counter() - reach_start
    final_seq = page.get_attribute('body', 'data-last-seq')
    page.wait_for_timeout(SETTLE_MS)
    longtasks = page.evaluate('() => window.__longtasks')
    total_ms = round(sum(longtasks), 1)
    max_ms = round(max(longtasks), 1) if longtasks else 0.0
    _record('stress', {'events': STRESS_EVENTS, 'emit_s': round(emit_s, 3), 'reach_last_seq_s': round(reach_s, 3),
                       'final_seq': final_seq, 'longtask_count': len(longtasks), 'longtask_total_ms': total_ms,
                       'longtask_max_ms': max_ms, 'page_problems': page.problems})
    assert final_seq == str(STRESS_EVENTS), final_seq
    assert total_ms < LONGTASK_TOTAL_BUDGET_MS, 'long-task total %.1f ms' % total_ms
    assert max_ms <= LONGTASK_MAX_BUDGET_MS, 'longest task %.1f ms' % max_ms
    assert page.problems == [], page.problems


def _sample(cdp):
    cdp.send('HeapProfiler.collectGarbage')
    metrics = {m['name']: m['value'] for m in cdp.send('Performance.getMetrics')['metrics']}
    dom = cdp.send('Memory.getDOMCounters')
    return {'heap_bytes': int(metrics['JSHeapUsedSize']), 'nodes': int(dom['nodes']),
            'listeners': int(dom['jsEventListeners']), 'documents': int(dom['documents'])}


def _mean(samples, key):
    return statistics.mean(sample[key] for sample in samples)


def test_heap_and_dom_stay_flat_across_a_compressed_session(open_page, repo):
    page = open_page()
    cdp = page.context.new_cdp_session(page)
    cdp.send('HeapProfiler.enable')
    cdp.send('Performance.enable')
    run_dir = _run_dir(repo)
    specs = _stress_specs(MEMORY_EVENTS)
    samples = {}
    for done in range(MEMORY_BATCH, MEMORY_EVENTS + 1, MEMORY_BATCH):
        _emit_batch(run_dir, specs[done - MEMORY_BATCH:done])
        _wait_seq(page, done)
        page.wait_for_timeout(SETTLE_MS)
        if done in FIRST_HALF_CHECKPOINTS + SECOND_HALF_CHECKPOINTS:
            samples[done] = _sample(cdp)
    first = [samples[c] for c in FIRST_HALF_CHECKPOINTS]
    second = [samples[c] for c in SECOND_HALF_CHECKPOINTS]
    heap_growth = _mean(second, 'heap_bytes') - _mean(first, 'heap_bytes')
    nodes_first, nodes_second = _mean(first, 'nodes'), _mean(second, 'nodes')
    listeners_first, listeners_second = _mean(first, 'listeners'), _mean(second, 'listeners')
    _record('memory', {'events': MEMORY_EVENTS, 'checkpoints': {str(k): v for k, v in sorted(samples.items())},
                       'heap_growth_bytes': round(heap_growth), 'heap_growth_budget_bytes': HEAP_GROWTH_BUDGET_BYTES,
                       'nodes_first_mean': nodes_first, 'nodes_second_mean': nodes_second,
                       'listeners_first_mean': listeners_first, 'listeners_second_mean': listeners_second,
                       'dom_growth_ratio_budget': DOM_GROWTH_RATIO, 'page_problems': page.problems})
    assert heap_growth < HEAP_GROWTH_BUDGET_BYTES, 'heap grew %d bytes' % heap_growth
    assert nodes_second <= nodes_first * DOM_GROWTH_RATIO, 'DOM nodes grew %.1f -> %.1f' % (nodes_first, nodes_second)
    assert listeners_second <= listeners_first * DOM_GROWTH_RATIO, (
        'listeners grew %.1f -> %.1f' % (listeners_first, listeners_second))
    assert page.problems == [], page.problems


@pytest.fixture
def route_repo(tmp_path):
    from simplicio_loop.dashboard_events import load
    root = tmp_path / 'routes'
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    per_run = ROUTE_EVENTS // ROUTE_RUNS
    for index in range(ROUTE_RUNS):
        run_id = 'run-route-%02d' % index
        run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
        run_dir.mkdir(parents=True)
        state = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'percent': 40, 'repo': str(root),
                 'started_at': '2026-10-02T22:08:04Z', 'updated_at': '2026-10-02T22:08:04Z'}
        (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
        written = emitter.emit_batch(run_dir, _stress_specs(per_run, offset=index * per_run), strict=True)
        assert len(written) == per_run
    return root


def _timed_gets(url, samples=ROUTE_SAMPLES):
    durations = []
    body = None
    for _ in range(samples):
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOKEN})
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read()
            status = response.status
        durations.append((time.perf_counter() - started) * 1000.0)
        assert status == 200, (url, status)
    return durations, json.loads(body.decode('utf-8'))


def _measure_route(url):
    '''Warm the route up, then take up to ROUTE_ATTEMPTS independent runs of ROUTE_SAMPLES timed GETs.

    Returns the run with the lowest p95 (so transient host load cannot fail the budget; a real slowdown shows in all
    runs), the p95 of every attempt, and the last response body. It stops at the first run that meets the budget:
    that is the same verdict as best-of-ROUTE_ATTEMPTS, and an idle host pays for one run only.
    '''
    _timed_gets(url, ROUTE_WARMUP)
    attempts = []
    body = None
    for _ in range(ROUTE_ATTEMPTS):
        durations, body = _timed_gets(url)
        attempts.append(durations)
        if _percentile(durations, 95) < ROUTE_P95_BUDGET_MS:
            break
    return min(attempts, key=lambda run: _percentile(run, 95)), [round(_percentile(run, 95), 2) for run in attempts], body


def _fake_runs(monkeypatch, p95_per_attempt):
    '''Replace _timed_gets with canned runs: 50 samples whose p95 is each value of p95_per_attempt in turn.'''
    calls = []

    def fake(url, samples=ROUTE_SAMPLES):
        calls.append(samples)
        if samples == ROUTE_WARMUP:
            return [1.0] * samples, {}
        p95 = p95_per_attempt[calls.count(ROUTE_SAMPLES) - 1]
        return [1.0] * (samples - 3) + [p95] * 3, {'attempt': len(calls)}

    monkeypatch.setattr(sys.modules[__name__], '_timed_gets', fake)
    return calls


def test_one_noisy_attempt_does_not_fail_the_route_budget(monkeypatch):
    calls = _fake_runs(monkeypatch, [ROUTE_P95_BUDGET_MS * 3, ROUTE_P95_BUDGET_MS * 0.4])
    best, attempts_p95, _body = _measure_route('http://unused')
    assert attempts_p95 == [ROUTE_P95_BUDGET_MS * 3, ROUTE_P95_BUDGET_MS * 0.4]
    assert _percentile(best, 95) == ROUTE_P95_BUDGET_MS * 0.4
    assert calls[0] == ROUTE_WARMUP, 'the untimed warm-up comes first'
    assert calls.count(ROUTE_SAMPLES) == 2, 'it stops at the first run under budget'


def test_a_real_slowdown_is_slower_in_every_attempt_and_still_fails(monkeypatch):
    slow = [ROUTE_P95_BUDGET_MS * 1.5, ROUTE_P95_BUDGET_MS * 1.2, ROUTE_P95_BUDGET_MS * 2.0]
    calls = _fake_runs(monkeypatch, slow)
    best, attempts_p95, _body = _measure_route('http://unused')
    assert calls.count(ROUTE_SAMPLES) == ROUTE_ATTEMPTS
    assert attempts_p95 == slow
    assert _percentile(best, 95) == ROUTE_P95_BUDGET_MS * 1.2
    assert _percentile(best, 95) >= ROUTE_P95_BUDGET_MS, 'the best attempt is still over the budget'


def test_read_routes_p95_under_budget_with_twenty_runs_and_a_thousand_events(route_repo):
    handle = server.start(repo_root=route_repo, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    base = 'http://127.0.0.1:%d' % handle.port
    routes = {
        '/api/health': lambda body: body['status'] == 'ok',
        '/api/runs': lambda body: len(body['runs']) == ROUTE_RUNS,
        '/api/runs/' + ROUTE_RUN_FIRST: lambda body: body['run_id'] == ROUTE_RUN_FIRST,
        '/api/runs/%s/artifacts/state.json' % ROUTE_RUN_FIRST: lambda body: body['run_id'] == ROUTE_RUN_FIRST,
    }
    results = {}
    try:
        for path, check in routes.items():
            durations, attempts_p95, body = _measure_route(base + path)
            assert check(body), (path, str(body)[:200])
            results[path] = {'p50_ms': round(_percentile(durations, 50), 2),
                             'p95_ms': round(_percentile(durations, 95), 2),
                             'p95_attempts_ms': attempts_p95,
                             'max_ms': round(max(durations), 2), 'samples': len(durations)}
    finally:
        handle.stop()
    _record('routes', {'runs': ROUTE_RUNS, 'events': ROUTE_EVENTS, 'p95_budget_ms': ROUTE_P95_BUDGET_MS,
                       'by_route': results})
    over = {path: stats['p95_ms'] for path, stats in results.items() if stats['p95_ms'] >= ROUTE_P95_BUDGET_MS}
    assert over == {}, 'best-of-%d p95 over %d ms: %s (attempts: %s)' % (
        ROUTE_ATTEMPTS, ROUTE_P95_BUDGET_MS, over, {path: results[path]['p95_attempts_ms'] for path in over})
