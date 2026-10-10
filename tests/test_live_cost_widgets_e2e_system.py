"""End-to-end checks of the Simplicio Live cost widgets and the agent map in a real browser (issues #1404 and #1550).

The dashboard server runs over loopback on a temporary repo. The token_usage events go through the real dashboard_events
emitter before the page opens (the budget is read on load; it is polled every 30 s, the worker signals every 3 s). Checks: the
origin of the tokens and the USD, the cost per task and per iteration, a real provider receipt attributed to its task and
iteration, the sparkline fed by the server series (it survives a reload), the agent map read from a real Mapper operations
store (instances, slots, leases, heartbeat), the UNVERIFIED states with their reasons, dark and light themes, a phone-width page
with no horizontal scroll, an offline DOM snapshot that requests nothing but loopback, and axe. Requires the optional e2e extra:

    pip install -e ".[e2e]" && python -m playwright install chromium   # or a system Chrome

Set ``SL_SCREENSHOT_DIR=<dir>`` to also write the dark, light and phone PNGs of the agents panel.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")
axe_pkg = pytest.importorskip("axe_playwright_python", reason="optional e2e extra: pip install -e '.[e2e]'")

from simplicio_loop.agent_slots import AgentSlotRegistry  # noqa: E402
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
ROWS_INSIDE_JS = """() => [...document.querySelectorAll('.cost-block li, .cost-block sl-gate-badge, .cost-block .bar-label')]
  .every((el) => el.getBoundingClientRect().right <= window.innerWidth + 0.5)"""
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


def _emit_usage(run_dir, task_id, phase, lane, tokens_in, tokens_out, iteration=None, model=MODEL):
    emitter = load()
    assert emitter is not None, "dashboard_events emitter is missing"
    payload = {"input_tokens": tokens_in, "output_tokens": tokens_out, "model": model}
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


def test_origin_rows_and_cost_per_task_and_iteration_show_in_dark_and_light(browser, live_server, repo):
    _seed_measured_usage(repo)
    expected_t1 = 1_000_000 * RATES["input_per_mtok"] / 1_000_000
    expected_t2 = 500_000 * RATES["output_per_mtok"] / 1_000_000
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
            # No receipt of the provider: the tokens come from other producers, and the USD is the price table's estimate.
            origin = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#token-source")}
            assert origin["Tokens do provedor"]["state"] == "UNVERIFIED"
            assert "nenhum token reportado pelo provedor: 1.500.000 tokens" in origin["Tokens do provedor"]["reason"]
            assert origin["USD do run"]["state"] == "ESTIMADO" and "tabela de preços de" in origin["USD do run"]["reason"]
            assert "1.500.000 tokens em 2 eventos" in page.inner_text("#token-source-note")
            assert page.locator("#token-bars, #cost-widgets progress").count() == 0
            tasks = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#task-cost")}
            assert tasks["Tarefa T1"]["state"] == "ESTIMADO"
            assert "1.000.000 tokens" in tasks["Tarefa T1"]["reason"] and "a partir de USD %.4f" % expected_t1 in tasks["Tarefa T1"]["reason"]
            assert tasks["Tarefa T2"]["state"] == "ESTIMADO"
            assert "500.000 tokens" in tasks["Tarefa T2"]["reason"] and "USD %.4f estimado" % expected_t2 in tasks["Tarefa T2"]["reason"]
            iterations = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#iteration-cost")}
            assert iterations["Iteração 1"]["state"] == "ESTIMADO"
            assert iterations["Sem iteração identificada"]["state"] == "ESTIMADO"
            assert page.inner_text("#task-cost-note").startswith("USD estimado")
            # The same budget reply still feeds the reducer: the agents list shows the measured tokens by phase.
            agents = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#agents-cost")}
            assert agents["Tokens por fase"]["state"] == "PASS" and "executing 1000000" in agents["Tokens por fase"]["reason"]
            # The stacked bars by phase, lane and model are the worker signals panel's, drawn once.
            page.wait_for_function("() => document.querySelectorAll('#live-extras .extras-bar').length >= 3")
            assert page.locator("#live-extras .extras-bar").count() == 3
            _shot(page, "cost-" + theme)
            assert page.problems == []
        finally:
            context.close()


def test_unmeasured_run_has_no_origin_row_and_says_why(browser, live_server):
    context, page = _open(browser, live_server.port, theme="dark")
    try:
        page.wait_for_function("() => document.querySelector('#token-source-note').textContent.includes('token_usage')")
        assert page.evaluate(BADGES_JS, "#token-source") == []
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
        page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
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
        page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
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
            page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
            page.evaluate(AXE_JS.read_text(encoding='utf-8'))  # evaluate, not a script tag: the page CSP forbids inline scripts
            violations = page.evaluate(
                """async () => (await axe.run(document.querySelector('.agents-panel'), { resultTypes: ['violations'] })).violations
                  .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))""")
            blocking = [v for v in violations if v["impact"] in ("serious", "critical")]
            assert blocking == [], (theme, blocking)
        finally:
            context.close()


XSS_TASK = '<img src=x onerror="window.__xss=1">'
XSS_MODEL = "<script>window.__xss=2</script>"
LONG_TASK = "T" + "x" * 179


def test_task_and_model_names_from_events_never_become_markup(browser, live_server, repo):
    run_dir = _run_dir(repo)
    _emit_usage(run_dir, XSS_TASK, "executing", "route-a", 1_000, 10, iteration=1, model=XSS_MODEL)
    _emit_usage(run_dir, "__proto__", "validating", "route-b", 2_000, 20, iteration=2, model=MODEL)
    _emit_usage(run_dir, "constructor", "validating", "route-b", 3_000, 30, iteration=3, model=MODEL)
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
            page.wait_for_function("() => document.querySelectorAll('#task-cost sl-gate-badge').length >= 3")
            assert page.evaluate("() => window.__xss") is None
            assert page.locator("img[src=x]").count() == 0
            assert page.locator("#cost-widgets script, #cost-widgets img").count() == 0
            tasks = [row["gate"] for row in page.evaluate(BADGES_JS, "#task-cost")]
            assert "Tarefa " + XSS_TASK in tasks and "Tarefa __proto__" in tasks and "Tarefa constructor" in tasks
            page.wait_for_function("() => document.querySelector('#live-extras').innerText.includes('Tokens por modelo')")
            assert XSS_MODEL in page.inner_text("#live-extras") and page.locator("#live-extras script").count() == 0
            assert page.problems == []
        finally:
            context.close()


def test_a_180_character_task_id_wraps_inside_the_cost_widgets_at_phone_width(browser, live_server, repo):
    run_dir = _run_dir(repo)
    _emit_usage(run_dir, LONG_TASK, "executing", "route-a", 1_000_000, 0, iteration=1)
    context, page = _open(browser, live_server.port, theme="dark", viewport=PHONE)
    try:
        page.wait_for_function("() => document.querySelectorAll('#task-cost sl-gate-badge').length >= 1")
        assert page.evaluate(PANEL_INSIDE_JS) is True
        assert page.evaluate(ROWS_INSIDE_JS) is True
        assert page.problems == []
    finally:
        context.close()


def test_a_floor_cost_shows_a_partir_de_and_the_reason_on_screen(browser, live_server, repo):
    run_dir = _run_dir(repo)
    _emit_usage(run_dir, "T1", "executing", "route-a", 150_000, 2_000, iteration=1)
    context, page = _open(browser, live_server.port)
    try:
        page.wait_for_selector("#task-cost sl-gate-badge", timeout=TIMEOUT_MS)
        tasks = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#task-cost")}
        assert "a partir de USD 0.0160" in tasks["Tarefa T1"]["reason"]
        assert "sem dado por requisição" in page.inner_text("#task-cost-note")
        assert "sem dado por requisição" in page.inner_text("#iteration-cost-note")
        assert page.problems == []
    finally:
        context.close()


# --- issue #1550: provider receipt, server sparkline and the measured agent map ---------------------------------------------
AGENT_BADGES_JS = """() => [...document.querySelectorAll('#agent-map-list sl-gate-badge')]
  .map((b) => ({ gate: b.getAttribute('gate'), state: b.getAttribute('state'), reason: b.getAttribute('reason') }))"""
SPARK_JS = "() => { const s = document.querySelector('#live-extras sl-sparkline'); return s ? s.getAttribute('values') : null; }"
AGENT_INSIDE_JS = """() => [...document.querySelectorAll('#agent-map, #agent-map li, #agent-map sl-gate-badge')]
  .every((el) => el.getBoundingClientRect().right <= window.innerWidth + 0.5)"""


def _write_provider_run(repo, *, tokens_in=1000, tokens_out=200, cost=None, calls=1, attempt=2):
    run_dir = _run_dir(repo)
    (run_dir / "execution-route-1.json").write_text(json.dumps(
        {"task_index": 1, "task_id": "T-7", "route": "provider-lane", "token_usage": {"input_tokens": None, "output_tokens": None}}), encoding="utf-8")
    receipt = {"schema": "simplicio.provider-worker-receipt/v1", "status": "READY", "provider": "openrouter", "model": MODEL,
               "task_index": 1, "attempt": attempt, "provider_call_count": calls, "usage_status": "measured",
               "input_tokens": tokens_in, "output_tokens": tokens_out, "cost": cost}
    name = "provider-worker-1-attempt-%d.json" % attempt
    (run_dir / name).write_text(json.dumps(receipt), encoding="utf-8")
    assert len(load().emit_token_usage(run_dir, only=name)) == 1


def test_a_provider_receipt_shows_its_tokens_task_iteration_and_the_reported_cost_as_medido(browser, live_server, repo):
    _write_provider_run(repo, cost=0.0042)
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#token-source sl-gate-badge", timeout=TIMEOUT_MS)
            origin = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#token-source")}
            assert origin["Tokens do provedor"]["state"] == "PASS"
            assert origin["Tokens do provedor"]["reason"] == "1.200 tokens de 1.200 tokens (100%) reportados pelo provedor"
            assert origin["USD do run"]["state"] == "PASS"
            assert origin["USD do run"]["reason"] == "USD 0.0042 medido (reportado pelo provedor)"
            tasks = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#task-cost")}
            assert list(tasks) == ["Tarefa T-7"] and tasks["Tarefa T-7"]["state"] == "PASS"
            assert tasks["Tarefa T-7"]["reason"] == "1.200 tokens medidos · USD 0.0042 medido (reportado pelo provedor)"
            iterations = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#iteration-cost")}
            assert list(iterations) == ["Iteração 2"] and iterations["Iteração 2"]["state"] == "PASS"
            assert page.inner_text("#task-cost-note") == "USD reportado pelo provedor; tokens medidos."
            assert page.problems == []
        finally:
            context.close()


def test_one_provider_call_above_the_price_tier_is_an_exact_estimate_and_not_a_floor_on_screen(browser, live_server, repo):
    _write_provider_run(repo, tokens_in=150_000, tokens_out=2_000)
    context, page = _open(browser, live_server.port)
    try:
        page.wait_for_selector("#task-cost sl-gate-badge", timeout=TIMEOUT_MS)
        tasks = {row["gate"]: row for row in page.evaluate(BADGES_JS, "#task-cost")}
        assert tasks["Tarefa T-7"]["state"] == "ESTIMADO" and "USD 0.0800 estimado" in tasks["Tarefa T-7"]["reason"]
        assert "a partir de" not in tasks["Tarefa T-7"]["reason"] and "requisição" not in page.inner_text("#task-cost-note")
        assert page.problems == []
    finally:
        context.close()


def test_the_sparkline_is_the_server_series_and_a_reload_draws_the_same_one(browser, live_server, repo):
    run_dir = _run_dir(repo)
    for tokens_in, tokens_out in ((100, 20), (30, 0), (0, 50)):
        _emit_usage(run_dir, "T1", "executing", "route-a", tokens_in, tokens_out)
    context, page = _open(browser, live_server.port)
    try:
        page.wait_for_function("() => document.querySelector('#live-extras sl-sparkline')")
        assert page.evaluate(SPARK_JS) == "120,150,200"
        assert "últimos 3 pontos, atual 200" in page.inner_text("#live-extras")
        page.reload()
        page.wait_for_selector('html[data-ready="1"]', timeout=TIMEOUT_MS)
        page.wait_for_function("() => document.querySelector('#live-extras sl-sparkline')")
        assert page.evaluate(SPARK_JS) == "120,150,200"
        _emit_usage(run_dir, "T1", "executing", "route-a", 0, 100)
        page.wait_for_function("() => document.querySelector('#live-extras sl-sparkline').getAttribute('values') === '120,150,200,300'", timeout=8000)
        assert page.problems == []
    finally:
        context.close()


def _seed_agent_store(repo, now=None):
    database = repo / ".simplicio-loop" / "data" / "operations.sqlite"
    database.parent.mkdir(parents=True, exist_ok=True)
    registry = AgentSlotRegistry(database, capacity=3)
    registry.initialize()
    registry.acquire("agent-live", worktree="/w/live", lease_id="lease-live")
    registry.start("agent-live")
    registry.acquire("agent-quiet")
    stamp = "2026-10-10T00:00:00Z"
    now = time.time() if now is None else now
    con = sqlite3.connect(database)
    try:
        con.execute("INSERT INTO ops_tasks VALUES ('t1', 'k1', '{}', 'running', 0, 0, 0, ?, ?)", (stamp, stamp))
        con.execute("INSERT INTO ops_attempts VALUES ('at1', 't1', 'w', 'f', 'running', ?, ?)", (stamp, stamp))
        con.execute("INSERT INTO ops_leases VALUES ('lease-live', 'at1', 'w', 'f', 's', 'active', ?, ?)", (now - 5, now + 600))
        con.commit()
    finally:
        con.close()


def test_the_agent_map_shows_instances_slots_leases_and_heartbeat_in_dark_light_and_phone(browser, live_server, repo):
    _seed_agent_store(repo)
    for theme, viewport in (("dark", DESKTOP), ("light", DESKTOP), ("dark", PHONE)):
        context, page = _open(browser, live_server.port, theme=theme, viewport=viewport)
        try:
            page.wait_for_selector("#agent-map-list sl-gate-badge", timeout=TIMEOUT_MS)
            rows = {row["gate"]: row for row in page.evaluate(AGENT_BADGES_JS)}
            assert rows["Instâncias"]["state"] == "PASS" and rows["Instâncias"]["reason"].startswith("2 instâncias medidas")
            assert rows["Slots"]["state"] == "PASS" and rows["Slots"]["reason"] == "2 de 3 slots em uso, 1 livres"
            live = rows["agent-live"]
            assert live["state"] == "RUNNING"
            assert live["reason"].startswith("em execução · tentativa 1 · worktree /w/live · lease lease-live · último batimento há ")
            assert rows["agent-quiet"]["state"] == "PENDING" and "sem lease" in rows["agent-quiet"]["reason"]
            assert page.eval_on_selector("#agent-map-bar > span", "el => el.style.width") == "66.67%"
            assert page.evaluate(OVERFLOW_JS) is True and page.evaluate(AGENT_INSIDE_JS) is True
            assert page.locator("#agent-map").evaluate("el => el.previousElementSibling.id") == "live-extras"
            _shot_map(page, "agents-%s-%d" % (theme, viewport[0]))
            assert page.problems == []
        finally:
            context.close()


def test_a_run_without_an_operations_store_labels_the_agent_map_unverified_with_the_reason(browser, live_server):
    context, page = _open(browser, live_server.port)
    try:
        page.wait_for_selector("#agent-map-list sl-gate-badge", timeout=TIMEOUT_MS)
        rows = {row["gate"]: row for row in page.evaluate(AGENT_BADGES_JS)}
        assert set(rows) == {"Instâncias", "Slots"}
        assert rows["Instâncias"] == {"gate": "Instâncias", "state": "UNVERIFIED", "reason": "operations.sqlite ausente"}
        assert rows["Slots"]["state"] == "UNVERIFIED" and rows["Slots"]["reason"] == "slots não medidos: operations.sqlite ausente"
        assert page.locator("#agent-map-bar").evaluate("el => el.hidden") is True
        assert page.problems == []
    finally:
        context.close()


def test_a_hostile_agent_id_stays_text_and_a_stale_beat_is_flagged(browser, live_server, repo):
    hostile = '<img src=x onerror="window.__xss=3">'
    database = repo / ".simplicio-loop" / "data" / "operations.sqlite"
    database.parent.mkdir(parents=True)
    registry = AgentSlotRegistry(database, capacity=2)
    registry.initialize()
    registry.acquire(hostile, lease_id="lease-old")
    registry.start(hostile)
    stamp = "2026-10-10T00:00:00Z"
    con = sqlite3.connect(database)
    con.execute("INSERT INTO ops_tasks VALUES ('t1', 'k1', '{}', 'running', 0, 0, 0, ?, ?)", (stamp, stamp))
    con.execute("INSERT INTO ops_attempts VALUES ('at1', 't1', 'w', 'f', 'running', ?, ?)", (stamp, stamp))
    con.execute("INSERT INTO ops_leases VALUES ('lease-old', 'at1', 'w', 'f', 's', 'expired', ?, ?)", (time.time() - 900, time.time() - 1))
    con.commit()
    con.close()
    context, page = _open(browser, live_server.port)
    try:
        page.wait_for_function("() => document.querySelectorAll('#agent-map-list sl-gate-badge').length >= 3")
        assert page.evaluate("() => window.__xss") is None and page.locator("#agent-map img").count() == 0
        rows = {row["gate"]: row for row in page.evaluate(AGENT_BADGES_JS)}
        assert rows[hostile]["state"] == "STALLED" and "batimento obsoleto, último há " in rows[hostile]["reason"]
        assert page.problems == []
    finally:
        context.close()


def test_axe_reports_no_serious_or_critical_violation_in_the_agent_map(browser, live_server, repo):
    _seed_agent_store(repo)
    for theme in ("dark", "light"):
        context, page = _open(browser, live_server.port, theme=theme)
        try:
            page.wait_for_selector("#agent-map-list sl-gate-badge", timeout=TIMEOUT_MS)
            page.evaluate(AXE_JS.read_text(encoding='utf-8'))
            violations = page.evaluate(
                """async () => (await axe.run(document.querySelector('#agent-map'), { resultTypes: ['violations'] })).violations
                  .map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length }))""")
            blocking = [v for v in violations if v["impact"] in ("serious", "critical")]
            assert blocking == [], (theme, blocking)
        finally:
            context.close()


def _shot_map(page, name):
    target = os.environ.get("SL_SCREENSHOT_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        page.locator("#agent-map").screenshot(path=str(Path(target) / (name + ".png")))
