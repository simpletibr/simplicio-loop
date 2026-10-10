"""`simplicio-loop login | logout | auth status` (#1575): ONE Simplicio login, shared with the Simplicio Runtime.

The login file, its checks, its lock and its refresh live in `simplicio_loop.auth`. This module is the command line:

* login: with the Runtime installed, run its flow (`simplicio login google`, terminal attached) and then check the shared
  file. WITHOUT the Runtime the standalone flow is UNVERIFIED: no authorize or device endpoint is documented in THIS
  repository, so none is invented; the command prints how to install the Runtime.
* logout: delete the shared file. It logs the Runtime out too. Needs --yes.
* auth status: what the file says. Never a token, the e-mail is masked.

Exit codes: 0 done / logged in, 1 not logged in or not verified, 2 refused (logout without --yes).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlsplit

from . import auth

RUNTIME_INSTALL = {
    "macOS / Linux": "curl -fsSL https://raw.githubusercontent.com/wesleysimplicio/simplicio/master/install.sh | sh",
    "Windows (PowerShell)": "irm https://raw.githubusercontent.com/wesleysimplicio/simplicio/master/install.ps1 | iex",
}
RUNTIME_INSTALL_DOC = "https://github.com/simpletibr/simplicio-runtime/blob/main/INSTALL.md"
STANDALONE_UNVERIFIED = (
    "Standalone login is UNVERIFIED: no authorize or device endpoint is documented in this repository, so "
    "simplicio-loop does not start a login of its own. Install the Simplicio Runtime (it signs in with Google), "
    "then run: simplicio-loop login"
)


# What `simplicio login google` is given. Everything else is left out on purpose: the shell of a developer holds other
# programs' credentials (GH_TOKEN, API keys, SIMPLICIO_LOGIN_TOKEN) and a sign-in needs none of them.
_CHILD_ENV = frozenset({
    "PATH", "HOME", "USERPROFILE", "USER", "LOGNAME", "SHELL", "TERM", "COLORTERM", "LANG", "LANGUAGE", "TZ", "TMPDIR",
    "TEMP", "TMP", "DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "BROWSER", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "PATHEXT", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", auth.RUNTIME_ENV,
    "SIMPLICIO_AUTH_BASE_URL", "SIMPLICIO_HOME",
})
_CHILD_ENV_PREFIXES = ("LC_", "XDG_")


def _runtime_env(env: dict) -> dict:
    return {name: value for name, value in env.items() if name in _CHILD_ENV or name.startswith(_CHILD_ENV_PREFIXES)}


def _print(doc: dict, as_json: bool, lines: list) -> None:
    print(json.dumps(doc, ensure_ascii=False, sort_keys=True) if as_json else "\n".join(lines))


def _when(timestamp: int, now: float) -> str:
    stamp = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    seconds = int(abs(timestamp - now))
    span = (f"{seconds // 86400} d" if seconds >= 2 * 86400 else f"{seconds // 3600} h" if seconds >= 2 * 3600
            else f"{seconds // 60} min" if seconds >= 120 else f"{seconds} s")
    return f"{'in ' + span if timestamp > now else span + ' ago'} ({stamp})"


def _status_lines(doc: dict, now: float) -> list:
    runtime = doc["runtime"]
    rt = f"{runtime['version'] or 'version unknown'} at {runtime['path']}" if runtime["found"] else "not found"
    if not doc.get("logged_in"):
        lines = [f"login: not logged in ({doc['reason_code']})", f"  file           {doc['path']}"]
        if doc.get("detail"):
            lines.append(f"  detail         {doc['detail']}")
        lines += [f"  fix            {doc['fix']}", f"  runtime        {rt}"]
    else:
        access = doc["access_expires_at"]
        lines = [
            "login: logged in" + (" (shared with the Simplicio Runtime)" if runtime["found"] else ""),
            f"  file           {doc['path']}",
            f"  account        {doc['email'] or 'unknown'}",
            f"  access token   {'expired ' if doc['access_expired'] else 'expires '}{_when(access, now)}",
            "  refresh token  " + ("none" if not doc["has_refresh_token"] else
                                 "expired" if doc["refresh_expired"] else
                                 f"valid until {_when(doc['refresh_expires_at'], now)}" if doc["refresh_expires_at"]
                                 else "valid, no expiry date"),
        ]
        ent = doc.get("entitlement")
        if ent:
            lines.append(f"  entitlement    {ent.get('tier')}, {ent.get('status')}, {ent.get('source')} "
                         "(cached in the file; --online asks the server)")
        lines.append(f"  runtime        {rt}")
    if not doc["shared_with_runtime"]:
        lines.append(f"WARN: the loop uses a DIFFERENT login file than the Runtime ({doc['runtime_path']}); "
                     "the two programs share a login only when they use the same file")
    return lines


# --- auth status -----------------------------------------------------------------------------------------------------


def _subscription_check() -> dict:
    import asyncio

    from .watcher247 import subscription

    return asyncio.run(subscription.mcp_subscription())


def status(*, as_json: bool = False, online: bool = False, check: Optional[Callable[[], dict]] = None,
           environ: Optional[dict] = None) -> int:
    now = time.time()
    doc = auth.describe(environ, now)
    if online and doc["logged_in"]:
        doc["subscription"] = (check or _subscription_check)()
    lines = _status_lines(doc, now)
    if "subscription" in doc:
        sub = doc["subscription"]
        lines.append(f"  subscription: {sub.get('reason')}" + (f" ({sub.get('tier')})" if sub.get("tier") else ""))
    _print(doc, as_json, lines)
    return 0 if doc["logged_in"] and doc.get("subscription", {"active": True}).get("active") else 1


# --- login -----------------------------------------------------------------------------------------------------------


def _run_runtime(command: list, env: dict, stdout: Optional[int]) -> int:
    return subprocess.call(command, env=env, stdout=stdout)


# --no-browser: Runtime 3.10.0 ignores BROWSER and runs the system opener, so the child gets opener stand-ins first on its
# PATH. They open nothing: they keep the sign-in address and print it, so the user can open it by hand.
_BROWSER_OPENERS = ("xdg-open", "open", "gio", "gnome-open", "kde-open", "sensible-browser", "x-www-browser", "wslview")
_OPENER_SHIM = r"""#!/bin/sh
for url; do :; done
printf '%s\n' "$url" > "$(dirname "$0")/sign-in-url"
printf 'Open this address in a browser to sign in:\n  %s\n' "$url" >&2
"""


def _can_block_browser() -> bool:
    return os.name != "nt"  # Windows opens the address with no program on PATH that could stand in


def _install_browser_shim(child: dict) -> str:
    shim_dir = tempfile.mkdtemp(prefix="simplicio-no-browser-")
    for name in _BROWSER_OPENERS:
        opener = os.path.join(shim_dir, name)
        with open(opener, "w", encoding="utf-8") as handle:
            handle.write(_OPENER_SHIM)
        os.chmod(opener, 0o755)
    child["PATH"] = shim_dir + os.pathsep + child.get("PATH", "")
    child["BROWSER"] = "true"
    return shim_dir


def _read_sign_in(shim_dir: Optional[str]) -> dict:
    if shim_dir is None:
        return {}
    try:
        with open(os.path.join(shim_dir, "sign-in-url"), encoding="utf-8") as handle:
            url = handle.read().strip()
    except OSError:
        return {}
    if not url:
        return {}
    codes = parse_qs(urlsplit(url).query).get("user_code")
    return {"sign_in_url": url, **({"user_code": codes[0]} if codes else {})}


def _sign_in_lines(sign_in: dict) -> list:
    if not sign_in:
        return []
    lines = ["", f"Open this address in a browser to sign in: {sign_in['sign_in_url']}"]
    if sign_in.get("user_code"):
        lines.append(f"Code: {sign_in['user_code']}")
    return lines


def login(*, as_json: bool = False, no_browser: bool = False, environ: Optional[dict] = None,
          run: Callable[[list, dict, Optional[int]], int] = _run_runtime) -> int:
    env = dict(os.environ if environ is None else environ)
    runtime = auth.runtime_binary(env)
    if runtime is None:
        doc = auth.describe(env)
        doc.update(schema="simplicio.login/v1", status="UNVERIFIED", reason_code="standalone_login_unverified",
                   detail=STANDALONE_UNVERIFIED, install=RUNTIME_INSTALL, install_doc=RUNTIME_INSTALL_DOC)
        lines = ["login: Simplicio Runtime not found", STANDALONE_UNVERIFIED, ""]
        lines += [f"  {name}: {command}" for name, command in RUNTIME_INSTALL.items()]
        lines += [f"  (documented in {RUNTIME_INSTALL_DOC}; not run by this command)"]
        if doc["logged_in"]:
            lines += ["", f"A usable login already exists in {doc['path']}. Run: simplicio-loop auth status"]
        _print(doc, as_json, lines)
        return 1
    path, runtime_path = auth.login_path(env), auth.runtime_login_path(env)
    child = _runtime_env(env)
    if path != runtime_path:  # for this run the Runtime must write where the loop reads
        child[auth.RUNTIME_ENV] = str(path)
    if no_browser and not _can_block_browser():
        doc = auth.describe(env)
        version = doc["runtime"]["version"] or "unknown"
        detail = (f"--no-browser is not supported on this system: Simplicio Runtime {version} opens the browser by "
                  "itself and has no option to stop it. Run: simplicio-loop login")
        doc.update(schema="simplicio.login/v1", status="REFUSED", reason_code="no_browser_unsupported", detail=detail)
        _print(doc, as_json, [f"login: {detail}"])
        return 2
    shim_dir = _install_browser_shim(child) if no_browser else None
    sys.stdout.flush()
    try:
        code = run([str(runtime), "login", "google"], child, 2 if as_json else None)  # --json: its output goes to stderr
        sign_in = _read_sign_in(shim_dir)
    finally:
        if shim_dir is not None:
            shutil.rmtree(shim_dir, ignore_errors=True)
    doc = auth.describe(env)
    doc.update(schema="simplicio.login/v1", runtime_exit_code=code)
    doc.update(sign_in)
    if code != 0:
        doc.update(status="NOT_VERIFIED", reason_code="runtime_login_failed", logged_in=False,
                   fix="simplicio-loop login")
        _print(doc, as_json, [f"login: the Runtime login ended with exit code {code}; the login is not verified"]
               + _sign_in_lines(sign_in))
        return 1
    if not doc["logged_in"]:
        doc["status"] = "NOT_VERIFIED"
        _print(doc, as_json, ["login: the Runtime finished, but the shared login file is not usable"]
               + _status_lines(doc, time.time()) + _sign_in_lines(sign_in))
        return 1
    doc["status"] = "VERIFIED"
    _print(doc, as_json, ["login: verified in the shared login file"] + _status_lines(doc, time.time())[1:])
    return 0


# --- logout ----------------------------------------------------------------------------------------------------------


def logout(*, yes: bool = False, as_json: bool = False, environ: Optional[dict] = None) -> int:
    path, runtime_path = auth.login_path(environ), auth.runtime_login_path(environ)
    shared = path == runtime_path  # the Runtime is logged out too only when it reads this very file
    doc: dict[str, Any] = {"schema": "simplicio.logout/v1", "path": str(path), "runtime_path": str(runtime_path),
                           "also_logs_out_runtime": shared}
    if not yes:
        doc.update(status="REFUSED", reason_code="confirmation_required")
        about = (f"{path} is shared with the Simplicio Runtime: logging out here logs the Runtime out too." if shared else
                 f"{path} is the login of simplicio-loop only. The Runtime reads {runtime_path} and stays logged in.")
        _print(doc, as_json, [f"logout: {about}", "Nothing was deleted. Run again with --yes to log out."])
        return 2
    try:
        removed = auth.clear_login(path)
    except auth.LoginError as exc:
        doc.update(status="FAILED", reason_code=exc.reason_code, detail=str(exc))
        _print(doc, as_json, [f"logout: {exc}"])
        return 1
    doc["status"] = "LOGGED_OUT" if removed else "NO_LOGIN"
    lines = [f"logout: removed {path}. " + ("The Runtime is logged out too (shared file)." if shared else
                                            f"The Runtime reads {runtime_path}, so it stays logged in."),
             "The refresh token is not revoked on the server: no revoke endpoint is documented in this repository."]
    if not removed:
        lines = [f"logout: no login file at {path}; nothing to remove"]
    _print(doc, as_json, lines)
    return 0


# --- the command line ------------------------------------------------------------------------------------------------


def configure_commands(sub) -> None:
    p_login = sub.add_parser("login", help="sign in with the Simplicio login shared with the Runtime")
    p_login.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    p_login.add_argument("--no-browser", action="store_true", help="ask the Runtime not to open a browser")
    p_logout = sub.add_parser("logout", help="delete the shared login file (this logs the Runtime out too)")
    p_logout.add_argument("--yes", action="store_true", help="confirm: without it nothing is deleted")
    p_logout.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    p_auth = sub.add_parser("auth", help="inspect the shared Simplicio login")
    auth_sub = p_auth.add_subparsers(dest="auth_command", required=True)
    p_status = auth_sub.add_parser("status", help="who is logged in, expiry, entitlement; never prints a token")
    p_status.add_argument("--json", action="store_true", help="emit one machine-readable JSON document")
    p_status.add_argument("--online", action="store_true",
                          help="also run the subscription check (may refresh the token, then asks the server)")


def dispatch(args) -> int:
    if args.command == "login":
        return login(as_json=args.json, no_browser=args.no_browser)
    if args.command == "logout":
        return logout(yes=args.yes, as_json=args.json)
    return status(as_json=args.json, online=args.online)
