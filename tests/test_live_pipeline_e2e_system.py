'''End-to-end system test of the Simplicio Live pipeline page in a real browser (issue #1402, slice 4b-1).

TDD red: the page under static/live/ and the /static route do not exist yet. The test starts the dashboard server
over loopback, replays the runner-lifecycle fixture through the real dashboard_events emitter with 50 ms gaps and
drives the page with Playwright. It requires the optional e2e extra:

    pip install -e '.[e2e]' && python -m playwright install chromium   # or a system Chrome
'''
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')
axe_pkg = pytest.importorskip('axe_playwright_python', reason='optional e2e extra (pip install -e .[e2e])')

from simplicio_loop.dashboard import server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
AXE_JS = Path(axe_pkg.__file__).with_name('axe.min.js')
TOKEN = 'live-e2e-token-0123'
RUN_ID = 'run-fixture-lifecycle'
TIMEOUT_MS = 10000
SPEC_KEYS = ('task_id', 'scope', 'phase', 'lane', 'iteration', 'severity', 'payload', 'refs')
RAIL_ORDER = ['intake', 'mapping', 'planning', 'executing', 'validating', 'delivering', 'done']
GATES = ['evidence', 'watcher', 'oracle', 'dod', 'quality', 'action']
INIT_SCRIPT = r'''
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective));
window.__railLog = [];
const sampleRail = () => {
  const rail = document.getElementById('rail');
  const phase = rail && rail.getAttribute('phase');
  if (phase && window.__railLog[window.__railLog.length - 1] !== phase) window.__railLog.push(phase);
};
new MutationObserver(sampleRail).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['phase'] });
'''
GATE_ORDER_JS = '''() => [...document.querySelectorAll('#gates li[data-gate]')].map((li) => li.dataset.gate)'''
SHOWS_JS = r'''(args) => {
  const el = document.querySelector(args.sel);
  if (!el) return false;
  const parts = [el.textContent || ''];
  for (const node of [el, ...el.querySelectorAll('*')]) {
    for (const attr of node.attributes) parts.push(attr.value);
    if (node.shadowRoot) parts.push(node.shadowRoot.textContent || '');
  }
  return parts.join(' ').toUpperCase().includes(args.word.toUpperCase());
}'''
KPI_NUMERIC = r'''(sel) => {
  const el = document.querySelector(sel);
  if (!el) return false;
  return /\d/.test(el.getAttribute('value') || el.textContent || '');
}'''
AXE_RUN_JS = '''async () => (await axe.run(document, { resultTypes: ['violations'] })).violations
  .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))'''


@pytest.fixture(scope='module')
def browser():
    with sync_api.sync_playwright() as pw:
        launched = None
        errors = []
        for options in ({}, {'channel': 'chrome'}, {'channel': 'msedge'}):
            try:
                launched = pw.chromium.launch(**options)
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
    run_dir = root / '.simplicio-loop' / 'loop-runs' / RUN_ID
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

    def _open(theme='dark', reduced_motion='no-preference'):
        context = browser.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion=reduced_motion)
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.add_init_script(INIT_SCRIPT)
        page.goto('http://127.0.0.1:%d/?t=%s&theme=%s&run=%s' % (live_server.port, TOKEN, theme, RUN_ID))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


def _run_dir(repo):
    return repo / '.simplicio-loop' / 'loop-runs' / RUN_ID


def _fixture_events():
    return [json.loads(line) for line in FIXTURE.read_text(encoding='utf-8').splitlines() if line.strip()]


def _emit(run_dir, event):
    from simplicio_loop.dashboard_events import load
    emitter = load()
    assert emitter is not None, 'dashboard_events emitter is missing'
    spec = {key: event[key] for key in SPEC_KEYS if key in event}
    return emitter.emit(run_dir, event['kind'], source=event['source'], strict=True, **spec)


def _replay(run_dir, events, gap=0.05):
    for event in events:
        _emit(run_dir, event)
        time.sleep(gap)


def _wait_seq(page, seq):
    page.wait_for_function("(seq) => document.body.getAttribute('data-last-seq') === String(seq)", arg=seq, timeout=TIMEOUT_MS)


def test_pipeline_replays_in_order_and_the_ring_waits_for_the_receipt(open_page, repo):
    page = open_page('dark')
    run_dir = _run_dir(repo)
    _replay(run_dir, _fixture_events())
    _wait_seq(page, 28)
    assert page.evaluate('() => window.__railLog') == RAIL_ORDER
    assert page.evaluate(GATE_ORDER_JS) == GATES
    assert page.get_attribute('#ring', 'data-percent') == '99'
    page.wait_for_timeout(300)
    assert page.get_attribute('#ring', 'data-percent') == '99'
    assert page.get_attribute('#ring', 'center') == '99%'
    assert page.evaluate(SHOWS_JS, {'sel': '#gates li[data-gate="evidence"]', 'word': 'PASS'})
    assert not page.evaluate(SHOWS_JS, {'sel': '#gates li[data-gate="oracle"]', 'word': 'PASS'})
    (run_dir / 'completion-receipt.json').write_text(json.dumps({'ready': True, 'verdict': 'COMPLETE'}), encoding='utf-8')
    page.wait_for_function("() => document.getElementById('ring').getAttribute('data-percent') === '100'", timeout=1000)
    assert page.evaluate(SHOWS_JS, {'sel': '#gates li[data-gate="oracle"]', 'word': 'PASS'})
    flip = dict(_fixture_events()[-1], kind='gate_evaluated', phase='done', refs=[],
                payload={'step': 'quality_gate', 'message': 'qualidade reprovada', 'gate': 'quality', 'verdict': 'fail'})
    _emit(run_dir, flip)
    page.wait_for_function(SHOWS_JS, arg={'sel': '#gates li[data-gate="quality"]', 'word': 'FAIL'}, timeout=1000)
    assert page.evaluate(SHOWS_JS, {'sel': '#conn', 'word': 'LIVE'})
    page.wait_for_function(KPI_NUMERIC, arg='#kpi-heartbeat', timeout=TIMEOUT_MS)
    assert page.evaluate('() => window.__csp') == []
    assert page.problems == []


def test_reduced_motion_leaves_no_running_animation(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark', reduced_motion='reduce')
    _wait_seq(page, 28)
    running = page.evaluate("() => document.getAnimations().filter((a) => a.playState === 'running').length")
    assert running == 0


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_axe_reports_no_serious_or_critical_violations(open_page, repo, theme):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page(theme)
    _wait_seq(page, 28)
    assert page.get_attribute('html', 'data-sl-theme') == theme
    page.evaluate(AXE_JS.read_text(encoding='utf-8'))
    violations = page.evaluate(AXE_RUN_JS)
    assert [v for v in violations if v['impact'] in ('serious', 'critical')] == [], violations


def test_empty_repo_shows_the_empty_state(browser, tmp_path):
    root = tmp_path / 'empty'
    (root / '.simplicio-loop').mkdir(parents=True)
    handle = server.start(repo_root=root, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    try:
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.goto('http://127.0.0.1:%d/?t=%s&theme=dark' % (handle.port, TOKEN))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        page.locator('#empty[role="status"]').wait_for(state='visible', timeout=TIMEOUT_MS)
    finally:
        context.close()
        handle.stop()
