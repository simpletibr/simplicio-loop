"""End-to-end system test of the Simplicio Live kit in a real browser (issue #1399).

Serves ``simplicio_loop/dashboard/static`` over loopback HTTP (ES modules need http://), drives
the catalog with Playwright and audits it with axe-core in the dark, light and high-contrast
themes. Requires the optional e2e extra:

    pip install -e ".[e2e]" && python -m playwright install chromium   # or a system Chrome

Set ``SL_SCREENSHOT_DIR=<dir>`` to also write the per-component catalog screenshots.
"""
from __future__ import annotations

import functools
import http.server
import os
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="optional e2e extra: pip install -e '.[e2e]'")
axe_pkg = pytest.importorskip("axe_playwright_python", reason="optional e2e extra: pip install -e '.[e2e]'")

from simplicio_loop.dashboard import STATIC_DIR  # noqa: E402

TAGS = (
    "sl-stage-rail", "sl-gate-badge", "sl-lane-swimlane", "sl-timeline", "sl-sparkline", "sl-donut",
    "sl-heatmap", "sl-log-viewer", "sl-json-tree", "sl-diff-view", "sl-kpi-card", "sl-alert-toast",
    "sl-command-palette", "sl-calendar", "sl-connection-dot",
)
THEMES = ("dark", "light", "contrast")
AXE_JS = Path(axe_pkg.__file__).with_name("axe.min.js")

