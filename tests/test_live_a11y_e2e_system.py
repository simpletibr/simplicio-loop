'''WCAG 2.2 AA end-to-end audit of the Simplicio Live pages in a real browser (issue #1409).

A real dashboard server runs on loopback. Each page is opened through Playwright and checked with axe-core using the
WCAG 2.0/2.1/2.2 A and AA tags plus best-practice. A check fails on ANY violation, whatever its impact, and the
failure message names the rule ids. The pages covered:

- the pipeline page populated by the runner-lifecycle fixture, in the dark, light and contrast themes;
- the board inside the same page, with four runs (intake, executing, blocked, done);
- the drill-down drawer opened with the ``l`` hotkey, and each of its six tabs;
- the TV mode (``tv=1``);
- keyboard use: Tab reaches the controls, each reached control shows a focus indicator, and Escape closes the drill and
  returns focus to the control that opened it;
- live regions: a phase change and an alert put their text inside a visible aria-live region;
- labels: ``html lang="pt-BR"`` and every visible control has an accessible name.

The optional e2e extra provides Playwright and axe (``pip install -e '.[e2e]'``). Chromium comes from
``python -m playwright install chromium``, from /opt/pw-browsers/chromium, or from a system Chrome or Edge.
'''
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

sync_api = pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')
axe_pkg = pytest.importorskip('axe_playwright_python', reason='optional e2e extra (pip install -e .[e2e])')

from simplicio_loop.dashboard import server  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / 'contracts' / 'dashboard-event' / 'v1' / 'fixtures' / 'runner-lifecycle.jsonl'
AXE_JS = Path(axe_pkg.__file__).with_name('axe.min.js')
CHROMIUM_PATH = Path('/opt/pw-browsers/chromium')
TOKEN = 'a11y-e2e-token-0123'
RUN_ID = 'run-fixture-lifecycle'
TIMEOUT_MS = 10000
LIFECYCLE_EVENTS = 28
SPEC_KEYS = ('task_id', 'scope', 'phase', 'lane', 'iteration', 'severity', 'payload', 'refs')
AXE_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']
DRILL_TABS = ['summary', 'logs', 'receipts', 'commands', 'contract', 'context']
THEMES = ['dark', 'light', 'contrast']
BOARD_RUNS = {
    'run-intake': ('intake', 'running'),
    'run-exec': ('executing', 'running'),
    'run-blocked': ('blocked', 'running'),
    'run-done': ('done', 'done'),
}
BOARD_OPENED_RUN = 'run-exec'
BOARD_COLUMNS = ['Contrato', 'Mapeamento', 'Plano', 'Execução', 'Validação', 'Watcher', 'Entrega', 'Concluído',
                 'Fora do trilho']

AXE_RUN_JS = '''async (tags) => (await axe.run(document, {
  runOnly: { type: 'tag', values: tags },
  resultTypes: ['violations'],
})).violations.map((v) => ({
  id: v.id,
  impact: v.impact,
  nodes: v.nodes.length,
  targets: v.nodes.slice(0, 3).map((n) => n.target.join(' ')),
}))'''

INIT_SCRIPT = r'''
window.__csp = [];
document.addEventListener('securitypolicyviolation', (e) => window.__csp.push(e.violatedDirective));
'''

# Walks the light DOM and every open shadow root. Returns the live regions that are rendered (have a box).
LIVE_REGIONS_JS = r'''() => {
  const out = [];
  const visit = (root) => {
    for (const el of root.querySelectorAll('*')) {
      const live = el.getAttribute('aria-live');
      const role = el.getAttribute('role');
      const isLive = (live && live !== 'off') || ['status', 'alert', 'log'].includes(role);
      if (isLive) {
        const own = el.textContent || '';
        const shadow = el.shadowRoot ? el.shadowRoot.textContent || '' : '';
        out.push({
          id: el.id || null,
          tag: el.localName,
          mode: live || role,
          shown: el.getClientRects().length > 0,
          text: (own + ' ' + shadow).replace(/\s+/g, ' ').trim(),
        });
      }
      if (el.shadowRoot) visit(el.shadowRoot);
    }
  };
  visit(document);
  return out;
}'''

# The element that holds focus, descending into open shadow roots, with its computed focus indicator.
DEEP_FOCUS_JS = r'''() => {
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el || el === document.body) return null;
  const cs = getComputedStyle(el);
  const host = el.getRootNode().host;
  const outlined = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  return {
    tag: el.localName,
    role: el.getAttribute('role'),
    id: el.id || null,
    host: host ? host.localName : null,
    text: (el.getAttribute('aria-label') || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
    ring: outlined || cs.boxShadow !== 'none',
    outline: cs.outlineStyle + ' ' + cs.outlineWidth,
    shadow: cs.boxShadow,
  };
}'''

