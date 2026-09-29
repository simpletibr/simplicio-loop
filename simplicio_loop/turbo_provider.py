"""The turbo model call, exactly as benchmarked: OpenRouter, pinned session, reasoning off.

`simplicio-loop turbo` and the benchmark's `simplicio` arm both call `complete`, so the
benchmark measures this code. The request is the one the benchmark measured:
- model `deepseek/deepseek-v4.1-flash` (override with `SIMPLICIO_TURBO_MODEL`)
- temperature 0, with usage included in the response
- `"reasoning": {"enabled": false}`
- a stable `x-session-id` per repository, so every call reads the same provider's prompt cache

Without `OPENROUTER_API_KEY` it fails closed with `turbo_provider_key_missing`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
KEY_ENV = "OPENROUTER_API_KEY"
MODEL_ENV = "SIMPLICIO_TURBO_MODEL"
DEFAULT_TIMEOUT = 300


class TurboProviderError(RuntimeError):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code


def model_name() -> str:
    return os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL


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


def complete(arm: str, messages: Sequence[Mapping[str, Any]], *, session_id: str,
             api_key: str | None = None, reasoning_off: bool = True,
             timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """One chat completion. Returns the fields the turbo engine records; never the key."""
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
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "x-session-id": session_id,
            "X-Title": "simplicio-loop turbo",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"ok": False, "error": f"HTTP {exc.code}: {detail}", "latency_s": time.time() - started}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "latency_s": time.time() - started}
    if "error" in parsed:
        return {"ok": False, "error": str(parsed["error"])[:500], "latency_s": time.time() - started}
    usage = parsed.get("usage") or {}
    choice = (parsed.get("choices") or [{}])[0]
    return {
        "ok": True,
        "content": (choice.get("message") or {}).get("content") or "",
        "finish_reason": choice.get("finish_reason"),
        "provider": parsed.get("provider"),
        "model": parsed.get("model", body["model"]),
        "latency_s": time.time() - started,
        "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
        "completion_tokens": usage.get("completion_tokens", 0) or 0,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0,
        "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0,
        "cost": usage.get("cost"),
        "cost_usd": usage.get("cost"),
    }
