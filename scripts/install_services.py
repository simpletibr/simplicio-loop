#!/usr/bin/env python3
"""Cross-platform installer for the Simplicio token-economy services.

Registers the three always-on, auto-start services on whichever OS you run it:
  - capture proxy        (intercepts LLM calls, logs tokens saved)
  - token monitor :9090  (the Simplicio Token Monitor web dashboard)
  - menu-bar / tray app  (live tokens saved)

Backends:
  macOS    → launchd LaunchAgents      (setup_simplicio.sh also does this)
  Linux    → systemd --user units
  Windows  → Startup-folder launchers (pythonw, no console window)

Usage:
  python3 scripts/install_services.py install     # register + start all services
  python3 scripts/install_services.py uninstall   # stop + remove them
  python3 scripts/install_services.py status       # report
  python3 scripts/install_services.py paths        # JSON list of paths install() would touch

`install()`/`uninstall()`/`service_paths()` are also called internally (in-process import) by
`scripts/install_executor.py`'s "service" step (#293 gap 1) when `apply()` is called with
`with_service=True` — so OS-level service registration is wired into the SAME transactional,
backed-up, rollback-eligible flow as every other install effect, instead of being a separate
manual step a human has to remember to run after `apply()` returns.
"""
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
HOME = Path.home()
PY = sys.executable or shutil.which("python3") or "python3"
PROXY_PORT = os.environ.get("SIMPLICIO_PROXY_PORT", "8788")
MONITOR_PORT = os.environ.get("SIMPLICIO_MONITOR_PORT", "9090")
# Native engine forwards to the upstream HOST (it appends the request path itself).
UPSTREAM = os.environ.get("SIMPLICIO_PROXY_UPSTREAM", "https://api.deepseek.com")

# The native Simplicio capture engine — self-contained, no external binary.
NATIVE_ENGINE = str(REPO / "engine" / "simplicio_engine.py")


def engine_bin():
    """The capture engine entrypoint (native module via the current Python)."""
    return NATIVE_ENGINE


PROXY = [PY, NATIVE_ENGINE, "proxy", "--port", PROXY_PORT, "--upstream", UPSTREAM, "--host", "127.0.0.1"]
MONITOR = [PY, str(REPO / "hooks" / "simplicio_dashboard.py")]
TRAY = [PY, str(REPO / "app" / "simplicio_tray.py")]
SERVICES = {"proxy": PROXY, "token-monitor": MONITOR, "tray": TRAY}
# ONLY the capture proxy auto-starts (the wired clients need it). The dashboard + tray are
# on-demand (open with scripts/simplicio-economy.sh monitor / tray). uninstall still sweeps all 3.
AUTOSTART = {"proxy": SERVICES["proxy"]}
# SIMPLICIO_HOME is set explicitly so the proxy can always write savings/logs even when the
# service runs with an unset/unwritable $HOME (verified necessary in the systemd field-test).
ENVS = {"PORT": MONITOR_PORT, "SIMPLICIO_PROXY_PORT": PROXY_PORT, "SIMPLICIO_MONITOR_PORT": MONITOR_PORT,
        "SIMPLICIO_HOME": str(HOME / ".simplicio-loop")}


# ── Linux: systemd --user ────────────────────────────────────────────────────
def _systemd_dir():
    d = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _systemd_unit(name, cmd):
    env = dict(ENVS)
    # Help systemd's minimal env resolve the engine binary if ExecStart isn't absolute.
    env["PATH"] = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    env_lines = "\n".join(f"Environment={k}={v}" for k, v in env.items())
    return (
        "[Unit]\nDescription=Simplicio %s\nAfter=network.target\n\n"
        "[Service]\nExecStart=%s\nRestart=always\nRestartSec=3\n%s\n\n"
        "[Install]\nWantedBy=default.target\n"
        % (name, " ".join(_q(c) for c in cmd), env_lines)
    )


def linux_install():
    d = _systemd_dir()
    # Sweep any leftover monitor/tray auto-start units from a previous install.
    for name in SERVICES:
        if name not in AUTOSTART:
            subprocess.run(["systemctl", "--user", "disable", "--now", f"simplicio-{name}.service"], check=False)
            (d / f"simplicio-{name}.service").unlink(missing_ok=True)
    for name, cmd in AUTOSTART.items():
        (d / f"simplicio-{name}.service").write_text(_systemd_unit(name, cmd))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    for name in AUTOSTART:
        subprocess.run(["systemctl", "--user", "enable", "--now", f"simplicio-{name}.service"], check=False)
    print("✅ systemd --user: %s auto-starts. Dashboard/tray on-demand: scripts/simplicio-economy.sh monitor / tray"
          % ", ".join(f"simplicio-{n}" for n in AUTOSTART))


