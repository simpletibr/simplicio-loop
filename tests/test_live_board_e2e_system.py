'''End-to-end system test of the Simplicio Live kanban board in a real browser.

A real dashboard server runs on loopback over one repo with four runs (intake, executing, blocked, done). Playwright
opens the live page at ``/?t=<token>&run=run-exec`` and checks the board inside ``#board``:

- nine columns in a fixed order, read from each column's ``h3`` (the label, without the count);
- one card per run in its column (Contrato, Execução, Fora do trilho, Concluído) and none in the other columns;
- ``aria-current="true"`` on the card of the run in the URL only;
- a click on a card changes the ``run`` parameter of the URL;
- the board polls ``/api/runs`` every 3 s, so a run written to disk later shows up in its column within 8 s;
- no console errors or page errors, and no horizontal scroll at a 375 px viewport.

DOM contract the tests rely on: each column is a ``section`` under ``#board`` with an ``h3``; each card is a link whose
``run`` query parameter names the run. ``aria-current`` is read from the card link or from its wrapping ``li`` or
``article``.

The optional e2e extra provides Playwright (``pip install -e '.[e2e]'``). Chromium comes from
``python -m playwright install chromium``, from /opt/pw-browsers/chromium, or from a system Chrome or Edge.
'''
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sync_api = pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')

from simplicio_loop.dashboard import server  # noqa: E402

CHROMIUM_PATH = Path('/opt/pw-browsers/chromium')
TOKEN = 'board-e2e-token-0123'
TIMEOUT_MS = 10000
POLL_WAIT_MS = 8000  # the board polls every 3 s: one poll plus margin
PHONE_WIDTH = 375
PHONE_HEIGHT = 812
DESKTOP_VIEWPORT = (1280, 900)
COLUMNS = ['Contrato', 'Mapeamento', 'Plano', 'Execução', 'Validação', 'Watcher', 'Entrega', 'Concluído',
           'Fora do trilho']
# Run id -> (phase, status) written to state.json.
RUNS = {
    'run-intake': ('intake', 'running'),
    'run-exec': ('executing', 'running'),
    'run-blocked': ('blocked', 'running'),
    'run-done': ('done', 'done'),
}
OPENED_RUN = 'run-exec'
# Column label -> the run ids whose cards sit in it. A column that is not listed holds no card.
PLACEMENT = {
    'Contrato': ['run-intake'],
    'Execução': ['run-exec'],
    'Concluído': ['run-done'],
    'Fora do trilho': ['run-blocked'],
}

# Shared by the scripts below. The label drops the count (digits and brackets); a column is a section under #board
# that holds an h3, and its cards are the links that carry a run parameter.
BOARD_LIB_JS = r'''
  const labelOf = (text) => String(text).normalize('NFC').replace(/[\d()\s]+/g, ' ').trim();
  const runOf = (link) => {
    try { return new URL(link.getAttribute('href'), location.href).searchParams.get('run'); }
    catch (error) { return null; }
  };
  const columnsOf = () => {
    const board = document.getElementById('board');
    if (!board) return [];
    return [...board.querySelectorAll('section')]
      .filter((section) => {
        const outer = section.parentElement && section.parentElement.closest('section');
        return !(outer && outer !== board && board.contains(outer));
      })
      .map((section) => {
        const heading = section.querySelector('h3');
        const cards = [...section.querySelectorAll('a[href]')]
          .filter((link) => runOf(link))
          .map((link) => ({
            run: runOf(link),
            current: [link, link.closest('li, article')].some(
              (el) => el !== null && el.getAttribute('aria-current') === 'true'),
          }));
        return { label: heading ? labelOf(heading.textContent) : null, cards };
      });
  };
'''
COLUMNS_JS = '() => {' + BOARD_LIB_JS + ' return columnsOf(); }'
CARDS_PRESENT_JS = ('(ids) => {' + BOARD_LIB_JS +
                    ' const seen = new Set(columnsOf().flatMap((c) => c.cards.map((card) => card.run)));'
                    ' return ids.every((id) => seen.has(id)); }')
