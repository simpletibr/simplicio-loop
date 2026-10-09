'''End-to-end system test of the Simplicio Live pipeline page in a real browser (issue #1402, slice 4b-1).

TDD red: the page under static/live/ and the /static route do not exist yet. The test starts the dashboard server
over loopback, replays the runner-lifecycle fixture through the real dashboard_events emitter with 50 ms gaps and
drives the page with Playwright. It requires the optional e2e extra:

    pip install -e '.[e2e]' && python -m playwright install chromium   # or a system Chrome
'''
from __future__ import annotations

import json
import os
import re
import statistics
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
window.__laneLog = [];
const sampleLane = () => {
  const block = document.querySelector('#lanes li[data-lane="feat/fixture"] button.block');
  const state = block && block.getAttribute('data-state');
  if (state && window.__laneLog[window.__laneLog.length - 1] !== state) window.__laneLog.push(state);
};
new MutationObserver(sampleLane).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state'] });
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
        candidates = ({'executable_path': os.environ['SL_CHROMIUM_PATH']},) if os.environ.get('SL_CHROMIUM_PATH') else ()
        for options in candidates + ({}, {'channel': 'chrome'}, {'channel': 'msedge'}):
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

    def _open(theme='dark', reduced_motion='no-preference', tv=False, viewport=(1280, 900)):
        context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, reduced_motion=reduced_motion)
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.add_init_script(INIT_SCRIPT)
        page.goto('http://127.0.0.1:%d/?t=%s&theme=%s&run=%s%s' % (live_server.port, TOKEN, theme, RUN_ID, '&tv=1' if tv else ''))
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
    page.wait_for_function("(seq) => Number(document.body.getAttribute('data-last-seq')) >= seq", arg=seq, timeout=TIMEOUT_MS)


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


BLOCK_SEL = '#lanes li[data-lane="feat/fixture"] button.block'
LANE_FIXTURE = 'feat/fixture'
CLAIM_SEQ = 16
SYNTHETIC_STATES = ['PASS', 'FAIL', 'BLOCKED', 'STALLED', 'RUNNING', 'RUNNING', 'RUNNING', 'RUNNING']
KEEP_NODE_JS = '(sel) => { window.__blockNode = document.querySelector(sel); return window.__blockNode !== null; }'
SAME_NODE_JS = '(sel) => window.__blockNode !== null && window.__blockNode.isConnected && window.__blockNode === document.querySelector(sel)'
BG_JS = '(sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).backgroundColor : null; }'
RUNNING_JS = '() => document.getAnimations().filter((a) => a.playState === "running").length'
RAF_MEDIAN_JS = '''() => new Promise((resolve) => {
  const deltas = [];
  let last = null;
  const tick = (now) => {
    if (last !== null) deltas.push(now - last);
    last = now;
    if (deltas.length < 60) requestAnimationFrame(tick);
    else {
      deltas.sort((a, b) => a - b);
      resolve(deltas[Math.floor(deltas.length / 2)]);
    }
  };
  requestAnimationFrame(tick);
})'''
FOCUS_KEY_JS = '(key) => { const el = document.activeElement; return !!el && el.getAttribute("data-key") === key; }'
HOTKEY_STATE_JS = '''() => {
  const lane = document.querySelector('#lanes [aria-current=true]');
  const drill = document.getElementById('drill');
  const follow = document.getElementById('follow');
  return { drill: drill.hidden, selected: lane ? lane.getAttribute('data-lane') : null, follow: follow.getAttribute('aria-pressed') };
}'''
PROBE_JS = '''() => {
  const input = document.createElement('input');
  input.id = 'probe';
  document.body.appendChild(input);
  input.focus();
}'''
FONT_SIZE_JS = '() => parseFloat(getComputedStyle(document.body).fontSize)'
NO_OVERFLOW_JS = '() => document.documentElement.scrollWidth <= document.documentElement.clientWidth'


def _replay_lane(run_dir, gap=0.05):
    events = _fixture_events()
    events[CLAIM_SEQ - 1] = dict(events[CLAIM_SEQ - 1], lane=LANE_FIXTURE)
    _replay(run_dir, events, gap=gap)


