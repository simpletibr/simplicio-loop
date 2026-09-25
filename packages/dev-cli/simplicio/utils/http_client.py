"""Shared httpx client with connection pooling.

Why a single shared client: every call to `httpx.Client()` opens a new
connection pool with its own TLS handshake. Reusing one client across a
benchmark batch or pipeline cuts the round-trip cost of repeated calls to
the same endpoint by an order of magnitude. The client is constructed
lazily on first use and disposed at process exit.
"""

from __future__ import annotations

import atexit
import os

import httpx

_client: httpx.Client | None = None
_aclient: httpx.AsyncClient | None = None


def _config() -> dict:
    return {
        "timeout": httpx.Timeout(
            connect=float(os.environ.get("SIMPLICIO_HTTP_CONNECT_TIMEOUT", "10")),
            read=float(os.environ.get("SIMPLICIO_HTTP_READ_TIMEOUT", "120")),
            write=float(os.environ.get("SIMPLICIO_HTTP_WRITE_TIMEOUT", "30")),
            pool=float(os.environ.get("SIMPLICIO_HTTP_POOL_TIMEOUT", "10")),
        ),
        "limits": httpx.Limits(
            max_connections=int(os.environ.get("SIMPLICIO_HTTP_MAX_CONN", "100")),
            max_keepalive_connections=int(os.environ.get("SIMPLICIO_HTTP_KEEPALIVE", "20")),
        ),
        "follow_redirects": True,
    }


def client() -> httpx.Client:
    """Return the shared httpx.Client, building it on first use."""
    global _client
    if _client is None:
        _client = httpx.Client(**_config())
        atexit.register(_close)
    return _client


def _close() -> None:
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None


def aclient() -> httpx.AsyncClient:
    """Return the shared async client (issue #212), building it on first use.

    Mirrors `client()`'s pooling rationale for the async pipeline path.
    There is no `atexit` hook here — `httpx.AsyncClient.aclose()` is a
    coroutine, so async callers close it explicitly via `aclose()` (see
    `simplicio.runtime_async.RuntimeContext.aclose`).
    """
    global _aclient
    if _aclient is None:
        _aclient = httpx.AsyncClient(**_config())
    return _aclient


async def aclose() -> None:
    global _aclient
    if _aclient is not None:
        try:
            await _aclient.aclose()
        except Exception:
            pass
        _aclient = None


def post_json(url: str, payload: dict, *, headers: dict | None = None, timeout: float | None = None) -> dict:
    """POST a JSON body and decode the JSON response. Uses the shared client.

    `timeout` lets callers override the read timeout for slow LLM endpoints
    without changing the env-driven default for the whole process.
    """
    from .serialization import dumps, loads

    headers = dict(headers or {})
    headers.setdefault("Content-Type", "application/json")
    response = client().post(
        url,
        content=dumps(payload),
        headers=headers,
        timeout=timeout if timeout is not None else None,
    )
    response.raise_for_status()
    return loads(response.content)


async def apost_json(
    url: str, payload: dict, *, headers: dict | None = None, timeout: float | None = None
) -> dict:
    """Async counterpart of `post_json` — same contract, shared async client."""
    from .serialization import dumps, loads

    headers = dict(headers or {})
    headers.setdefault("Content-Type", "application/json")
    response = await aclient().post(
        url,
        content=dumps(payload),
        headers=headers,
        timeout=timeout if timeout is not None else None,
    )
    response.raise_for_status()
    return loads(response.content)
