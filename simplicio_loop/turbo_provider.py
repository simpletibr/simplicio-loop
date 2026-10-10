"""The turbo model call, exactly as benchmarked: OpenRouter, pinned session, reasoning off.

`simplicio-loop turbo` and the benchmark's `simplicio` arm both call `complete`, so the
benchmark measures this code. The request is the one the benchmark measured:
- model `deepseek/deepseek-v4.1-flash` (override with `SIMPLICIO_TURBO_MODEL`)
- temperature 0, with usage included in the response
- `"reasoning": {"enabled": false}`
- a stable `x-session-id` per repository, so every call reads the same provider's prompt cache

Two latency guards, both measured or simulated on the benchmark calls:
- **Kept-alive connection.** One pooled `httpx.AsyncClient` is reused for every call, which saves the
  TCP+TLS handshake (~50 ms per call measured against openrouter.ai). `close()` releases it.
- **Hedged request.** A call still running after `SIMPLICIO_TURBO_HEDGE_AFTER` seconds (default
  10; 0 disables it) gets a duplicate on another session as a second asyncio task, and the first good
  answer wins. The losing task is cancelled (no thread pool); a cancelled request reports no usage, so
  only the winner's tokens are counted.
  Why 10 s: the hedge only pays on a real tail. Measured over 12 CLI calls per release, normal calls
  took 1.6-8.0 s depending on the provider that answered (the slowest, Relace, about 8 s) and the one
  tail took 19.6 s. The 2.5 s of 3.45.1 came from a simulation with Together only; on the real mix it
  hedged 5 of 12 calls and billed a duplicate for calls that were fine (4-task sets cost 45-57% more).
  10 s is above the ~8 s slowest normal call and below the tails it exists to cut.

Without `OPENROUTER_API_KEY` it fails closed with `turbo_provider_key_missing`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import httpx

from .input_ceiling import CeilingConfigError, InputCeilingExceeded, Projection, enforce_budget, resolve_ceiling

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "SIMPLICIO_TURBO_MODEL"
HEDGE_ENV = "SIMPLICIO_TURBO_HEDGE_AFTER"
DEFAULT_HEDGE_AFTER = 10.0
DEFAULT_TIMEOUT = 300
CONCURRENCY_ENV = "SIMPLICIO_TURBO_CONCURRENCY"
DEFAULT_CONCURRENCY = 8

_client: httpx.AsyncClient | None = None


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


def concurrency() -> int:
    """Max concurrent model calls (default 8; set SIMPLICIO_TURBO_CONCURRENCY)."""
    raw = os.environ.get(CONCURRENCY_ENV, "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_CONCURRENCY
    except ValueError:
        return DEFAULT_CONCURRENCY


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


async def _http_client() -> httpx.AsyncClient:
    """One pooled async client for the process: every call reuses a kept-alive connection."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
        )
    return _client


async def _post(body: Mapping[str, Any], key: str, session_id: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    try:
        client = await _http_client()
        response = await client.post(
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
        "usage_reported": "usage" in parsed,
    }


def _gate_input(messages: Sequence[Mapping[str, Any]], response_format: Mapping[str, Any] | None,
                repo_root: str | os.PathLike[str] | None) -> None:
    """Refuse a request whose projected prompt is above the input-token ceiling (#1608). No usage exists before the
    request, so the projection is ESTIMATED. Nothing is sent when it is over; a bad ceiling setting fails loud too."""
    prompt = json.dumps(list(messages), ensure_ascii=False, default=str)
    if response_format:
        prompt += json.dumps(dict(response_format), ensure_ascii=False, default=str)
    try:
        ceiling = resolve_ceiling(Path.cwd() if repo_root is None else repo_root)
        enforce_budget(Projection.estimated(prompt), ceiling)
    except CeilingConfigError as exc:
        raise TurboProviderError(exc.reason_code, str(exc)) from exc
    except InputCeilingExceeded as exc:
        raise TurboProviderError(
            exc.reason_code, f"{exc}; the request was not sent, split the task or hand off to a fresh agent") from exc


async def complete(arm: str, messages: Sequence[Mapping[str, Any]], *, session_id: str,
                   api_key: str | None = None, reasoning_off: bool = True, max_tokens: int | None = None,
                   response_format: Mapping[str, Any] | None = None,
                   hedge: float | None = None, timeout: int = DEFAULT_TIMEOUT,
                   repo_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """One chat completion, hedged after `hedge` seconds. Never returns the key.

    `response_format` (a strict json_schema, see structured_output) is not sent with `max_tokens=1`: the one-token
    warm-up reply cannot hold a JSON object.

    The projected prompt must fit the input-token ceiling of `input_ceiling`; otherwise `TurboProviderError`
    (`input_ceiling_exceeded`) is raised before any request leaves the process.
    """
    del arm
    key = require_key(api_key)
    _gate_input(messages, response_format if max_tokens != 1 else None, repo_root)
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
    if response_format and max_tokens != 1:
        body["response_format"] = dict(response_format)
    wait = hedge_after() if hedge is None else hedge
    started = time.time()
    primary = asyncio.create_task(_post(body, key, session_id, timeout))
    tasks = [primary]
    try:
        if wait > 0:
            # wait() does not cancel the primary on timeout (wait_for would): it keeps running next to the hedge.
            await asyncio.wait({primary}, timeout=wait)
        if primary.done() or wait <= 0:
            return {**await primary, "hedged": False}
        duplicate = asyncio.create_task(_post(body, key, f"{session_id}-hedge", timeout))
        tasks.append(duplicate)
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        winner = primary if primary in done else duplicate
        result = winner.result()
        if not result.get("ok"):  # the faster one failed: the other is the answer
            winner = duplicate if winner is primary else primary
            result = await winner
        return {**result, "hedged": True, "hedge_winner": "primary" if winner is primary else "duplicate",
                "latency_s": time.time() - started}
    finally:
        # The loser (or, if the caller was cancelled, every request) is cancelled: no thread, no orphan task.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def close() -> None:
    """Close the async client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
