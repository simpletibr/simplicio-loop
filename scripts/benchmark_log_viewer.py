#!/usr/bin/env python3
"""Benchmark the Simplicio Live ``sl-log-viewer`` with 100 000 log lines in a real Chromium (issue #1405).

    .venv/bin/python scripts/benchmark_log_viewer.py [--lines 100000] [--json]

Serves ``simplicio_loop/dashboard/static`` over loopback HTTP, loads the component catalog, feeds the viewer
``--lines`` lines and measures, in the browser: time to render the lines, rendered DOM rows, time to jump to the end
(follow), and time to apply a level filter and a text search. Needs the optional e2e extra
(``pip install -e ".[e2e]"``) and a Chromium. Numbers are wall-clock on the machine that runs it.
"""
from __future__ import annotations

import argparse
import functools
import glob
import http.server
import json
import sys
import threading

from simplicio_loop.dashboard import STATIC_DIR

MEASURE = """async (count) => {
  await customElements.whenDefined('sl-log-viewer');
  const lines = [];
  for (let i = 0; i < count; i++) {
    const level = i % 97 === 0 ? 'error' : i % 31 === 0 ? 'warn' : 'info';
    lines.push({ ts: '12:00:' + String(i % 60).padStart(2, '0'), level, source: 'lane-' + (i % 4), text: 'linha ' + i + ' do registro do gate' });
  }
  const viewer = document.createElement('sl-log-viewer');
  viewer.setAttribute('label', 'bench');
  document.body.append(viewer);
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const timed = async (fn) => { const t = performance.now(); fn(); await frame(); return Math.round(performance.now() - t); };
  const root = viewer.shadowRoot;
  const out = { lines: count };
  out.render_ms = await timed(() => { viewer.lines = lines; });
  out.dom_rows = root.querySelectorAll('.line').length;
  const box = root.querySelector('.lines');
  out.scroll_height_px = box.scrollHeight;
  out.follow_ms = await timed(() => { viewer.setAttribute('follow', ''); });
  out.at_end = Math.abs(box.scrollTop + box.clientHeight - box.scrollHeight) < 4;
  viewer.removeAttribute('follow');
  const rowH = box.scrollHeight / count;
  out.scroll_mid_ms = await timed(() => { box.scrollTop = 50000 * rowH; });
  out.mid_row_found = [...root.querySelectorAll('.line .msg')].some((m) => m.textContent.includes('linha 50000 '));
  out.filter_errors_ms = await timed(() => { root.querySelector('button[data-filter=error]').click(); });
  out.filter_rows = root.querySelectorAll('.line').length;
  out.count_label = root.querySelector('.count').textContent;
  root.querySelector('button[data-filter=all]').click();
  await frame();
  const search = root.querySelector('input[type=search]');
  out.search_ms = await timed(() => { search.value = 'linha 99999'; search.dispatchEvent(new Event('input')); });
  out.search_rows = root.querySelectorAll('.line').length;
  out.dom_nodes_total = root.querySelectorAll('*').length;
  return out;
}"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _launch(pw, chromium: str | None):
    if chromium:
        return pw.chromium.launch(executable_path=chromium)
    try:
        return pw.chromium.launch()
    except Exception:  # Playwright's own build is absent: use a pre-installed Chromium if there is one
        for found in sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")):
            return pw.chromium.launch(executable_path=found)
        raise


def run(lines: int, chromium: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(STATIC_DIR)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = _launch(pw, chromium)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/components.html?theme=dark")
            page.wait_for_selector("html[data-ready='1']", timeout=20000)
            result = page.evaluate(MEASURE, lines)
            result["browser"] = browser.version
            browser.close()
            return result
    finally:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lines", type=int, default=100_000, help="how many log lines to feed the viewer")
    parser.add_argument("--chromium", help="path of a Chromium/Chrome binary when Playwright's own build is not installed")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    result = run(args.lines, args.chromium)
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else "\n".join(f"{k}: {v}" for k, v in sorted(result.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
