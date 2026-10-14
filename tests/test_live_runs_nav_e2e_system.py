'''End-to-end test of the Simplicio Live run navigation and the Pipeline reference image (issue #1402, slice 4b-3).

A real dashboard server runs on loopback over a repo with two runs. Playwright checks:

- the Ctrl-K palette lists the other run ("Run run-b") and choosing it moves the page to ``?run=run-b``, keeping the
  token and the other parameters;
- ``?tv=1&rotate=1`` moves through the runs on its own, wrapping around, and the URL keeps ``tv=1``;
- with ``prefers-reduced-motion: reduce`` the TV mode does not rotate;
- the Pipeline page, after the runner-lifecycle fixture replays in full, matches the committed reference image
  ``tests/fixtures/live_pipeline/pipeline-dark-1280x900.png`` within a stated tolerance.

Reference image tolerance: the screenshot is taken at 1280x900, dark theme, reduced motion, over the viewport with
the board and the clock-dependent cells hidden. A pixel differs when any RGB channel differs by more than
``CHANNEL_TOLERANCE`` (16 of 255); the page matches when at most ``MAX_DIFF_RATIO`` (2%) of the pixels differ. That
absorbs anti-aliasing and sub-pixel text shifts between machines; a layout, colour or content change moves far more
pixels. To refresh the reference after an intended visual change, run the test with ``SL_UPDATE_REFERENCE=1``.

The optional e2e extra provides Playwright (``pip install -e '.[e2e]'``).
'''
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sync_api = pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')

from simplicio_loop.dashboard import server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
REFERENCE = REPO / 'tests' / 'fixtures' / 'live_pipeline' / 'pipeline-dark-1280x900.png'
CHROMIUM_PATH = Path('/opt/pw-browsers/chromium')
TOKEN = 'runs-nav-e2e-token-0123'
TIMEOUT_MS = 10000
SPEC_KEYS = ('task_id', 'scope', 'phase', 'lane', 'iteration', 'severity', 'payload', 'refs')
CHANNEL_TOLERANCE = 16
MAX_DIFF_RATIO = 0.02
VIEWPORT = (1280, 900)
HIDE_VOLATILE_CSS = '''
.board-panel, #alerts-panel { display: none !important; }
.live-head { visibility: hidden !important; }
*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }
'''
DIFF_JS = r'''async (args) => {
  const load = async (b64) => {
    const blob = await (await fetch('data:image/png;base64,' + b64)).blob();
    const bitmap = await createImageBitmap(blob);
    const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
    const ctx = canvas.getContext('2d');
    ctx.drawImage(bitmap, 0, 0);
    return ctx.getImageData(0, 0, bitmap.width, bitmap.height);
  };
  const a = await load(args.actual);
  const b = await load(args.reference);
  if (a.width !== b.width || a.height !== b.height) return { sizeMismatch: [a.width, a.height, b.width, b.height] };
  let differing = 0;
  for (let i = 0; i < a.data.length; i += 4) {
    const d = Math.max(Math.abs(a.data[i] - b.data[i]), Math.abs(a.data[i + 1] - b.data[i + 1]), Math.abs(a.data[i + 2] - b.data[i + 2]));
    if (d > args.tolerance) differing += 1;
  }
  return { ratio: differing / (a.width * a.height), pixels: a.width * a.height };
}'''


@pytest.fixture(scope='module')
def browser():
    with sync_api.sync_playwright() as pw:
        launched = None
        errors = []
        options = [{}]
        if CHROMIUM_PATH.exists():
            options.append({'executable_path': str(CHROMIUM_PATH)})
        options += [{'channel': 'chrome'}, {'channel': 'msedge'}]
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


def _write_run(root, run_id, updated_at):
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {'run_id': run_id, 'status': 'running', 'phase': 'executing', 'repo': str(root), 'updated_at': updated_at}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    return run_dir


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'repo'
    _write_run(root, 'run-a', '2026-10-08T10:00:00Z')
    _write_run(root, 'run-b', '2026-10-08T09:00:00Z')
    return root


@pytest.fixture
def live_server(repo):
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    yield handle
    handle.stop()


