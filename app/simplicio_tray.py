#!/usr/bin/env python3
"""Simplicio Token Monitor — cross-platform tray + widget for token savings.

Lives in the system tray / menu bar showing live tokens saved; the dropdown is the
widget (lifetime + session tokens/$ saved, reduction %, requests, proxy status, open
the dashboard). Reads the capture proxy's proxy_savings.json — no traffic of its own.

Backends (auto-selected):
  macOS  → rumps   (native menu-bar text: shows the live number)   pip install rumps
  Win/Linux → pystray (tray icon + menu + tooltip)                 pip install pystray pillow
  fallback → headless print loop (no GUI libs)

Run:  python3 app/simplicio_tray.py
"""
import json
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HOME = os.path.expanduser("~")
REPO = Path(__file__).resolve().parents[1]
ICON = str(REPO / "assets" / "tray-icon.png")
SAVINGS_CANDIDATES = [
    Path(HOME) / ".simplicio-loop" / "proxy_savings.json",
]
PROXY_PORT = int(os.environ.get("SIMPLICIO_PROXY_PORT", "8788"))
MONITOR_PORT = os.environ.get("SIMPLICIO_MONITOR_PORT", "9090")
DASH_URL = f"http://127.0.0.1:{MONITOR_PORT}"


def _read_savings():
    for p in SAVINGS_CANDIDATES:
        if p.exists():
            try:
                return json.loads(p.read_text(errors="replace"))
            except (ValueError, OSError):
                pass
    return {}


def _port_up(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _compact(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _data():
    d = _read_savings()
    life = d.get("lifetime", {}) if isinstance(d, dict) else {}
    sess = d.get("display_session", {}) if isinstance(d, dict) else {}
    saved = int(life.get("tokens_saved", 0) or 0)
    after = int(life.get("total_input_tokens", 0) or 0)
    before = after + saved
    return {
        "saved": saved,
        "usd": float(life.get("compression_savings_usd", 0) or 0),
        "pct": round(saved / before * 100, 1) if before else 0.0,
        "req": int(life.get("requests", 0) or 0),
        "sess": int(sess.get("tokens_saved", 0) or 0),
        "sess_pct": sess.get("savings_percent", 0),
        "up": _port_up(PROXY_PORT),
    }


# ── macOS backend (rumps): native menu-bar text ──────────────────────────────
def run_rumps():
    import rumps

    class TrayApp(rumps.App):
        def __init__(self):
            icon = ICON if os.path.exists(ICON) else None
            super().__init__("—", icon=icon, template=False, quit_button="Quit Simplicio Monitor")
            self.m_saved = rumps.MenuItem("Tokens saved: —")
            self.m_usd = rumps.MenuItem("$ saved: —")
            self.m_pct = rumps.MenuItem("Reduction: —")
            self.m_req = rumps.MenuItem("Requests: —")
            self.m_sess = rumps.MenuItem("This session: —")
            self.m_proxy = rumps.MenuItem("Capture proxy: —")
            self.menu = [
                self.m_saved, self.m_usd, self.m_pct, self.m_req, None,
                self.m_sess, self.m_proxy, None,
                rumps.MenuItem("Open Token Monitor…", callback=lambda _: webbrowser.open(DASH_URL)),
                rumps.MenuItem("Refresh now", callback=lambda _: self.update()),
            ]
            self._timer = rumps.Timer(lambda _: self.update(), 4)
            self._timer.start()
            self.update()

        def update(self):
            m = _data()
            self.title = f" {_compact(m['saved'])}" if m["up"] else f" {_compact(m['saved'])} ○"
            self.m_saved.title = f"Tokens saved: {m['saved']:,}"
            self.m_usd.title = f"$ saved: ${m['usd']:.3f}"
            self.m_pct.title = f"Reduction: {m['pct']}%"
            self.m_req.title = f"Requests: {m['req']:,}"
            self.m_sess.title = f"This session: {m['sess']:,} ({m['sess_pct']}%)"
            self.m_proxy.title = f"Capture proxy: {'● live :' + str(PROXY_PORT) if m['up'] else '○ offline'}"

    TrayApp().run()


# ── Windows/Linux backend (pystray): tray icon + menu + tooltip ──────────────
def run_pystray():
    import pystray
    from PIL import Image

    img = Image.open(ICON) if os.path.exists(ICON) else Image.new("RGBA", (64, 64), (157, 255, 26, 255))

    def label(fn):
        return pystray.MenuItem(fn, None, enabled=False)

    menu = pystray.Menu(
        label(lambda i: f"Tokens saved: {_data()['saved']:,}"),
        label(lambda i: f"$ saved: ${_data()['usd']:.3f}"),
        label(lambda i: f"Reduction: {_data()['pct']}%"),
        label(lambda i: f"Requests: {_data()['req']:,}"),
        pystray.Menu.SEPARATOR,
        label(lambda i: f"Capture proxy: {'live :' + str(PROXY_PORT) if _data()['up'] else 'offline'}"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Token Monitor", lambda i: webbrowser.open(DASH_URL)),
        pystray.MenuItem("Quit", lambda i: i.stop()),
    )
    icon = pystray.Icon("simplicio_token_monitor", img, "Simplicio Token Monitor", menu)

    def loop():
        while True:
            try:
                m = _data()
                icon.title = f"Simplicio · {_compact(m['saved'])} saved · {m['pct']}%"
                icon.update_menu()
            except Exception:
                pass
            time.sleep(4)

    threading.Thread(target=loop, daemon=True).start()
    icon.run()


# ── headless fallback (no GUI libs) ──────────────────────────────────────────
def run_headless():
    while True:
        m = _data()
        print(f"Simplicio Token Monitor: {m['saved']:,} tokens saved ({m['pct']}%) · "
              f"proxy {'live' if m['up'] else 'offline'}", flush=True)
        time.sleep(15)


def main():
    # SIMPLICIO_TRAY_BACKEND=rumps|pystray|headless forces a backend (default: auto by OS).
    backend = os.environ.get("SIMPLICIO_TRAY_BACKEND", "").lower()
    if backend == "headless":
        return run_headless()
    if backend == "pystray":
        try:
            import pystray  # noqa: F401
            return run_pystray()
        except ImportError:
            return run_headless()
    if backend == "rumps" or sys.platform == "darwin":
        try:
            import rumps  # noqa: F401
            return run_rumps()
        except ImportError:
            pass
    try:
        import pystray  # noqa: F401
        return run_pystray()
    except ImportError:
        return run_headless()


if __name__ == "__main__":
    main()
