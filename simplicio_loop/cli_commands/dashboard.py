"""`dashboard`: the Simplicio Live panel and the Token Monitor.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser

from ._base import impl

def _pid_file() -> Path:
    """Cross-platform temp dir (Windows has no /tmp) — must match hooks/simplicio_dashboard.py. Read at call time."""
    return Path(tempfile.gettempdir()) / "simplicio-token-monitor.pid"


def _gui_available() -> bool:
    """True only when opening a browser is safe + non-blocking. On headless Linux (no DISPLAY),
    webbrowser.open() may launch a text browser that inherits stdin and blocks forever — and a
    blocking wait() is NOT caught by try/except — so we must skip it there."""
    if sys.platform == "darwin" or impl().os.name == "nt":
        return True
    return bool(impl().os.environ.get("DISPLAY") or impl().os.environ.get("WAYLAND_DISPLAY"))


def _port_up(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), 0.5):
            return True
    except OSError:
        return False


def _stop_dashboard() -> int:
    """Best-effort stop: kill the PID the dashboard recorded, then any stray server."""
    killed = False
    try:
        pid = int(impl()._pid_file().read_text().strip())
        impl().os.kill(pid, 15)
        killed = True
    except (OSError, ValueError):
        pass
    if impl().os.name != "nt":  # pkill catches a server started outside this CLI
        try:
            subprocess.run(["pkill", "-f", "simplicio_dashboard.py"], check=False)
            killed = True
        except OSError:
            pass
    try:
        impl()._pid_file().unlink()
    except OSError:
        pass
    print("⬡ Token Monitor stopped." if killed else "⬡ dashboard was not running.")
    return 0


def dashboard(port: int, open_browser: bool, stop: bool) -> int:
    """Open (or stop) the Simplicio Token Monitor dashboard — works from anywhere after a pip
    install, no repo checkout needed. Starts the bundled server detached if it's not already up,
    then opens the browser. The dashboard is on-demand: nothing keeps it open, close it freely."""
    if stop:
        return impl()._stop_dashboard()
    url = f"http://127.0.0.1:{port}"
    if not impl().DASHBOARD.is_file():
        print("error: bundled dashboard not found in the installed package.", flush=True)
        return 1
    if not _port_up(port):
        logdir = Path.home() / ".simplicio-loop" / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        env = {**impl().os.environ, "PORT": str(port)}
        # Detach so the server outlives this CLI process (own session / no console window).
        kw = {"start_new_session": True} if impl().os.name != "nt" else {
            "creationflags": 0x00000008 | 0x00000200}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        with open(logdir / "token-monitor.log", "ab") as logf:
            try:
                subprocess.Popen([sys.executable or "python3", str(impl().DASHBOARD)],
                                 env=env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, **kw)
            except OSError as e:
                print(f"error: could not start the dashboard ({e}).", flush=True)
                return 1
        for _ in range(25):  # wait up to ~5s for the port to come up
            if _port_up(port):
                break
            time.sleep(0.2)
    if not _port_up(port):
        print("⬡ failed to start the dashboard — see ~/.simplicio-loop/logs/token-monitor.log", flush=True)
        return 1
    print(f"⬡ Simplicio Token Monitor → {url}")
    if open_browser and _gui_available():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    print("   stop it any time:  simplicio-loop dashboard --stop")
    return 0


def add_dashboard(sub, argv_list):
    p_dashboard = sub.add_parser("dashboard", help="open the Simplicio Live panel; --tokens opens the Token Monitor")
    if "dashboard" in argv_list:  # its flags are only read for this command; importing them costs ~170 ms for every other one
        from ..dashboard import cli as dashboard_cli
        dashboard_cli.add_arguments(p_dashboard)