DEEP_ACTIVE = """() => {
  let el = document.activeElement;
  while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
  if (!el) return null;
  const host = el.getRootNode().host;
  return { tag: el.localName, role: el.getAttribute('role'), host: host ? host.localName : null,
           text: (el.getAttribute('aria-label') || el.textContent || '').trim().slice(0, 80),
           date: el.dataset ? el.dataset.date || null : null };
}"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output clean
        pass


@pytest.fixture(scope="module")
def base_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(STATIC_DIR)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        launched = None
        errors = []
        for options in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
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
def open_catalog(browser, base_url):
    pages = []

    def _open(theme="dark", compare=False, reduced_motion="no-preference", width=1600):
        context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion=reduced_motion)
        page = context.new_page()
        page.problems = []
        page.on("console", lambda m: page.problems.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
        query = f"?theme={theme}" + ("&compare=1" if compare else "")
        page.goto(f"{base_url}/components.html{query}")
        page.wait_for_selector("html[data-ready='1']", timeout=20000)
        pages.append(context)
        return page

    yield _open
    for context in pages:
        context.close()


def _axe(page, context="document"):
    page.add_script_tag(path=str(AXE_JS))
    return page.evaluate(
        "async (ctx) => (await axe.run(ctx === 'document' ? document : ctx, {resultTypes: ['violations']})).violations"
        ".map(v => ({id: v.id, impact: v.impact, nodes: v.nodes.length, sample: v.nodes[0] && v.nodes[0].target}))",
        context,
    )


@pytest.mark.parametrize("theme", THEMES)
def test_catalog_renders_every_component_in_the_theme_without_errors(open_catalog, theme):
    page = open_catalog(theme)
    assert page.evaluate("document.documentElement.dataset.slTheme") == theme
    counts = page.evaluate(
        """(tags) => Object.fromEntries(tags.map(t => [t, {
             defined: !!customElements.get(t),
             rendered: [...document.querySelectorAll(t)].filter(e => e.shadowRoot && e.shadowRoot.childNodes.length).length }]))""",
        list(TAGS),
    )
    for tag, info in counts.items():
        assert info["defined"] and info["rendered"] >= 1, (tag, info)
    fonts = page.evaluate("[...document.fonts].filter(f => f.status === 'loaded').map(f => f.family)")
    assert any("Atkinson Hyperlegible Next" in f for f in fonts)
    assert page.problems == []


def test_compare_mode_shows_every_component_in_all_three_themes(open_catalog):
    page = open_catalog("dark", compare=True)
    per_section = page.evaluate(
        """(tags) => tags.map(t => [t, [...document.querySelectorAll(`#${t} .theme`)].map(d => d.dataset.slTheme),
             document.querySelectorAll(`#${t} .theme ${t}`).length])""", list(TAGS))
    for tag, themes, instances in per_section:
        assert themes == list(THEMES), tag
        assert instances >= 3, tag
    # Tokens really resolve differently per theme container.
    bgs = page.evaluate("[...document.querySelectorAll('#sl-gate-badge .theme')].map(d => getComputedStyle(d).backgroundColor)")
    assert len(set(bgs)) == 3
    assert page.problems == []


@pytest.mark.parametrize("theme", THEMES)
def test_axe_core_reports_no_serious_or_critical_violations(open_catalog, theme):
    page = open_catalog(theme)
    violations = _axe(page)
    serious = [v for v in violations if v["impact"] in ("serious", "critical")]
    assert serious == [], serious


@pytest.mark.parametrize("theme", THEMES)
def test_axe_core_with_the_command_palette_open(open_catalog, theme):
    page = open_catalog(theme)
    page.keyboard.press("Control+k")
    page.wait_for_function("document.querySelector('sl-command-palette[hotkey]').isOpen")
    violations = _axe(page)
    assert [v for v in violations if v["impact"] in ("serious", "critical")] == []


def test_axe_core_compare_mode(open_catalog):
    page = open_catalog("dark", compare=True)
    violations = _axe(page)
    assert [v for v in violations if v["impact"] in ("serious", "critical")] == []


def test_tab_order_reaches_every_interactive_component_and_never_traps(open_catalog):
    page = open_catalog("dark")
    seen = []
    for _ in range(400):
        page.keyboard.press("Tab")
        info = page.evaluate(DEEP_ACTIVE)
        if info is None or info["tag"] == "body":
            break
        seen.append(info)
        if len(seen) > 5 and info == seen[0]:
            break
    hosts = {s["host"] for s in seen}
    for tag in ("sl-command-palette", "sl-gate-badge", "sl-lane-swimlane", "sl-heatmap", "sl-log-viewer",
                "sl-json-tree", "sl-diff-view", "sl-alert-toast", "sl-calendar"):
        assert tag in hosts, (tag, hosts)
    roles = {(s["host"], s["role"]) for s in seen}
    assert ("sl-json-tree", "treeitem") in roles and ("sl-heatmap", None) in {(h, r) for h, r in roles if h == "sl-heatmap"}
    assert ("sl-calendar", "gridcell") in roles
    assert seen[0]["text"].startswith("Pular"), seen[0]
    # Roving tabindex: each composite widget is a single tab stop.
    assert sum(1 for s in seen if s["host"] == "sl-calendar" and s["role"] == "gridcell") == 1
    assert sum(1 for s in seen if s["host"] == "sl-json-tree") == 1


def test_command_palette_keyboard_flow_and_focus_restore(open_catalog):
    page = open_catalog("dark")
    page.focus("input[name=compare]")
    page.keyboard.press("Control+k")
    page.wait_for_function("document.querySelector('sl-command-palette[hotkey]').isOpen")
    active = page.evaluate(DEEP_ACTIVE)
    assert active["role"] == "combobox" and active["host"] == "sl-command-palette"
    page.keyboard.press("Escape")
    page.wait_for_function("!document.querySelector('sl-command-palette[hotkey]').isOpen")
    assert page.evaluate("document.activeElement.name") == "compare"
    page.keyboard.press("Control+k")
    page.keyboard.type("calend")
    options = page.evaluate("document.querySelector('sl-command-palette[hotkey]').shadowRoot.querySelectorAll('[role=option]').length")
    assert options == 1
    page.keyboard.press("Enter")
    page.wait_for_function("!document.querySelector('sl-command-palette[hotkey]').isOpen")
    assert page.evaluate("document.activeElement.id") == "sl-calendar-h"
    # The section palette fires sl-command and its result is announced in the output.
    palette = page.locator("#sl-command-palette sl-command-palette")
    palette.evaluate("el => el.shadowRoot.querySelector('.trigger').focus()")
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowUp")
    page.keyboard.press("Enter")
    assert page.locator("#sl-command-palette output").inner_text() == "Executado: Selo de gate"
    page.keyboard.press("Control+k")
    page.keyboard.type("zzzz")
    empty = page.evaluate("document.querySelector('sl-command-palette[hotkey]').shadowRoot.querySelector('.empty').textContent")
    assert "Nenhum comando" in empty
    page.keyboard.press("Escape")
    assert page.problems == []


def test_json_tree_follows_the_aria_tree_keyboard_pattern(open_catalog):
    page = open_catalog("dark")
    tree = page.locator("sl-json-tree").first
    tree.evaluate("el => el.shadowRoot.querySelector('[role=treeitem]').focus()")
    for _ in range(3):
        page.keyboard.press("ArrowDown")
    gates = page.evaluate(DEEP_ACTIVE)
    assert gates["role"] == "treeitem" and gates["text"].startswith("gates")
    expanded = "el => el.shadowRoot.activeElement.getAttribute('aria-expanded')"
    assert tree.evaluate(expanded) == "true"
    page.keyboard.press("ArrowLeft")
    assert tree.evaluate(expanded) == "false"
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    assert page.evaluate(DEEP_ACTIVE)["text"].startswith("evidence")
    assert tree.evaluate("el => el.shadowRoot.activeElement.querySelectorAll('[role=treeitem]').length") == 0  # lazy
    page.keyboard.press("Enter")
    assert tree.evaluate("el => el.shadowRoot.activeElement.querySelectorAll('[role=treeitem]').length") == 2
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")
    assert page.evaluate(DEEP_ACTIVE)["text"].startswith("gates")
    page.keyboard.press("End")
    assert page.evaluate(DEEP_ACTIVE)["text"].startswith("usd")


def test_calendar_date_grid_keyboard(open_catalog):
    page = open_catalog("dark")
    cal = page.locator("#sl-calendar sl-calendar")
    cal.evaluate("el => el.shadowRoot.querySelector('td[tabindex=\"0\"]').focus()")
    assert page.evaluate(DEEP_ACTIVE)["date"] == "2026-10-05"
    events = []
    page.expose_function("recordSelect", lambda d: events.append(d))
    page.evaluate("document.addEventListener('sl-select', e => window.recordSelect(e.detail.date))")
    for key, expected in (("ArrowRight", "2026-10-06"), ("ArrowDown", "2026-10-13"), ("End", "2026-10-17"),
                          ("Home", "2026-10-11"), ("ArrowUp", "2026-10-04"), ("PageDown", "2026-11-04"),
                          ("PageUp", "2026-10-04"), ("ArrowLeft", "2026-10-03"), ("ArrowLeft", "2026-10-02")):
        page.keyboard.press(key)
        assert page.evaluate(DEEP_ACTIVE)["date"] == expected, key
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowUp")  # crosses into September
    assert page.evaluate(DEEP_ACTIVE)["date"] == "2026-09-18"
    assert "Setembro de 2026" in cal.evaluate("el => el.shadowRoot.querySelector('.month').textContent")
    page.keyboard.press("Enter")
    page.wait_for_timeout(50)
    assert cal.get_attribute("selected") == "2026-09-18" and events == ["2026-09-18"]
    label = page.evaluate(DEEP_ACTIVE)["text"]
    assert "18 de setembro de 2026" in label
    cal.evaluate("el => el.shadowRoot.querySelector('.nav[data-step=\"1\"]').focus()")
    page.keyboard.press("Enter")
    assert "Outubro de 2026" in cal.evaluate("el => el.shadowRoot.querySelector('.month').textContent")
    assert page.evaluate(DEEP_ACTIVE)["text"] == "Próximo mês"
    day = cal.evaluate("el => el.shadowRoot.querySelector('td[data-date=\"2026-10-14\"]').getAttribute('aria-label')")
    assert "4 itens" in day and "Artigo no blog (Blog): Parado" in day


def test_heatmap_cells_are_reachable_with_arrows_and_read_aloud(open_catalog):
    page = open_catalog("dark")
    heat = page.locator("sl-heatmap").first
    heat.evaluate("el => el.shadowRoot.querySelector('td[tabindex=\"0\"]').focus()")
    for key in ("ArrowRight", "ArrowRight", "ArrowDown"):
        page.keyboard.press(key)
    assert heat.evaluate("el => el.shadowRoot.querySelector('.readout').textContent") == "watcher, 15h: 3 falhas"
    page.keyboard.press("Control+End")
    assert page.evaluate(DEEP_ACTIVE)["text"] == "DoD, 19h: 2 falhas"
    page.keyboard.press("Home")
    assert page.evaluate(DEEP_ACTIVE)["text"] == "DoD, 13h: 2 falhas"
    assert heat.evaluate("el => el.shadowRoot.querySelector('td[data-r=\"2\"][data-c=\"4\"]').getAttribute('aria-label')") == "oracle, 17h: sem dado"


def test_log_viewer_filters_highlights_and_never_renders_html(open_catalog):
    page = open_catalog("dark")
    page.evaluate("window.__xss = false")
    log = page.locator("sl-log-viewer").first
    text = log.evaluate("el => el.shadowRoot.querySelector('.lines').textContent")
    assert "<img src=x onerror=alert(1)>" in text
    assert log.evaluate("el => el.shadowRoot.querySelectorAll('img').length") == 0
    log.evaluate("el => el.shadowRoot.querySelector('input[type=search]').focus()")
    page.keyboard.type("watcher")
    assert log.evaluate("el => el.shadowRoot.querySelectorAll('.line').length") == 1
    assert log.evaluate("el => el.shadowRoot.querySelector('mark').textContent") == "watcher"
    page.keyboard.press("Control+a")
    page.keyboard.press("Backspace")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    page.keyboard.press("Space")  # "Erros"
    assert log.evaluate("el => [...el.shadowRoot.querySelectorAll('.line')].map(l => l.dataset.level)") == ["error"]
    log.evaluate("el => el.append({ts: '19:06:00', level: 'error', text: 'nova falha <b>x</b>'})")
    assert log.evaluate("el => el.shadowRoot.querySelectorAll('.line').length") == 2
    assert log.evaluate("el => el.shadowRoot.querySelectorAll('b').length") == 0


def test_alert_toasts_dismiss_by_button_and_escape(open_catalog):
    page = open_catalog("dark")
    before = page.locator("#sl-alert-toast sl-alert-toast").count()
    first = page.locator("#sl-alert-toast sl-alert-toast").first
    assert first.get_attribute("role") == "alert"
    first.evaluate("el => el.shadowRoot.querySelector('.close').focus()")
    page.keyboard.press("Enter")
    assert page.locator("#sl-alert-toast sl-alert-toast").count() == before - 1
    nxt = page.locator("#sl-alert-toast sl-alert-toast").first
    nxt.evaluate("el => el.shadowRoot.querySelector('.close').focus()")
    page.keyboard.press("Escape")
    assert page.locator("#sl-alert-toast sl-alert-toast").count() == before - 2
    assert page.locator("#sl-alert-toast sl-alert-toast[persistent]").evaluate("el => el.shadowRoot.querySelector('.close')") is None
    assert page.locator("#sl-alert-toast sl-alert-toast[state=PASS]").get_attribute("role") == "status"
    page.click("[data-notify]")
    toast = page.locator("[data-sl-toasts] sl-alert-toast")
    assert toast.count() == 1 and toast.get_attribute("timeout") == "8000"


def test_stage_rail_is_honest_about_completion(open_catalog):
    page = open_catalog("dark")
    rails = page.locator("#sl-stage-rail sl-stage-rail")
    no_receipt = rails.nth(5)
    assert no_receipt.get_attribute("phase") == "done" and no_receipt.get_attribute("percent") == "100"
    model = no_receipt.evaluate("el => el.model")
    assert model["percent"] == 99 and model["current"] == "UNVERIFIED"
    assert "ready: true" in no_receipt.evaluate("el => el.shadowRoot.querySelector('.note').textContent")
    assert rails.nth(6).evaluate("el => el.model.percent") == 100
    blocked = rails.nth(3).evaluate("el => ({m: el.model, s: el.shadowRoot.querySelector('.siding').textContent})")
    assert blocked["m"]["offRail"] and blocked["m"]["current"] == "BLOCKED" and "Gate de evidência" in blocked["s"]
    current = rails.nth(0).evaluate("el => el.shadowRoot.querySelector('[aria-current=step]').textContent")
    assert "Execução em andamento" in current and "Em execução" in current


def test_reduced_motion_stops_every_pulse(open_catalog):
    calm = open_catalog("dark", reduced_motion="reduce")
    moving = open_catalog("dark")
    probe = "() => document.querySelector('sl-stage-rail').shadowRoot.querySelector('.lamp.live').getAnimations().length"
    assert calm.evaluate(probe) == 0
    assert moving.evaluate(probe) >= 1


def test_untrusted_values_are_escaped_and_links_sanitised(open_catalog):
    page = open_catalog("dark")
    result = page.evaluate("""() => {
      const box = document.createElement('div');
      box.innerHTML = `<sl-gate-badge gate="<b>x</b>" state="FAIL" href="javascript:alert(1)" reason="<img src=x>"></sl-gate-badge>
        <sl-timeline items='[{"title":"<script>window.__x=1</script>","state":"nope"}]'></sl-timeline>
        <sl-json-tree data='{"<i>k</i>":"<img src=x>"}'></sl-json-tree>`;
      document.body.append(box);
      const badge = box.querySelector('sl-gate-badge').shadowRoot;
      return { link: !!badge.querySelector('a'), tags: badge.querySelectorAll('b,img').length,
               state: box.querySelector('sl-timeline').shadowRoot.querySelector('li').dataset.state,
               injected: window.__x === 1,
               tree: box.querySelector('sl-json-tree').shadowRoot.querySelectorAll('i,img').length };
    }""")
    assert result == {"link": False, "tags": 0, "state": "PENDING", "injected": False, "tree": 0}


def test_diff_parser_keeps_sql_comments_and_counts_lines(open_catalog):
    page = open_catalog("dark")
    files = page.evaluate("""async () => {
      const { parseUnifiedDiff } = await import('./components/index.js');
      return parseUnifiedDiff('diff --git a/q.sql b/q.sql\\n--- a/q.sql\\n+++ b/q.sql\\n@@ -1,2 +1,2 @@\\n keep\\n--- old comment\\n+-- new comment\\n');
    }""")
    assert len(files) == 1 and files[0]["name"] == "q.sql"
    assert (files[0]["add"], files[0]["del"]) == (1, 1)
    assert [r["kind"] for r in files[0]["rows"]] == ["hunk", "ctx", "del", "add"]


def test_properties_set_before_upgrade_are_kept(open_catalog):
    page = open_catalog("dark")
    result = page.evaluate("""() => {
      // Elements inside <template> content are not upgraded: properties land on the plain element.
      const t = document.createElement('template');
      t.innerHTML = '<sl-lane-swimlane></sl-lane-swimlane><sl-diff-view></sl-diff-view>';
      const [lanes, diff] = t.content.children;
      lanes.lanes = [{label: 'x', stages: {intake: 'PASS'}}];
      diff.diff = '--- a/f\\n+++ b/f\\n@@ -1 +1 @@\\n-a\\n+b\\n';
      document.body.append(lanes, diff);
      return { rows: lanes.shadowRoot.querySelectorAll('tbody tr').length,
               upgraded: Object.hasOwn(lanes, 'lanes'),
               diffRows: diff.shadowRoot.querySelectorAll('tr.r-add, tr.r-del').length };
    }""")
    assert result == {"rows": 1, "upgraded": False, "diffRows": 2}


def test_narrow_viewport_keeps_the_rail_readable(open_catalog):
    page = open_catalog("light", width=420)
    direction = page.evaluate(
        "() => getComputedStyle(document.querySelector('sl-stage-rail').shadowRoot.querySelector('.track')).gridTemplateColumns.split(' ').length")
    assert direction == 1
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.problems == []


@pytest.mark.skipif(not os.environ.get("SL_SCREENSHOT_DIR"), reason="set SL_SCREENSHOT_DIR to write screenshots")
def test_capture_catalog_screenshots(open_catalog):
    out = Path(os.environ["SL_SCREENSHOT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        page = open_catalog(theme)
        page.locator("#painel").screenshot(path=str(out / f"catalog-hero-{theme}.png"))
    page = open_catalog("dark", compare=True)
    for tag in TAGS:
        page.locator(f"#{tag}").screenshot(path=str(out / f"{tag}.png"))
    page = open_catalog("dark")
    page.keyboard.press("Control+k")
    page.keyboard.type("gate")
    page.screenshot(path=str(out / "sl-command-palette-open.png"))