@pytest.fixture
def open_page(browser, live_server):
    contexts = []

    def _open(query, reduced_motion='no-preference', viewport=VIEWPORT, bypass_csp=False):
        context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, reduced_motion=reduced_motion,
                                      bypass_csp=bypass_csp)
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append(str(e)))
        page.goto('http://127.0.0.1:%d/?t=%s&%s' % (live_server.port, TOKEN, query))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


def _run_param(page):
    return parse_qs(urlparse(page.url).query).get('run', [None])[0]


def test_palette_lists_the_other_run_and_jumps_to_it(open_page):
    page = open_page('run=run-a&theme=dark')
    page.wait_for_function("() => (document.getElementById('palette').commands || []).some((c) => c.id === 'run:run-b')")
    commands = page.evaluate("() => document.getElementById('palette').commands.filter((c) => c.id.startsWith('run:')).map((c) => c.id)")
    assert commands == ['run:run-b']
    page.keyboard.press('Control+k')
    page.keyboard.type('run-b')
    page.keyboard.press('Enter')
    page.wait_for_url('**run=run-b**')
    query = parse_qs(urlparse(page.url).query)
    assert query['run'] == ['run-b'] and query['t'] == [TOKEN] and query['theme'] == ['dark']
    page.wait_for_selector('html[data-ready="1"]')
    assert page.problems == []


def test_tv_mode_rotates_through_the_runs_and_wraps(open_page):
    page = open_page('run=run-a&tv=1&rotate=1')
    seen = [_run_param(page)]
    deadline = time.time() + 20
    while len(seen) < 3 and time.time() < deadline:
        page.wait_for_function('(current) => new URLSearchParams(location.search).get("run") !== current', arg=seen[-1], timeout=8000)
        page.wait_for_selector('html[data-ready="1"]')
        seen.append(_run_param(page))
    assert seen == ['run-a', 'run-b', 'run-a']
    assert parse_qs(urlparse(page.url).query)['tv'] == ['1']


def test_tv_mode_does_not_rotate_under_reduced_motion(open_page):
    page = open_page('run=run-a&tv=1&rotate=1', reduced_motion='reduce')
    page.wait_for_function("() => (document.getElementById('palette').commands || []).some((c) => c.id === 'run:run-b')")
    page.wait_for_timeout(3000)
    assert _run_param(page) == 'run-a'


def _replay_full(run_dir):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    events = [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]
    for event in events:
        spec = {key: event[key] for key in SPEC_KEYS if key in event}
        emitter.emit(run_dir, event['kind'], source=event['source'], strict=True, **spec)
    return len(events)


def test_pipeline_matches_the_reference_image_within_tolerance(open_page, repo):
    count = _replay_full(repo / '.simplicio-loop' / 'loop-runs' / 'run-a')
    page = open_page('run=run-a&theme=dark', reduced_motion='reduce', bypass_csp=True)
    page.wait_for_function("(seq) => Number(document.body.getAttribute('data-last-seq')) >= seq", arg=count, timeout=TIMEOUT_MS)
    page.wait_for_timeout(500)
    page.add_style_tag(content=HIDE_VOLATILE_CSS)
    shot = page.screenshot(clip={'x': 0, 'y': 0, 'width': VIEWPORT[0], 'height': VIEWPORT[1]})
    if os.environ.get('SL_UPDATE_REFERENCE') == '1':
        REFERENCE.write_bytes(shot)
    assert REFERENCE.exists(), 'reference image missing: run once with SL_UPDATE_REFERENCE=1'
    blank = page.context.new_page()  # a blank page has no CSP, so it can decode the two PNGs
    result = blank.evaluate(DIFF_JS, {'actual': base64.b64encode(shot).decode(),
                                     'reference': base64.b64encode(REFERENCE.read_bytes()).decode(),
                                     'tolerance': CHANNEL_TOLERANCE})
    assert 'sizeMismatch' not in result, result
    assert result['ratio'] <= MAX_DIFF_RATIO, 'pipeline differs from the reference on %.2f%% of pixels (max %.0f%%)' % (
        result['ratio'] * 100, MAX_DIFF_RATIO * 100)
