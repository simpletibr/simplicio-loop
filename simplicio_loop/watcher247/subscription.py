"""Live Simplicio MCP subscription gate: the watcher runs only while it is active."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request

from .. import auth
from . import config

_UA = "simplicio-loop-247"


def _http_json_sync(method: str, url: str, payload: dict | None, headers: dict) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": _UA, **headers},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


async def http_json(method: str, url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    """The only network call of the gate; tests replace it. Raises urllib.error.HTTPError on 4xx/5xx."""
    return await asyncio.to_thread(_http_json_sync, method, url, payload, headers or {})


def _public_subscription(ent: dict, reason: str, active: bool) -> dict:
    return {
        "active": active,
        "reason": reason,
        "tier": ent.get("tier"),
        "status": ent.get("status"),
        "source": ent.get("source"),
        "plan": ent.get("plan"),
    }


def _http_detail(exc: urllib.error.HTTPError) -> str:
    return exc.read()[:180].decode(errors="replace")


async def mcp_subscription() -> dict:
    """Reasons: ok, subscription_required, login_missing, login_insecure (a symlink or a file others can read),
    refresh_failed, entitlement_required, validate_unreachable.

    The login file is read, checked, locked and written by `simplicio_loop.auth`, shared with the Runtime."""
    try:
        login = await asyncio.to_thread(auth.read_login, config.LOGIN)
    except auth.LoginError as exc:
        if exc.reason_code in {"login_missing", "login_invalid"}:
            return _public_subscription({}, "login_missing", False)
        return _public_subscription({}, "login_insecure", False) | {"detail": str(exc)[:180]}
    access = str(login.get("access_token") or "").strip()
    refresh = str(login.get("refresh_token") or "").strip()
    expires = int(login.get("access_expires_at") or 0)
    if refresh and expires <= int(time.time()) + 60:
        loop = asyncio.get_running_loop()

        def post(payload: dict) -> dict:  # runs in the worker thread, under the login lock; the request runs on the loop
            return asyncio.run_coroutine_threadsafe(http_json("POST", config.TOKEN_URL, payload), loop).result()

        try:
            login, _ = await asyncio.to_thread(auth.refresh_if_due, config.LOGIN, post)
            access = str(login.get("access_token") or "").strip()
        except urllib.error.HTTPError as exc:
            return _public_subscription({}, "refresh_failed", False) | {"detail": _http_detail(exc)}
        except Exception as exc:
            return _public_subscription({}, "refresh_failed", False) | {"detail": str(exc)[:180]}
    if not access:
        return _public_subscription({}, "login_missing", False)
    try:
        payload = await http_json("GET", config.VALIDATE_URL, headers={"Authorization": f"Bearer {access}"})
    except urllib.error.HTTPError as exc:
        return _public_subscription({}, "entitlement_required", False) | {"detail": _http_detail(exc)}
    except Exception as exc:
        return _public_subscription({}, "validate_unreachable", False) | {"detail": str(exc)[:180]}
    ent = payload.get("entitlement") if isinstance(payload.get("entitlement"), dict) else {}
    status = str(ent.get("status") or "")
    source = str(ent.get("source") or "")
    tier = str(ent.get("tier") or "")
    active = bool(
        payload.get("active")
        and ent.get("active")
        and status in config.PAID_STATUS
        and source in config.PAID_SOURCES
        and tier not in {"", "free"}
    )
    return _public_subscription(ent, "ok" if active else "subscription_required", active)