def _emit_synthetic_lanes(run_dir):
    for number, state in enumerate(SYNTHETIC_STATES, start=1):
        lane = 'lane-%d' % number
        task = 'S%d' % number
        _emit(run_dir, {'kind': 'worker_claimed', 'source': 'worker', 'phase': 'executing', 'task_id': task,
                        'lane': lane, 'payload': {'lease_id': 'L-%d' % number}})
        if state == 'PASS':
            _emit(run_dir, {'kind': 'gate_evaluated', 'source': 'runner', 'phase': 'executing', 'task_id': task,
                            'lane': lane, 'refs': ['evidence-receipt.json'],
                            'payload': {'gate': 'evidence', 'verdict': 'pass', 'message': 'teste verde'}})
        elif state == 'FAIL':
            _emit(run_dir, {'kind': 'gate_evaluated', 'source': 'runner', 'phase': 'executing', 'task_id': task,
                            'lane': lane, 'payload': {'gate': 'quality', 'verdict': 'fail', 'message': 'qualidade reprovada'}})
        elif state == 'BLOCKED':
            _emit(run_dir, {'kind': 'apply_result', 'source': 'worker', 'phase': 'executing', 'task_id': task,
                            'lane': lane, 'payload': {'execution_state': 'blocked', 'message': 'operador bloqueado'}})
        elif state == 'STALLED':
            _emit(run_dir, {'kind': 'stall_detected', 'source': 'runner', 'phase': 'executing', 'task_id': task,
                            'lane': lane, 'payload': {'streak': 2}})


def _write_fps(median):
    target = os.environ.get('SL_SCREENSHOT_DIR')
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        (Path(target) / 'fps.json').write_text(json.dumps({'median_frame_ms': median, 'frames': 60}), encoding='utf-8')


