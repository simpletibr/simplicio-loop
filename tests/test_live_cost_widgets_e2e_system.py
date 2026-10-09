"""End-to-end checks of the Simplicio Live cost widgets in a real browser (issue #1404, cost widgets).

The dashboard server runs over loopback on a temporary repo. The token_usage events go through the real dashboard_events
emitter before the page opens (the budget is read on load; it is polled every 30 s). Checks: measured bars and the cost per
task and per iteration in dark and light, the UNVERIFIED state with no bar, a phone-width page with no horizontal scroll,
an offline DOM snapshot that requests nothing but loopback, and axe on the agents panel. Requires the optional e2e extra:

    pip install -e ".[e2e]" && python -m playwright install chromium   # or a system Chrome

Set ``SL_SCREENSHOT_DIR=<dir>`` to also write the dark, light and phone PNGs of the agents panel.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")
axe_pkg = pytest.importorskip("axe_playwright_python", reason="optional e2e extra: pip install -e '.[e2e]'")

from simplicio_loop.dashboard import budget, server  # noqa: E402
from simplicio_loop.dashboard_events import load  # noqa: E402

TOKEN = "cost-e2e-token-0123"
RUN_ID = "run-cost-widgets"
TIMEOUT_MS = 10000
MODEL = "claude-haiku-5-5"
RATES = json.loads(Path(budget.__file__).with_name("prices.json").read_text(encoding="utf-8"))["models"][MODEL]
AXE_JS = Path(axe_pkg.__file__).with_name("axe.min.js")
PHONE = (390, 844)
DESKTOP = (1280, 900)
OVERFLOW_JS = "() => document.documentElement.scrollWidth <= document.documentElement.clientWidth"
PANEL_INSIDE_JS = """() => [...document.querySelectorAll('.cost-block')]
  .every((el) => el.getBoundingClientRect().right <= window.innerWidth + 0.5)"""
BARS_JS = "() => [...document.querySelectorAll('#token-bars progress')].map((p) => Number(p.value))"
# sl-gate-badge draws its text inside a shadow root, so the rows are read from the badge attributes.
BADGES_JS = """(sel) => [...document.querySelectorAll(sel + ' sl-gate-badge')]
  .map((b) => ({ gate: b.getAttribute('gate'), state: b.getAttribute('state'), reason: b.getAttribute('reason') }))"""


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
def repo(tmp_path):
    root = tmp_path / "repo"
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True)
    state = {"run_id": RUN_ID, "status": "running", "phase": "executing", "percent": 50, "repo": str(root),
             "started_at": "2026-10-08T10:00:00Z", "updated_at": "2026-10-08T10:00:00Z"}
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return root


@pytest.fixture
def live_server(repo):
    handle = server.start(repo_root=repo, host="127.0.0.1", port=0, token=TOKEN, heartbeat_seconds=0.2)
    yield handle
    handle.stop()


def _run_dir(repo):
    return repo / ".simplicio-loop" / "loop-runs" / RUN_ID


def _emit_usage(run_dir, task_id, phase, lane, tokens_in, tokens_out, iteration=None):
    emitter = load()
    assert emitter is not None, "dashboard_events emitter is missing"
    payload = {"input_tokens": tokens_in, "output_tokens": tokens_out, "model": MODEL}
    return emitter.emit(run_dir, "token_usage", source="runner", strict=True, task_id=task_id, phase=phase, lane=lane,
                        iteration=iteration, payload=payload)


def _seed_measured_usage(repo):
    run_dir = _run_dir(repo)
    _emit_usage(run_dir, "T1", "executing", "route-a", 1_000_000, 0, iteration=1)
    _emit_usage(run_dir, "T2", "validating", "route-b", 0, 500_000)


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
        page.locator(".agents-panel").screenshot(path=str(Path(target) / (name + ".png")))


def test_measured_bars_and_cost_per_task_and_iteration_show_in_dark_and_light(browser, live_server, repo):
    _seed_measured_usage(repo)
    expected_t1 = 1_000_000 * RATES["input_per_mtok"] / 1_000_000
    expected_t2 = 500_000 * RATES["output_per_mtok"] / 1_000_000
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#token-bars progress", timeout=TIMEOUT_MS)
            # Two phases, then the one model: the values are the measured counts, the max is the measured total.
            assert page.evaluate(BARS_JS) == [1_000_000, 500_000, 1_500_000]
            assert "1.500.000 tokens" in page.inner_text("#token-bars")
            tasks = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#task-cost")}
            assert tasks["Tarefa T1"]["state"] == "ESTIMADO"
            assert "1.000.000 tokens" in tasks["Tarefa T1"]["reason"] and "USD %.4f estimado" % expected_t1 in tasks["Tarefa T1"]["reason"]
            assert tasks["Tarefa T2"]["state"] == "ESTIMADO"
            assert "500.000 tokens" in tasks["Tarefa T2"]["reason"] and "USD %.4f estimado" % expected_t2 in tasks["Tarefa T2"]["reason"]
            iterations = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#iteration-cost")}
            assert iterations["Iteração 1"]["state"] == "ESTIMADO"
            assert iterations["Sem iteração identificada"]["state"] == "ESTIMADO"
            assert page.inner_text("#task-cost-note").startswith("USD estimado")
            _shot(page, "cost-" + theme)
            assert page.problems == []
        finally:
            context.close()


def test_unmeasured_run_draws_no_bar_and_says_why(browser, live_server):
    context, page = _open(browser, live_server.port, theme="dark")
    try:
        page.wait_for_function("() => document.querySelector('#token-bars-note').textContent.includes('token_usage')")
        assert page.evaluate(BARS_JS) == []
        assert page.evaluate(BADGES_JS, "#task-cost") == []
        assert page.evaluate(BADGES_JS, "#iteration-cost") == []
        assert "task_id" in page.inner_text("#task-cost-note")
        assert "iteração" in page.inner_text("#iteration-cost-note")
        assert page.problems == []
    finally:
        context.close()


def test_phone_width_keeps_the_cost_widgets_inside_the_page(browser, live_server, repo):
    _seed_measured_usage(repo)
    context, page = _open(browser, live_server.port, theme="dark", viewport=PHONE)
    try:
        page.wait_for_selector("#token-bars progress", timeout=TIMEOUT_MS)
        assert page.evaluate(OVERFLOW_JS) is True
        assert page.evaluate(PANEL_INSIDE_JS) is True
        page.locator(".cost-widgets").scroll_into_view_if_needed()
        assert page.evaluate(OVERFLOW_JS) is True
        _shot(page, "cost-phone")
        assert page.problems == []
    finally:
        context.close()


def test_the_cost_markup_is_a_stable_offline_snapshot_that_requests_only_loopback(browser, live_server, repo):
    _seed_measured_usage(repo)
    requests: list[str] = []
    context, page = _open(browser, live_server.port, theme="light", requests=requests)
    try:
        page.wait_for_selector("#token-bars progress", timeout=TIMEOUT_MS)
        first = page.evaluate("() => document.querySelector('.cost-widgets').outerHTML")
        time.sleep(0.5)
        second = page.evaluate("() => document.querySelector('.cost-widgets').outerHTML")
        assert first == second
        assert "<script" not in first and "http://" not in first and "https://" not in first
        origin = "http://127.0.0.1:%d/" % live_server.port
        assert requests and all(url.startswith(origin) for url in requests), [u for u in requests if not u.startswith(origin)]
    finally:
        context.close()


def test_axe_reports_no_serious_or_critical_violation_in_the_cost_panel(browser, live_server, repo):
    _seed_measured_usage(repo)
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#token-bars progress", timeout=TIMEOUT_MS)
            page.evaluate(AXE_JS.read_text(encoding='utf-8'))  # evaluate, not a script tag: the page CSP forbids inline scripts
            violations = page.evaluate(
                """async () => (await axe.run(document.querySelector('.agents-panel'), { resultTypes: ['violations'] })).violations
                  .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))""")
            blocking = [v for v in violations if v["impact"] in ("serious", "critical")]
            assert blocking == [], (theme, blocking)
        finally:
            context.close()
