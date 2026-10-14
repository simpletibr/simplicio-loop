#!/usr/bin/env python3
"""Benchmark the Simplicio Live ``sl-diff-view`` with a 50 000-line unified diff in a real Chromium.

    .venv/bin/python scripts/benchmark_diff_view.py [--lines 50000] [--files 100] [--json]

Serves ``simplicio_loop/dashboard/static`` over loopback HTTP, loads the component catalog, feeds the viewer a
synthetic diff of ``--lines`` lines spread over ``--files`` files and measures, in the browser: time to render
the diff, rendered DOM rows, total DOM nodes, and time to jump to the middle file (scrolling the virtual list).
Above 1000 diff rows the viewer windows its rows (see ``VIRTUAL_ROWS`` in ``sl-diff-view.js``). Needs the optional
e2e extra (``pip install -e ".[e2e]"``) and a Chromium. Numbers are wall-clock on the machine that runs it.
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

ROW_HEIGHT = 22  # must match ROW_HEIGHT in sl-diff-view.js
BODY_PATTERNS = (
    " ",
    "-",
    "+",
    " ",
    "+",
)  # context, delete, add, context, add: a realistic mix

MEASURE = """async ({ diff, mid, target }) => {
  await customElements.whenDefined('sl-diff-view');
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const timed = async (fn) => { const t = performance.now(); fn(); await frame(); return Math.round(performance.now() - t); };
  const viewer = document.createElement('sl-diff-view');
  viewer.setAttribute('label', 'bench');
  document.body.append(viewer);
  await frame();
  const root = viewer.shadowRoot;
  const out = {};
  out.render_ms = await timed(() => { viewer.diff = diff; });
  const box = root.querySelector('.vbox');
  out.virtual = box !== null;
  out.table_rows = root.querySelectorAll('tr').length;
  out.dom_rows = root.querySelectorAll('.vrow').length;
  if (box) {
    out.scroll_height_px = box.scrollHeight;
    out.spacer_bottom_px = parseFloat(root.querySelector('.spacer.bot').style.blockSize) || 0;
    out.scroll_mid_ms = await timed(() => { box.scrollTop = target * 22; });
    out.summary = root.querySelector('.vsum').textContent;
  } else {
    out.dom_rows = root.querySelectorAll('tr.r-add, tr.r-del, tr.r-ctx').length;
    out.scroll_mid_ms = 0;
  }
  out.mid_row_found = [...root.querySelectorAll('.vcode, td.code')].some((c) => c.textContent.includes('f' + String(mid).padStart(3, '0') + ' ln '));
  out.dom_nodes_total = root.querySelectorAll('*').length;
  return out;
}"""


def build_diff(lines: int, files: int) -> str:
    """Synthetic unified diff with exactly ``lines`` lines over ``files`` files (the last file takes the rest)."""
    if files < 1 or lines < files * 4:
        raise ValueError("need at least 4 lines per file")
    per_file = lines // files
    out: list[str] = []
    for f in range(files):
        count = per_file + (lines - per_file * files if f == files - 1 else 0)
        name = f"src/mod_{f:03d}.py"
        out += [
            f"diff --git a/{name} b/{name}",
            f"--- a/{name}",
            f"+++ b/{name}",
            f"@@ -1,{count} +1,{count} @@",
        ]
        for j in range(count - 4):
            sign = BODY_PATTERNS[j % len(BODY_PATTERNS)]
            out.append(f"{sign}f{f:03d} ln {j}")
    return "\n".join(out) + "\n"


def mid_target(lines: int, files: int) -> tuple[int, int]:
    """(file index, virtual item index of a row inside the middle file) for the jump-to-middle measurement."""
    per_file = lines // files
    items_per_file = per_file - 2  # one file head + (per_file - 3) rows; hunk included
    mid = files // 2
    return mid, mid * items_per_file + 200


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _launch(pw, chromium: str | None):
    if chromium:
        return pw.chromium.launch(executable_path=chromium)
    try:
        return pw.chromium.launch()
    except (
        Exception
    ):  # Playwright's own build is absent: use a pre-installed Chromium if there is one
        for found in sorted(
            glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
        ):
            return pw.chromium.launch(executable_path=found)
        raise


def run(lines: int = 50_000, files: int = 100, chromium: str | None = None) -> dict:
    from playwright.sync_api import sync_playwright

    diff = build_diff(lines, files)
    mid, target = mid_target(lines, files)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Quiet, directory=str(STATIC_DIR))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = _launch(pw, chromium)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(
                f"http://127.0.0.1:{server.server_address[1]}/components.html?theme=dark"
            )
            page.wait_for_selector("html[data-ready='1']", timeout=20000)
            result = page.evaluate(
                MEASURE, {"diff": diff, "mid": mid, "target": target}
            )
            result.update(
                {
                    "lines": lines,
                    "files": files,
                    "diff_bytes": len(diff),
                    "browser": browser.version,
                }
            )
            browser.close()
            return result
    finally:
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lines",
        type=int,
        default=50_000,
        help="how many diff lines to feed the viewer",
    )
    parser.add_argument(
        "--files", type=int, default=100, help="how many files the diff spans"
    )
    parser.add_argument(
        "--chromium",
        help="path of a Chromium/Chrome binary when Playwright's own build is not installed",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    result = run(args.lines, args.files, args.chromium)
    print(
        json.dumps(result, indent=2, sort_keys=True)
        if args.json
        else "\n".join(f"{k}: {v}" for k, v in sorted(result.items()))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