# Visible controls, in the light DOM and in open shadow roots, with the name a screen reader would announce.
NAMES_JS = r'''() => {
  const CONTROL = 'button, a[href], input:not([type=hidden]), select, textarea, [role=button], [role=tab], '
    + '[role=link], [role=checkbox], [role=switch], [role=treeitem], [role=gridcell], [role=option], [role=combobox]';
  const nameOf = (el) => {
    const root = el.getRootNode();
    const labelledby = el.getAttribute('aria-labelledby');
    if (labelledby) {
      const text = labelledby.split(/\s+/).map((id) => root.getElementById(id)).filter(Boolean)
        .map((n) => n.textContent).join(' ').trim();
      if (text) return text;
    }
    const aria = (el.getAttribute('aria-label') || '').trim();
    if (aria) return aria;
    if (el.id && root.querySelector('label[for="' + el.id + '"]')) return 'label';
    if (el.closest('label')) return 'label';
    if (el.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(el.type)) return el.value || '';
    if (el.tagName === 'INPUT' && el.type === 'image') return el.alt || '';
    if (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA') return el.title || '';
    return (el.textContent || el.title || '').replace(/\s+/g, ' ').trim();
  };
  const out = [];
  const visit = (root) => {
    for (const el of root.querySelectorAll(CONTROL)) {
      if (el.getClientRects().length === 0) continue;
      out.push({ tag: el.localName, id: el.id || null, name: nameOf(el) });
    }
    for (const el of root.querySelectorAll('*')) if (el.shadowRoot) visit(el.shadowRoot);
  };
  visit(document);
  return out;
}'''


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_run(root, run_id, phase, status):
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {'run_id': run_id, 'status': status, 'phase': phase, 'repo': str(root), 'updated_at': _now_iso()}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')


def _run_dir(repo, run_id=RUN_ID):
    return repo / '.simplicio-loop' / 'loop-runs' / run_id


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
    page.wait_for_function("(seq) => Number(document.body.getAttribute('data-last-seq')) >= seq", arg=seq,
                           timeout=TIMEOUT_MS)


def _axe(page):
    """Runs axe on the whole page and returns the violations as dicts."""
    page.evaluate(AXE_JS.read_text(encoding='utf-8'))
    return page.evaluate(AXE_RUN_JS, AXE_TAGS)


def _assert_no_violations(page, where):
    violations = _axe(page)
    assert violations == [], '%s: %s' % (where, [(v['id'], v['impact'], v['targets']) for v in violations])


def _live_text_has(page, word):
    return any(r['shown'] and word in r['text'] for r in page.evaluate(LIVE_REGIONS_JS))


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
def board_repo(tmp_path):
    root = tmp_path / 'board'
    for run_id, (phase, status) in BOARD_RUNS.items():
        _write_run(root, run_id, phase, status)
    return root


@pytest.fixture
def live_server(repo):
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN, heartbeat_seconds=0.2)
    yield handle
    handle.stop()


@pytest.fixture
def board_server(board_repo):
    handle = server.start(repo_root=board_repo, host='127.0.0.1', port=0, token=TOKEN)
    yield handle
    handle.stop()


@pytest.fixture
def open_page(browser, live_server):
    contexts = []

    def _open(theme='dark', tv=False, viewport=(1280, 900)):
        context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.add_init_script(INIT_SCRIPT)
        page.goto('http://127.0.0.1:%d/?t=%s&theme=%s&run=%s%s' % (
            live_server.port, TOKEN, theme, RUN_ID, '&tv=1' if tv else ''))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


