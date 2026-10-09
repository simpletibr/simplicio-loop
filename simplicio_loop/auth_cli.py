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
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

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
    if path != runtime_path:  # the Runtime must write where the loop reads
        env[auth.RUNTIME_ENV] = str(path)
    if no_browser and os.name != "nt":
        env["BROWSER"] = "true"  # UNVERIFIED: the Runtime may ignore it and print its sign-in address anyway
    sys.stdout.flush()
    code = run([str(runtime), "login", "google"], env, 2 if as_json else None)  # --json: its output goes to stderr
    doc = auth.describe(env)
    doc.update(schema="simplicio.login/v1", runtime_exit_code=code)
    if code != 0:
        doc.update(status="NOT_VERIFIED", reason_code="runtime_login_failed", logged_in=False,
                   fix="simplicio-loop login")
        _print(doc, as_json, [f"login: the Runtime login ended with exit code {code}; the login is not verified"])
        return 1
    if not doc["logged_in"]:
        doc["status"] = "NOT_VERIFIED"
        _print(doc, as_json, ["login: the Runtime finished, but the shared login file is not usable"]
               + _status_lines(doc, time.time()))
        return 1
    doc["status"] = "VERIFIED"
    _print(doc, as_json, ["login: verified in the shared login file"] + _status_lines(doc, time.time())[1:])
    return 0


# --- logout ----------------------------------------------------------------------------------------------------------


def logout(*, yes: bool = False, as_json: bool = False, environ: Optional[dict] = None) -> int:
    path = auth.login_path(environ)
    shared = f"{path} is shared with the Simplicio Runtime: logging out here logs the Runtime out too."
    doc: dict[str, Any] = {"schema": "simplicio.logout/v1", "path": str(path), "also_logs_out_runtime": True}
    if not yes:
        doc.update(status="REFUSED", reason_code="confirmation_required")
        _print(doc, as_json, [f"logout: {shared}", "Nothing was deleted. Run again with --yes to log out."])
        return 2
    removed = auth.clear_login(path)
    doc["status"] = "LOGGED_OUT" if removed else "NO_LOGIN"
    lines = [f"logout: removed {path}. The Runtime is logged out too (shared file).",
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