def linux_uninstall():
    d = _systemd_dir()
    for name in SERVICES:
        subprocess.run(["systemctl", "--user", "disable", "--now", f"simplicio-{name}.service"], check=False)
        (d / f"simplicio-{name}.service").unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print("✅ systemd --user services removed")


# ── Windows: Startup folder launchers (pythonw, no console) ───────────────────
def _startup_dir():
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _windows_bat(name, cmd):
    pyw = PY.replace("python.exe", "pythonw.exe")
    exe = pyw if cmd[0] == PY else cmd[0]
    args = " ".join(f'"{a}"' for a in cmd[1:])
    # Quoted `set "K=V"` per line — `set K=V & ...` would bake a trailing space into the value.
    env_set = "\r\n".join(f'set "{k}={v}"' for k, v in ENVS.items())
    return f'@echo off\r\n{env_set}\r\nstart "" /b "{exe}" {args}\r\n'


def windows_install():
    startup = _startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    # Sweep any leftover monitor/tray auto-start launchers from a previous install.
    for name in SERVICES:
        if name not in AUTOSTART:
            (startup / f"simplicio-{name}.bat").unlink(missing_ok=True)
    for name, cmd in AUTOSTART.items():
        (startup / f"simplicio-{name}.bat").write_text(_windows_bat(name, cmd))
        subprocess.Popen([startup / f"simplicio-{name}.bat"], shell=True)  # start now
    print("✅ Windows Startup: %s auto-starts (also launched now). Dashboard/tray on-demand."
          % ", ".join(f"simplicio-{n}" for n in AUTOSTART))


def windows_uninstall():
    startup = _startup_dir()
    for name in SERVICES:
        (startup / f"simplicio-{name}.bat").unlink(missing_ok=True)
    print("✅ Windows Startup launchers removed (running instances stay until reboot/kill)")


# ── macOS: launchd is handled by setup_simplicio.sh ──────────────────────────
def macos_note():
    print("macOS uses launchd — run:  bash scripts/setup_simplicio.sh")
    print("(services: ai.simplicio.proxy / ai.simplicio.token-monitor / ai.simplicio.tray)")


def _q(s):
    return f'"{s}"' if " " in str(s) else str(s)


def _shell_profile():
    shell = os.environ.get("SHELL", "")
    if "zsh" in shell:
        return HOME / ".zshrc"
    if "bash" in shell:
        return HOME / ".bashrc"
    return HOME / ".profile"


def cmd_wire(on=True):
    """Always-capture: route Claude (Anthropic) + Codex/OpenAI clients through the local proxy so
    the monitor measures them too (Simplicio Agent is already routed). The engine routes each model to its
    REAL provider (no model swap). NOTE: OpenAI clients append /chat/completions so the base needs
    a /v1 suffix; Claude appends /v1/messages so its base must NOT carry /v1. Opt out: SIMPLICIO_NO_WIRE=1."""
    if os.environ.get("SIMPLICIO_NO_WIRE") == "1":
        print("⬡ wire skipped (SIMPLICIO_NO_WIRE=1)")
        return
    target = f"http://127.0.0.1:{PROXY_PORT}/v1"   # OpenAI / Codex / Cursor / OpenCode
    root = f"http://127.0.0.1:{PROXY_PORT}"          # Anthropic / Claude (no /v1)
    # Claude Code / the `claude` CLI auth via OAuth, which 401s through the proxy. Only route Anthropic
    # when a static ANTHROPIC_API_KEY is set — otherwise wiring it would break the user's claude CLI.
    wire_anthropic = on and bool(os.environ.get("ANTHROPIC_API_KEY"))
    if os.name == "nt":
        if on:
            subprocess.run(["setx", "OPENAI_BASE_URL", target], check=False)
            subprocess.run(["setx", "ANTHROPIC_BASE_URL", root if wire_anthropic else ""], check=False)
            extra = f" · ANTHROPIC_BASE_URL -> {root}" if wire_anthropic else " · ANTHROPIC skipped (OAuth claude; set ANTHROPIC_API_KEY)"
            print(f"✅ OPENAI_BASE_URL -> {target}{extra} (reopen your tools)")
        else:
            subprocess.run(["setx", "OPENAI_BASE_URL", ""], check=False)
            subprocess.run(["setx", "ANTHROPIC_BASE_URL", ""], check=False)
            print("✅ OPENAI_BASE_URL + ANTHROPIC_BASE_URL cleared")
        return
    prof = _shell_profile()
    txt = prof.read_text() if prof.exists() else ""
    import re
    txt = re.sub(r"(?m)^export (OPENAI_BASE_URL|ANTHROPIC_BASE_URL|SIMPLICIO_CAPTURE)=.*$", "", txt).rstrip()
    if on:
        txt += f"\nexport OPENAI_BASE_URL={target}\nexport SIMPLICIO_CAPTURE=on\n"
        if wire_anthropic:
            txt += f"export ANTHROPIC_BASE_URL={root}\n"
    prof.write_text(txt + "\n")
    routed = ("Claude + " if wire_anthropic else "") + "Codex/OpenAI"
    print(f"✅ {prof}: {routed} {'routed through the proxy (effective next shell)' if on else 'cleared'}"
          + ("" if wire_anthropic or not on else " · Claude skipped (OAuth — set ANTHROPIC_API_KEY to capture it)"))


