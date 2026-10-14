"""End-to-end: the "a partir de" floor shows on the extras run cost and on the cost widgets of a real page (issue #1550).

A haiku-5-5 event of 150000 input tokens with no ``requests`` is a floor; with ``requests`` 1 it is exact. The mixed run
(T1 with requests, T2 aggregated) must read the same total in both panels. Requires the optional e2e extra.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")

from simplicio_loop.dashboard import server  # noqa: E402
from simplicio_loop.dashboard_events import load  # noqa: E402

TOKEN = "floor-e2e-token-0123"
RUN_ID = "run-floor"
TIMEOUT_MS = 15000
MODEL = "claude-haiku-5-5"
EXTRAS_COST_JS = """() => { const dt = [...document.querySelectorAll('#live-extras dt')].find((n) => n.textContent.includes('Custo do run'));
  return dt ? dt.parentElement.textContent : ''; }"""


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        launched = None
        candidates = ({"executable_path": os.environ["SL_CHROMIUM_PATH"]},) if os.environ.get("SL_CHROMIUM_PATH") else ()
        for options in candidates + ({}, {"channel": "chrome"}):
            try:
                launched = pw.chromium.launch(**options)
                break
            except Exception:
                continue
        if launched is None:
            pytest.skip("no Chromium/Chrome available")
        yield launched
        launched.close()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    run_dir = root / ".simplicio-loop" / "loop-runs" / RUN_ID
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


def _emit(repo, task, tokens_in, tokens_out, iteration, requests=None):
    payload = {"input_tokens": tokens_in, "output_tokens": tokens_out, "model": MODEL}
    if requests is not None:
        payload["requests"] = requests
    run_dir = repo / ".simplicio-loop" / "loop-runs" / RUN_ID
    load().emit(run_dir, "token_usage", source="runner", strict=True, task_id=task, phase="executing", lane="route-a",
                iteration=iteration, payload=payload)


def _screens(browser, port):
    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    page.goto("http://127.0.0.1:%d/?t=%s&theme=dark&run=%s" % (port, TOKEN, RUN_ID))
    page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
    page.wait_for_function("(js) => /US\\$/.test(eval('(' + js + ')')())", arg=EXTRAS_COST_JS, timeout=TIMEOUT_MS)
    page.wait_for_selector("#task-cost sl-gate-badge", timeout=TIMEOUT_MS)
    return context, page


def _tasks(page):
    return {b.get_attribute("gate"): b.get_attribute("reason") for b in page.query_selector_all("#task-cost sl-gate-badge")}


def test_an_aggregated_event_above_the_tier_reads_a_partir_de_in_the_extras_header_and_the_widget(browser, live_server, repo):
    _emit(repo, "T1", 150_000, 2_000, 1)
    context, page = _screens(browser, live_server.port)
    try:
        header = page.evaluate(EXTRAS_COST_JS)
        assert "a partir de US$ 0.0160" in header and "estimado" not in header
        assert "a partir de USD 0.0160" in _tasks(page)["Tarefa T1"]
    finally:
        context.close()


def test_requests_1_reads_exact_in_both_panels(browser, live_server, repo):
    _emit(repo, "T1", 150_000, 2_000, 1, requests=1)
    context, page = _screens(browser, live_server.port)
    try:
        header = page.evaluate(EXTRAS_COST_JS)
        assert "US$ 0.0800 estimado" in header and "a partir de" not in header
        reason = _tasks(page)["Tarefa T1"]
        assert "USD 0.0800 estimado" in reason and "a partir de" not in reason
    finally:
        context.close()


def test_a_mixed_run_shows_the_same_total_in_the_extras_and_the_budget_widget(browser, live_server, repo):
    _emit(repo, "T1", 150_000, 2_000, 1, requests=1)
    _emit(repo, "T2", 150_000, 2_000, 2)
    context, page = _screens(browser, live_server.port)
    try:
        assert "a partir de US$ 0.0960" in page.evaluate(EXTRAS_COST_JS)
        tasks = _tasks(page)
        assert "USD 0.0800 estimado" in tasks["Tarefa T1"] and "a partir de USD 0.0160" in tasks["Tarefa T2"]
    finally:
        context.close()