RUN_IN_COLUMN_JS = ('(arg) => {' + BOARD_LIB_JS +
                    ' return columnsOf().some((c) => c.label === arg.column'
                    ' && c.cards.some((card) => card.run === arg.run)); }')
DOCUMENT_SCROLL_WIDTH_JS = '() => document.documentElement.scrollWidth'


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_run(root, run_id, phase, status):
    run_dir = root / '.simplicio-loop' / 'loop-runs' / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    state = {'run_id': run_id, 'status': status, 'phase': phase, 'repo': str(root), 'updated_at': _now_iso()}
    (run_dir / 'state.json').write_text(json.dumps(state), encoding='utf-8')


def _run_param(url):
    return parse_qs(urlparse(url).query).get('run', [None])[0]


def _board(page):
    return page.evaluate(COLUMNS_JS)


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
    for run_id, (phase, status) in RUNS.items():
        _write_run(root, run_id, phase, status)
    return root


@pytest.fixture
def live_server(repo):
    handle = server.start(repo_root=repo, host='127.0.0.1', port=0, token=TOKEN)
    yield handle
    handle.stop()


@pytest.fixture
def open_board(browser, live_server):
    contexts = []

    def _open(viewport=DESKTOP_VIEWPORT):
        context = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(TIMEOUT_MS)
        page.problems = []
        page.on('console', lambda m: page.problems.append('%s: %s' % (m.type, m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: page.problems.append('pageerror: %s' % e))
        page.goto('http://127.0.0.1:%d/?t=%s&run=%s' % (live_server.port, TOKEN, OPENED_RUN))
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        page.wait_for_selector('#board section h3', state='attached', timeout=TIMEOUT_MS)
        page.wait_for_function(CARDS_PRESENT_JS, arg=list(RUNS), timeout=TIMEOUT_MS)
        return page

    yield _open
    for context in contexts:
        context.close()


def test_board_has_nine_columns_in_the_fixed_order(open_board):
    page = open_board()
    labels = [column['label'] for column in _board(page)]
    assert labels == COLUMNS, labels


def test_each_run_card_sits_in_its_phase_column_and_no_other(open_board):
    page = open_board()
    placement = [(column['label'], [card['run'] for card in column['cards']]) for column in _board(page)]
    assert placement == [(label, PLACEMENT.get(label, [])) for label in COLUMNS], placement


def test_only_the_card_of_the_opened_run_is_marked_current(open_board):
    page = open_board()
    current = [card['run'] for column in _board(page) for card in column['cards'] if card['current']]
    assert current == [OPENED_RUN], current


def test_clicking_a_card_changes_the_run_parameter_of_the_url(open_board):
    page = open_board()
    page.locator('#board a[href*="run=run-blocked"]').first.click()
    page.wait_for_url(lambda url: _run_param(url) == 'run-blocked', timeout=TIMEOUT_MS)


def test_a_run_written_after_load_appears_in_its_column_within_one_poll(open_board, repo):
    page = open_board()
    _write_run(repo, 'run-new', 'planning', 'running')
    page.wait_for_function(RUN_IN_COLUMN_JS, arg={'run': 'run-new', 'column': 'Plano'}, timeout=POLL_WAIT_MS)


def test_loading_and_polling_the_board_logs_no_console_or_page_errors(open_board, repo):
    page = open_board()
    assert page.problems == [], page.problems
    _write_run(repo, 'run-new', 'planning', 'running')
    page.wait_for_function(RUN_IN_COLUMN_JS, arg={'run': 'run-new', 'column': 'Plano'}, timeout=POLL_WAIT_MS)
    assert page.problems == [], page.problems


def test_board_has_no_horizontal_scroll_at_phone_width(open_board):
    page = open_board(viewport=(PHONE_WIDTH, PHONE_HEIGHT))
    scroll_width = page.evaluate(DOCUMENT_SCROLL_WIDTH_JS)
    assert scroll_width <= PHONE_WIDTH, scroll_width