def test_fixture_lane_logs_running_then_pass_within_one_second(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    page.wait_for_function("() => window.__laneLog.includes('PASS')", timeout=1000)
    assert page.evaluate('() => window.__laneLog') == ['RUNNING', 'PASS']


LANE_SEL = '#lanes li[data-lane="feat/fixture"]'
ARM_LANE_JS = '''(sel) => {
  if (window.__laneObs) window.__laneObs.disconnect();
  window.__laneAt = null;
  window.__laneObs = new MutationObserver(() => { if (window.__laneAt === null) window.__laneAt = Date.now(); });
  window.__laneObs.observe(document.querySelector(sel), { subtree: true, childList: true, attributes: true, attributeFilter: ['data-state'] });
}'''


def test_event_to_dom_latency_is_under_one_second_measured(open_page, repo):
    page = open_page('dark')
    run_dir = _run_dir(repo)
    _replay_lane(run_dir)
    _wait_seq(page, 28)
    page.wait_for_selector(LANE_SEL, timeout=TIMEOUT_MS)
    claim = _fixture_events()[CLAIM_SEQ - 1]
    samples = []
    for _ in range(5):
        # Observe only the lane: a document-wide observer would also catch the one-second tick and heartbeat renders.
        before = page.locator(LANE_SEL + ' button.block').count()
        page.evaluate(ARM_LANE_JS, LANE_SEL)
        host_ms = time.time() * 1000
        _emit(run_dir, claim)
        page.wait_for_function('() => window.__laneAt !== null', timeout=TIMEOUT_MS)
        samples.append(page.evaluate('() => window.__laneAt') - host_ms)
        assert page.locator(LANE_SEL + ' button.block').count() == before + 1
    if os.environ.get('SL_SCREENSHOT_DIR'):
        target = Path(os.environ['SL_SCREENSHOT_DIR'])
        target.mkdir(parents=True, exist_ok=True)
        (target / 'latency.json').write_text(json.dumps({
            'samples_ms': [round(s, 1) for s in samples],
            'median_ms': round(statistics.median(samples), 1),
            'max_ms': round(max(samples), 1),
            'method': 'host Date/ time.time() vs in-page Date.now() MutationObserver, same machine clock',
        }), encoding='utf-8')
    assert all(0 <= s < 1000 for s in samples), samples


def test_block_node_keeps_its_identity_across_a_tick(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    assert page.evaluate(KEEP_NODE_JS, BLOCK_SEL)
    page.wait_for_timeout(1200)
    assert page.evaluate(SAME_NODE_JS, BLOCK_SEL)


def test_eight_lanes_show_distinct_colours_for_pass_fail_blocked_and_stalled(open_page, repo):
    page = open_page('dark')
    _emit_synthetic_lanes(_run_dir(repo))
    page.wait_for_selector('#lanes li[data-lane="lane-8"]', timeout=TIMEOUT_MS)
    assert page.locator('#lanes li[data-lane]').count() == 8
    colours = {}
    for state in ('PASS', 'FAIL', 'BLOCKED', 'STALLED'):
        colours[state] = page.evaluate(BG_JS, '#lanes button.block[data-state="%s"]' % state)
    assert all(colours.values()), colours
    assert len(set(colours.values())) == 4, colours
    median = page.evaluate(RAF_MEDIAN_JS)
    _write_fps(median)
    assert median <= 25, median


def test_clicking_a_block_opens_the_drill_and_escape_restores_focus(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    block = page.locator('#lanes button.block').first
    key = block.get_attribute('data-key')
    block.click()
    page.wait_for_selector('#drill:not([hidden])', timeout=TIMEOUT_MS)
    page.keyboard.press('Escape')
    page.wait_for_selector('#drill[hidden]', state='attached', timeout=TIMEOUT_MS)
    assert page.evaluate(FOCUS_KEY_JS, key)


def test_clicking_a_phase_opens_the_drill(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    page.locator('#phase-stats button').first.click()
    page.wait_for_selector('#drill:not([hidden])', timeout=TIMEOUT_MS)


def test_block_data_tip_carries_the_timings(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    tip = page.get_attribute('#lanes button.block', 'data-tip')
    assert tip and re.search(r'\d', tip), tip


def test_hotkeys_j_k_g_l_are_ignored_while_typing_in_an_input(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    page.wait_for_selector('#lanes li[data-lane="feat/fixture"]', timeout=TIMEOUT_MS)
    before = page.evaluate(HOTKEY_STATE_JS)
    page.evaluate(PROBE_JS)
    page.locator('#probe').press_sequentially('jkgl')
    assert page.input_value('#probe') == 'jkgl'
    assert page.evaluate(HOTKEY_STATE_JS) == before


def test_ctrl_k_then_t1_selects_the_lane(open_page, repo):
    page = open_page('dark')
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    page.wait_for_selector('#lanes li[data-lane="feat/fixture"]', timeout=TIMEOUT_MS)
    page.keyboard.press('Control+k')
    page.keyboard.type('T1')
    page.keyboard.press('Enter')
    page.wait_for_selector('#lanes li[data-lane="feat/fixture"][aria-current="true"]', timeout=TIMEOUT_MS)


def test_board_scrolls_at_1920_and_the_last_column_is_reachable(open_page, repo):
    page = open_page('dark', viewport=(1920, 1080))
    _replay_lane(_run_dir(repo))
    _wait_seq(page, 18)
    page.wait_for_selector('#board > section', timeout=TIMEOUT_MS)
    before = page.evaluate('''() => {
      const board = document.getElementById('board');
      return { sections: board.querySelectorAll(':scope > section').length,
               overflows: board.scrollWidth > board.clientWidth };
    }''')
    # Eight phases on the rail plus the off-rail column; at 14rem each they need more than 1920 px, so the board scrolls.
    assert before == {'sections': 9, 'overflows': True}, before
    page.evaluate("() => { const b = document.getElementById('board'); b.scrollLeft = b.scrollWidth; }")
    reached = page.evaluate('''() => {
      const board = document.getElementById('board');
      return board.lastElementChild.getBoundingClientRect().right <= board.getBoundingClientRect().right + 1;
    }''')
    assert reached, 'the off-rail column must be reachable by scrolling the board'


def test_pause_holds_the_view_while_events_still_reduce_and_resume_shows_them(open_page, repo):
    page = open_page('dark')
    run_dir = _run_dir(repo)
    _replay_lane(run_dir)
    _wait_seq(page, 28)
    before = page.get_attribute('#follow', 'aria-pressed')
    page.click('#follow')
    page.wait_for_function("() => document.getElementById('follow').getAttribute('aria-pressed') !== '%s'" % before, timeout=TIMEOUT_MS)
    _emit(run_dir, {'kind': 'worker_claimed', 'source': 'worker', 'phase': 'executing', 'task_id': 'P1', 'lane': 'lane-paused'})
    _wait_seq(page, 29)
    assert page.locator('#lanes li[data-lane="lane-paused"]').count() == 0
    page.click('#follow')
    page.wait_for_function("() => document.getElementById('follow').getAttribute('aria-pressed') === '%s'" % before, timeout=TIMEOUT_MS)
    page.wait_for_selector('#lanes li[data-lane="lane-paused"]', timeout=TIMEOUT_MS)


def test_a_stall_shows_a_role_alert_toast(open_page, repo):
    page = open_page('dark')
    run_dir = _run_dir(repo)
    _replay_lane(run_dir)
    _wait_seq(page, 28)
    _emit(run_dir, {'kind': 'stall_detected', 'source': 'runner', 'phase': 'executing', 'task_id': 'T1',
                    'lane': LANE_FIXTURE, 'payload': {'streak': 2}})
    alert = page.locator('[role="alert"]').first
    alert.wait_for(state='visible', timeout=TIMEOUT_MS)
    assert alert.inner_text().strip()


def test_tv_mode_type_is_at_least_1_4_times_larger_and_fits_1080p(open_page):
    normal = open_page('dark', viewport=(1920, 1080))
    tv = open_page('dark', tv=True, viewport=(1920, 1080))
    assert tv.get_attribute('html', 'data-tv') == '1'
    ratio = tv.evaluate(FONT_SIZE_JS) / normal.evaluate(FONT_SIZE_JS)
    assert ratio >= 1.4, ratio
    assert tv.evaluate(NO_OVERFLOW_JS), 'horizontal overflow at 1920x1080'


def test_lanes_under_reduced_motion_run_no_animation_while_normal_motion_does(open_page, repo):
    _emit_synthetic_lanes(_run_dir(repo))
    normal = open_page('dark')
    normal.wait_for_selector('#lanes li[data-lane="lane-8"]', timeout=TIMEOUT_MS)
    assert normal.evaluate(RUNNING_JS) > 0
    reduced = open_page('dark', reduced_motion='reduce')
    reduced.wait_for_selector('#lanes li[data-lane="lane-8"]', timeout=TIMEOUT_MS)
    assert reduced.evaluate(RUNNING_JS) == 0


@pytest.mark.parametrize('theme, tv', [('dark', False), ('light', False), ('dark', True)], ids=['dark', 'light', 'tv'])
def test_axe_reports_no_serious_violation_with_the_drill_open(open_page, repo, theme, tv):
    _replay_lane(_run_dir(repo))
    page = open_page(theme, tv=tv)
    _wait_seq(page, 18)
    page.locator('#lanes button.block').first.click()
    page.wait_for_selector('#drill:not([hidden])', timeout=TIMEOUT_MS)
    page.evaluate(AXE_JS.read_text(encoding='utf-8'))
    violations = page.evaluate(AXE_RUN_JS)
    assert [v for v in violations if v['impact'] in ('serious', 'critical')] == [], violations


@pytest.mark.skipif(not os.environ.get('SL_SCREENSHOT_DIR'), reason='set SL_SCREENSHOT_DIR to write the dark, light and tv captures')
def test_capture_writes_dark_light_and_tv_pngs(open_page, repo):
    target = Path(os.environ['SL_SCREENSHOT_DIR'])
    target.mkdir(parents=True, exist_ok=True)
    _replay_lane(_run_dir(repo))
    for name, theme, tv in (('dark', 'dark', False), ('light', 'light', False), ('tv', 'dark', True)):
        page = open_page(theme, tv=tv, viewport=(1920, 1080))
        _wait_seq(page, 18)
        page.screenshot(path=str(target / (name + '.png')), full_page=True)
    assert all((target / (name + '.png')).stat().st_size > 0 for name in ('dark', 'light', 'tv'))

