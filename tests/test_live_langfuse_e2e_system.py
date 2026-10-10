"""End-to-end checks of the Simplicio Live Langfuse panel in a real browser (issue #1610).

The dashboard server runs over loopback on a temporary git repo whose default branch holds the loop.toml. Checks: the trace
link, the chip and the queue size in dark and light; off shows the chip and nothing else; a phone-width page with no
horizontal scroll; names from events never become markup; an unreachable Langfuse host leaves the page working with no
request leaving loopback; no key anywhere in the DOM; axe on the panel. Set ``SL_SCREENSHOT_DIR=<dir>`` to also write the dark, light and phone PNGs of the panel. Requires the optional e2e extra:

    pip install -e ".[e2e]" && python -m playwright install chromium   # or SL_CHROMIUM_PATH=<chrome binary>
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")
axe_pkg = pytest.importorskip("axe_playwright_python", reason="optional e2e extra: pip install -e '.[e2e]'")

from simplicio_loop.dashboard import server  # noqa: E402
from tests.test_dashboard_langfuse_view_unit import (HOST, PUBLIC, RUN_ID, SECRET, TRACE_ID, _report, _write_events, export, lf_dir,  # noqa: E402
                                                     make_repo, on, outbox)

TOKEN = "langfuse-e2e-token-0123"
TIMEOUT_MS = 10000
AXE_JS = Path(axe_pkg.__file__).with_name("axe.min.js")
PHONE = (390, 844)
DESKTOP = (1280, 900)
OVERFLOW_JS = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
PANEL = "#live-langfuse"
PANEL_INSIDE_JS = """() => [...document.querySelectorAll('#live-langfuse, #live-langfuse *')]
  .every((el) => el.getBoundingClientRect().right <= window.innerWidth + 0.5)"""


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        launched = None
        errors = []
        candidates = ({"executable_path": os.environ["SL_CHROMIUM_PATH"]},) if os.environ.get("SL_CHROMIUM_PATH") else ()
        for options in candidates + ({}, {"channel": "chrome"}, {"channel": "msedge"}):
            try:
                launched = pw.chromium.launch(**options)
                break
            except Exception as exc:  # browser binary not installed for this option
                errors.append(str(exc).splitlines()[0])
        if launched is None:
            pytest.skip("no Chromium/Chrome available: " + " | ".join(errors))
        yield launched
        launched.close()


@pytest.fixture
def serve(tmp_path):
    handles = []

    def start(toml, **kwargs):
        ref = make_repo(tmp_path, toml, **kwargs)
        state = {"run_id": RUN_ID, "status": "running", "phase": "executing", "percent": 50, "repo": ref["repo"],
                 "started_at": "2026-10-08T10:00:00Z", "updated_at": "2026-10-08T10:00:00Z"}
        (Path(ref["run_dir"]) / "state.json").write_text(json.dumps(state), encoding="utf-8")
        handle = server.start(repo_root=ref["repo"], host="127.0.0.1", port=0, token=TOKEN, heartbeat_seconds=0.2)
        handles.append(handle)
        return ref, handle.port

    yield start
    for handle in handles:
        handle.stop()


def _open(browser, port, theme="dark", viewport=DESKTOP, requests=None):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append("pageerror: %s" % e))
    if requests is not None:
        page.on("request", lambda request: requests.append(request.url))
    page.goto("http://127.0.0.1:%d/?t=%s&theme=%s&run=%s" % (port, TOKEN, theme, RUN_ID))
    page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
    return context, page


def _shot(page, name):
    target = os.environ.get("SL_SCREENSHOT_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        page.locator(PANEL).screenshot(path=str(Path(target) / (name + ".png")))


def test_link_chip_and_queue_show_in_dark_and_light(browser, serve):
    ref, port = serve(on(), report=_report(), gates={"tests": True})
    export(ref)
    for _ in range(2):
        outbox(ref).enqueue("traces", {"x": 1})
    for theme in ("dark", "light"):
        context, page = _open(browser, port, theme=theme)
        try:
            page.wait_for_selector(PANEL + " .lf-link", timeout=TIMEOUT_MS)
            link = page.locator(PANEL + " .lf-link")
            assert link.get_attribute("href") == "%s/trace/%s" % (HOST, TRACE_ID)
            assert link.get_attribute("rel") == "noopener noreferrer" and link.get_attribute("target") == "_blank"
            assert page.locator(PANEL + " .lf-chip").inner_text().startswith("Langfuse:")
            assert "2" in page.locator(PANEL + " .lf-queue").inner_text()
            assert page.locator(PANEL + " iframe").count() == 0
            _shot(page, "langfuse-" + theme)
            assert page.problems == []
        finally:
            context.close()


def test_off_shows_only_the_chip(browser, serve):
    _, port = serve(None, report=_report(), gates={"tests": True})
    context, page = _open(browser, port)
    try:
        page.wait_for_selector(PANEL + " .lf-chip", timeout=TIMEOUT_MS)
        assert page.locator(PANEL + " .lf-chip").inner_text() == "Langfuse: desligado"
        assert page.locator(PANEL + " a, " + PANEL + " ul, " + PANEL + " .lf-queue, " + PANEL + " .lf-warn").count() == 0
        assert page.locator(PANEL + " *").count() == page.locator(PANEL + " p, " + PANEL + " p *").count()
        assert page.problems == []
    finally:
        context.close()


def test_phone_width_keeps_the_panel_inside_the_page(browser, serve):
    ref, port = serve(on(), report=_report(), gates={"g" * 150: True})  # one 150-character gate name with no break point
    export(ref)
    context, page = _open(browser, port, viewport=PHONE)
    try:
        page.wait_for_selector(PANEL + " .lf-gates li", timeout=TIMEOUT_MS)
        page.locator(PANEL).scroll_into_view_if_needed()
        assert page.evaluate(OVERFLOW_JS) is True
        assert page.evaluate(PANEL_INSIDE_JS) is True
        _shot(page, "langfuse-phone")
        assert page.problems == []
    finally:
        context.close()


def test_a_gate_name_from_events_never_becomes_markup(browser, serve):
    xss = '<img src=x onerror="window.__xss=1">'
    ref, port = serve(on(), report=_report(), gates={xss: True})
    export(ref)
    for theme in ("dark", "light"):
        context, page = _open(browser, port, theme=theme)
        try:
            page.wait_for_selector(PANEL + " .lf-gates li", timeout=TIMEOUT_MS)
            assert page.evaluate("() => window.__xss") is None
            assert page.locator(PANEL + " img").count() == 0
            assert xss in page.locator(PANEL + " .lf-gates").inner_text()
            assert page.problems == []
        finally:
            context.close()


def test_a_diverged_gate_raises_the_warning(browser, serve):
    ref, port = serve(on(), report=_report(), gates={"tests": True})
    export(ref)
    _write_events(Path(ref["run_dir"]), {"tests": False})
    context, page = _open(browser, port)
    try:
        page.wait_for_selector(PANEL + " .lf-warn", timeout=TIMEOUT_MS)
        assert page.locator(PANEL + " .lf-warn").get_attribute("role") == "alert"
        assert "diferentes" in page.locator(PANEL + " .lf-warn").inner_text()
    finally:
        context.close()


def test_with_langfuse_down_the_page_works_requests_only_loopback_and_no_key_is_in_the_dom(browser, serve, monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC)
    ref, port = serve(on("http://127.0.0.1:1"), report=_report(), gates={"tests": True})  # nothing listens on port 1
    lf_dir(ref).mkdir(parents=True, exist_ok=True)
    (lf_dir(ref) / "credentials.json").write_text(json.dumps({"public_key": PUBLIC, "secret_key": SECRET}), encoding="utf-8")
    outbox(ref).enqueue("traces", {"x": 1})
    requests: list[str] = []
    context, page = _open(browser, port, requests=requests)
    try:
        page.wait_for_selector(PANEL + " .lf-link", timeout=TIMEOUT_MS)
        assert page.locator(".board-panel").is_visible() and page.locator("#live-extras").is_visible()
        html = page.content()
        assert SECRET not in html and PUBLIC not in html and "sk-lf-" not in html
        origin = "http://127.0.0.1:%d/" % port
        assert requests and all(url.startswith(origin) for url in requests), [u for u in requests if not u.startswith(origin)]
        assert page.problems == []
    finally:
        context.close()


def test_axe_reports_no_serious_or_critical_violation_in_the_langfuse_panel(browser, serve):
    ref, port = serve(on(), report=_report(), gates={"tests": True, "lint": False})
    export(ref)
    _write_events(Path(ref["run_dir"]), {"tests": False, "lint": False})  # the warning is on screen too
    for theme in ("dark", "light"):
        context, page = _open(browser, port, theme=theme)
        try:
            page.wait_for_selector(PANEL + " .lf-warn", timeout=TIMEOUT_MS)
            page.evaluate(AXE_JS.read_text(encoding="utf-8"))  # evaluate, not a script tag: the page CSP forbids inline scripts
            violations = page.evaluate(
                """async () => (await axe.run(document.querySelector('#live-langfuse'), { resultTypes: ['violations'] })).violations
                  .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))""")
            assert [v for v in violations if v["impact"] in ("serious", "critical")] == [], (theme, violations)
        finally:
            context.close()
