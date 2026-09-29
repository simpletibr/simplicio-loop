"""The turbo model call, exactly as benchmarked: OpenRouter, pinned session, reasoning off.

`simplicio-loop turbo` and the benchmark's `simplicio` arm both call `complete`, so the
benchmark measures this code. The request is the one the benchmark measured:
- model `deepseek/deepseek-v4.1-flash` (override with `SIMPLICIO_TURBO_MODEL`)
- temperature 0, with usage included in the response
- `"reasoning": {"enabled": false}`
- a stable `x-session-id` per repository, so every call reads the same provider's prompt cache

Two latency guards, both measured or simulated on the benchmark calls:
- **Kept-alive connection.** One pooled HTTPS client is reused for every call, which saves the
  TCP+TLS handshake (~50 ms per call measured against openrouter.ai).
- **Hedged request.** A call still running after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds (default
  10; 0 disables it) gets a duplicate on another session, and the first good answer wins. The
  losing request is billed too: `drain_hedges()` waits for it so callers can count its tokens.
  Why 10 s: the hedge only pays on a real tail. Measured over 12 CLI calls per release, normal calls
  took 1.6-8.0 s depending on the provider that answered (the slowest, Relace, about 8 s) and the one
  tail took 19.6 s. The 2.5 s of 3.45.1 came from a simulation with Together only; on the real mix it
  hedged 5 of 12 calls and billed a duplicate for calls that were fine (4-task sets cost 45-57% more).
  10 s is above the ~8 s slowest normal call and below the tails it exists to cut.

Without `OPENROUTER_API_KEY` it fails closed with `turbo_provider_key_missing`.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "SIMPLICIO_TURBO_MODEL"
HEDGE_ENV = "SIMPLICIO_TURBO_HEDGE_AFTER"
DEFAULT_HEDGE_AFTER = 10.0
DEFAULT_TIMEOUT = 300

_lock = threading.Lock()
_client: httpx.Client | None = None
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="simplicio-turbo")
_hedge_losers: list[concurrent.futures.Future] = []


class TurboProviderError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


def model_name() -> str:
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


def hedge_after() -> float:
    raw = os.environ.get(HEDGE_ENV, "").strip()
    try:
        return float(raw) if raw else DEFAULT_HEDGE_AFTER
    except ValueError:
        return DEFAULT_HEDGE_AFTER


def require_key(api_key: str | None = None) -> str:
    key = (api_key or os.environ.get(KEY_ENV, "")).strip()
    if not key:
        raise TurboProviderError(
            "turbo_provider_key_missing",
            f"set {KEY_ENV} (OpenRouter) so simplicio-loop turbo can call {model_name()}",
        )
    return key


def session_id_for(root: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:16]
    return f"simplicio-turbo-{digest}"


def _http_client() -> httpx.Client:
    """One pooled client for the process: every call reuses a kept-alive connection."""
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(
                timeout=DEFAULT_TIMEOUT,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
            )
        return _client


def _post(body: Mapping[str, Any], key: str, session_id: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    try:
        response = _http_client().post(
            API_URL,
            json=dict(body),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {key}",
                "x-session-id": session_id,
                "X-Title": "simplicio-loop turbo",
            },
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - started}
    latency = time.time() - started
    if response.status_code != 200:
        return {"ok": False, "error": f"HTTP {response.status_code}: {response.text[:500]}", "latency_s": latency}
    try:
        parsed = response.json()
    except ValueError as exc:
        return {"ok": False, "error": f"bad JSON: {exc}", "latency_s": latency}
    if "error" in parsed:
        return {"ok": False, "error": str(parsed["error"])[:500], "latency_s": latency}
    usage = parsed.get("usage") or {}
    choice = (parsed.get("choices") or [{}])[0]
    return {
        "ok": True,
        "content": (choice.get("message") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "provider": parsed.get("provider"),
        "model": parsed.get("model", body["model"]),
        "session_id": session_id,
        "latency_s": latency,
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
        "cost": usage.get("cost"),
        "cost_usd": usage.get("cost"),
    }


def complete(arm: str, messages: Sequence[Mapping[str, Any]], *, session_id: str,
             api_key: str | None = None, reasoning_off: bool = True, max_tokens: int | None = None,
             hedge: float | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """One chat completion, hedged after `hedge` seconds. Never returns the key."""
    del arm  # the provider call is the same for every caller
    key = require_key(api_key)
    body: dict[str, Any] = {
        "model": model_name(),
        "messages": list(messages),
        "temperature": 0,
        "usage": {"include": True},
    }
    if reasoning_off:
        body["reasoning"] = {"enabled": False}
    if max_tokens:
        body["max_tokens"] = max_tokens
    wait = hedge_after() if hedge is None else hedge
    started = time.time()
    primary = _pool.submit(_post, body, key, session_id, timeout)
    if wait <= 0:
        return {**primary.result(), "hedged": False}
    try:
        return {**primary.result(timeout=wait), "hedged": False}
    except concurrent.futures.TimeoutError:
        pass
    duplicate = _pool.submit(_post, body, key, f"{session_id}-hedge", timeout)
    done, _ = concurrent.futures.wait([primary, duplicate], return_when=concurrent.futures.FIRST_COMPLETED)
    first = primary if primary in done else duplicate
    winner, loser = (first, duplicate if first is primary else primary)
    result = winner.result()
    if not result.get("ok"):  # the faster one failed: the other is the answer
        winner, loser = loser, winner
        result = winner.result()
    else:
        with _lock:
            _hedge_losers.append(loser)
    return {**result, "hedged": True, "hedge_winner": "primary" if winner is primary else "duplicate",
            "latency_s": time.time() - started}


def drain_hedges(timeout: float = 120.0) -> list[dict[str, Any]]:
    """Wait for the losing side of every hedged call; its tokens are billed too."""
    with _lock:
        pending = list(_hedge_losers)
        _hedge_losers.clear()
    records = []
    for future in pending:
        try:
            reply = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            continue
        if reply.get("ok"):
            records.append({**reply, "hedge_loser": True})
    return records