def selftest():
    """Validate the generated systemd/Windows artifacts on any OS (no install)."""
    ok = True
    print(f"⬡ install_services self-test · engine={os.path.basename(engine_bin())} · py={os.path.basename(PY)}")
    for name, cmd in SERVICES.items():
        u = _systemd_unit(name, cmd)
        for key in ("[Unit]", "[Service]", "ExecStart=", "Restart=always", "[Install]", "WantedBy=default.target"):
            if key not in u:
                print(f"  ✗ systemd simplicio-{name}: missing {key}"); ok = False
        if "\nExecStart=\n" in u or u.rstrip().endswith("ExecStart="):
            print(f"  ✗ systemd simplicio-{name}: empty ExecStart"); ok = False
    print(f"  {'✓' if ok else '✗'} systemd units ({len(SERVICES)})")
    wok = True
    for name, cmd in SERVICES.items():
        b = _windows_bat(name, cmd)
        if not b.startswith("@echo off") or 'start "" /b' not in b:
            print(f"  ✗ windows simplicio-{name}: malformed"); wok = False
    print(f"  {'✓' if wok else '✗'} windows launchers ({len(SERVICES)})")
    for name, cmd in SERVICES.items():
        target = cmd[1] if cmd[0] == PY else cmd[0]
        exists = os.path.exists(target) or bool(shutil.which(os.path.basename(target)))
        print(f"  {'✓' if exists else '·'} {name}: {os.path.basename(cmd[0])} {os.path.basename(cmd[1]) if len(cmd) > 1 else ''}")
    print(f"  ✓ wire target: http://127.0.0.1:{PROXY_PORT}/v1")
    print("PASS" if (ok and wok) else "FAIL")
    return 0 if (ok and wok) else 1


def service_paths():
    """The exact file path(s) `install()` would create/update on THIS OS, for the transactional
    executor to back up before mutating (#293 gap 1: "wire OS-level service registration into
    apply() for full-stack mode"). Always freshly computed from the CURRENT environment (HOME/
    APPDATA/XDG_CONFIG_HOME) — never cached — so a caller that redirects those env vars (tests;
    a non-default install root) gets paths matching where `install()` will actually write.
    Returns [] on macOS/other (handled by the separate `setup_simplicio.sh` launchd path, not
    wired into the transactional executor)."""
    osname = platform.system()
    if osname == "Linux":
        d = _systemd_dir()
        return [str(d / ("simplicio-%s.service" % name)) for name in AUTOSTART]
    if osname == "Windows":
        d = _startup_dir()
        return [str(d / ("simplicio-%s.bat" % name)) for name in AUTOSTART]
    return []


def cmd_paths():
    import json as _json
    print(_json.dumps(service_paths()))
    return 0


def cmd_status():
    import socket
    print(f"⬡ Simplicio services · {platform.system()}")
    for port, what in ((PROXY_PORT, "capture proxy"), (MONITOR_PORT, "token monitor")):
        try:
            socket.create_connection(("127.0.0.1", int(port)), 0.5).close()
            print(f"  ● {what:14} :{port} live")
        except OSError:
            print(f"  ○ {what:14} :{port} offline")


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    osname = platform.system()
    if action == "status":
        return cmd_status()
    if action == "selftest":
        sys.exit(selftest())
    if action == "wire":
        return cmd_wire(True)
    if action == "unwire":
        return cmd_wire(False)
    if action == "paths":
        sys.exit(cmd_paths())
    if osname == "Darwin":
        return macos_note()
    if osname == "Linux":
        return linux_install() if action == "install" else linux_uninstall()
    if osname == "Windows":
        return windows_install() if action == "install" else windows_uninstall()
    print(f"unsupported OS: {osname}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
