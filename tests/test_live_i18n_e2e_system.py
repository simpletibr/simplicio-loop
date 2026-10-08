'''EN switch of the Live page in a real browser: ``?lang=en`` translates the chrome, the default stays pt-BR.'''
from __future__ import annotations

import pytest

pytest.importorskip('playwright.sync_api', reason='optional e2e extra (pip install -e .[e2e])')

from tests.test_live_board_e2e_system import TOKEN  # noqa: E402,F401
from tests.test_live_board_e2e_system import browser, repo, live_server, OPENED_RUN, TIMEOUT_MS  # noqa: E402,F401


def _open(browser, live_server, extra):
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    page.problems = []
    page.on('pageerror', lambda e: page.problems.append(str(e)))
    page.goto('http://127.0.0.1:%d/?t=%s&run=%s%s' % (live_server.port, TOKEN, OPENED_RUN, extra))
    page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
    return context, page


def test_default_is_pt_br(browser, live_server):
    context, page = _open(browser, live_server, '')
    try:
        assert page.get_attribute('html', 'lang') == 'pt-BR'
        assert page.inner_text('h1') == 'Pipeline vivo'
    finally:
        context.close()


def test_lang_en_translates_the_chrome_and_the_labels(browser, live_server):
    context, page = _open(browser, live_server, '&lang=en')
    try:
        assert page.get_attribute('html', 'lang') == 'en'
        assert page.inner_text('h1') == 'Live pipeline'
        assert page.inner_text('#follow') == 'Follow the run'
        assert page.get_attribute('#lanes', 'aria-label') == 'Run lanes'
        assert page.inner_text('#board-title') == 'Board by stage'
        assert page.problems == []
    finally:
        context.close()
