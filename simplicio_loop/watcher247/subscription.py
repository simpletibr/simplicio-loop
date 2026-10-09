"""Live Simplicio MCP subscription gate: the watcher runs only while it is active."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any

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


def _store_tokens_sync(login: dict, data: dict) -> None:
    now_ts = int(time.time())
    login["access_token"] = data["access_token"]
    login["refresh_token"] = data["refresh_token"]
    login["access_expires_at"] = now_ts + int(data.get("expires_in") or 0) - 30
    if data.get("refresh_token_persistent"):
        login["refresh_token_expires_at"] = 0
    else:
        login["refresh_token_expires_at"] = now_ts + int(data.get("refresh_token_expires_in") or 0)
    ent = data.get("entitlement")
    if isinstance(ent, dict):
        validated = login.setdefault("verification", {}).setdefault("validated", {})
        validated["ok"] = True
        validated["active"] = bool(ent.get("active"))
        validated["entitlement"] = ent
    fd, tmp = tempfile.mkstemp(dir=config.LOGIN.parent, prefix=config.LOGIN.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(login) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, config.LOGIN)


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
    """Reasons: ok, subscription_required, login_missing, refresh_failed,
    entitlement_required, validate_unreachable."""
    try:
        login: Any = json.loads(await asyncio.to_thread(config.LOGIN.read_text))
    except Exception:
        return _public_subscription({}, "login_missing", False)
    access = str(login.get("access_token") or "").strip()
    refresh = str(login.get("refresh_token") or "").strip()
    expires = int(login.get("access_expires_at") or 0)
    if refresh and expires <= int(time.time()) + 60:
        try:
            data = await http_json("POST", config.TOKEN_URL, {
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "client_id": config.MCP_CLIENT_ID,
            })
            await asyncio.to_thread(_store_tokens_sync, login, data)
            access = str(data.get("access_token") or "").strip()
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