@pytest.fixture
def open_board(browser, board_server):
    contexts = []

    def _open(viewport=(1280, 900)):
        context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.goto('http://127.0.0.1:%d/?t=%s&run=%s' % (board_server.port, TOKEN, BOARD_OPENED_RUN))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        page.wait_for_function(
            "() => ['run-intake','run-exec','run-blocked','run-done'].every((id) => "
            "document.querySelector('#board a[href*=\"run=' + id + '\"]'))", timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


@pytest.mark.parametrize('theme', THEMES)
def test_pipeline_populated_by_the_lifecycle_has_no_wcag_violations(open_page, repo, theme):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page(theme)
    _wait_seq(page, LIFECYCLE_EVENTS)
    assert page.get_attribute('html', 'data-sl-theme') == theme
    _assert_no_violations(page, 'pipeline %s' % theme)
    assert page.problems == []


def test_board_with_four_runs_has_no_wcag_violations(open_board):
    page = open_board()
    board = page.evaluate(
        "() => [...document.querySelectorAll('#board section h3')].map((h) => h.textContent.replace(/[\\d()\\s]+/g, ' ').trim())")
    assert board == BOARD_COLUMNS, board
    _assert_no_violations(page, 'board')
    assert page.problems == []


def test_drill_opened_with_l_and_each_of_its_six_tabs_has_no_wcag_violations(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark')
    _wait_seq(page, LIFECYCLE_EVENTS)
    page.keyboard.press('l')
    page.wait_for_selector('#drill:not([hidden])', timeout=TIMEOUT_MS)
    _assert_no_violations(page, 'drill logs (opened with l)')
    for name in DRILL_TABS:
        page.click('#drill-tab-%s' % name)
        page.wait_for_function(
            "(name) => document.getElementById('drill-tab-' + name).getAttribute('aria-selected') === 'true'"
            " && !document.getElementById('drill-panel-' + name).hidden", arg=name, timeout=TIMEOUT_MS)
        _assert_no_violations(page, 'drill tab %s' % name)
    assert page.problems == []


def test_tv_mode_has_no_wcag_violations(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark', tv=True)
    _wait_seq(page, LIFECYCLE_EVENTS)
    assert page.get_attribute('html', 'data-tv') == '1'
    _assert_no_violations(page, 'tv mode')


def test_tab_reaches_controls_and_each_shows_a_focus_indicator(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark')
    _wait_seq(page, LIFECYCLE_EVENTS)
    page.evaluate('() => document.activeElement && document.activeElement.blur()')
    reached = []
    for _ in range(80):
        page.keyboard.press('Tab')
        info = page.evaluate(DEEP_FOCUS_JS)
        if info is None:
            break
        key = (info['host'], info['tag'], info['id'], info['text'])
        if reached and key == (reached[0]['host'], reached[0]['tag'], reached[0]['id'], reached[0]['text']):
            break
        reached.append(info)
    names = [(i['id'] or i['host'] or i['text']) for i in reached]
    assert len(reached) >= 5, names
    assert 'follow' in [i['id'] for i in reached], names
    assert 'alerts-toggle' in [i['id'] for i in reached], names
    assert 'sl-command-palette' in [i['host'] for i in reached], names
    unmarked = [i for i in reached if not i['ring']]
    assert unmarked == [], [(i['tag'], i['id'], i['host'], i['text'], i['outline'], i['shadow']) for i in unmarked]


def test_escape_closes_the_drill_and_returns_focus_to_the_opener(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark')
    _wait_seq(page, LIFECYCLE_EVENTS)
    phase_button = page.locator('#phase-stats li[data-phase="executing"] button')
    phase_button.focus()
    page.keyboard.press('Enter')
    page.wait_for_selector('#drill:not([hidden])', timeout=TIMEOUT_MS)
    page.keyboard.press('Escape')
    page.wait_for_selector('#drill[hidden]', state='attached', timeout=TIMEOUT_MS)
    focused = page.evaluate(
        "() => { const el = document.activeElement; return el && el.parentElement ? el.parentElement.dataset.phase : null; }")
    assert focused == 'executing', focused


def test_a_phase_change_is_announced_in_a_live_region(open_page, repo):
    run_dir = _run_dir(repo)
    events = _fixture_events()
    page = open_page('dark')
    _replay(run_dir, events[:5])
    _wait_seq(page, 5)
    assert not _live_text_has(page, 'Contexto mapeado')
    _emit(run_dir, events[5])
    _wait_seq(page, 6)
    deadline = time.time() + 3
    while time.time() < deadline and not _live_text_has(page, 'Contexto mapeado'):
        page.wait_for_timeout(100)
    regions = page.evaluate(LIVE_REGIONS_JS)
    assert _live_text_has(page, 'Contexto mapeado'), regions


def test_an_alert_is_announced_in_a_live_region(open_page, repo):
    run_dir = _run_dir(repo)
    page = open_page('dark')
    _replay(run_dir, _fixture_events())
    _wait_seq(page, LIFECYCLE_EVENTS)
    _emit(run_dir, {'kind': 'stall_detected', 'source': 'runner', 'phase': 'executing', 'payload': {'streak': 2}})
    _wait_seq(page, LIFECYCLE_EVENTS + 1)
    deadline = time.time() + 3
    while time.time() < deadline and not _live_text_has(page, 'sem avanço'):
        page.wait_for_timeout(100)
    regions = page.evaluate(LIVE_REGIONS_JS)
    assert _live_text_has(page, 'sem avanço'), regions


def test_html_is_pt_br_and_every_visible_control_has_an_accessible_name(open_page, repo):
    _replay(_run_dir(repo), _fixture_events())
    page = open_page('dark')
    _wait_seq(page, LIFECYCLE_EVENTS)
    assert page.get_attribute('html', 'lang') == 'pt-BR'
    controls = page.evaluate(NAMES_JS)
    assert len(controls) >= 5, controls
    unnamed = [c for c in controls if not c['name'].strip()]
    assert unnamed == [], unnamed
