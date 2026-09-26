"""Minimal OpenRouter chat-completions client using stdlib urllib only.

Loads the API key from a keys.env file at call time (never logs the raw
key). The path comes from the ``SIMPLICIO_BENCH_KEYS`` environment variable
-- there is no default and no fallback location, so a missing key file fails
loudly instead of silently reading someone else's keys.env.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_TIMEOUT = 600
MODEL = "deepseek/deepseek-v4.1-flash"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
KEYS_PATH_ENV = "SIMPLICIO_BENCH_KEYS"


def keys_path() -> str:
    path = os.environ.get(KEYS_PATH_ENV, "").strip()
    if not path:
        raise RuntimeError(
            f"{KEYS_PATH_ENV} is not set -- point it at a keys.env file with "
            "OR_KEY_NORMAL / OR_KEY_SIMPLICIO "
            "(never commit this file)."
        )
    return path


def _load_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    with open(keys_path()) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    return keys


def mask(key: str | None) -> str:
    if not key or len(key) < 8:
        return "sk-or-...xxxx"
    return "sk-or-..." + key[-4:]


# One key per arm -- lets an OpenRouter dashboard attribute spend per arm
# without ever mixing usage across them.
ARM_KEY_NAMES = {
    "normal": "OR_KEY_NORMAL",
    "simplicio": "OR_KEY_SIMPLICIO",
}


def get_key(arm: str) -> str:
    keys = _load_keys()
    name = ARM_KEY_NAMES.get(arm, "OR_KEY_NORMAL")
    key = keys.get(name)
    if not key:
        raise RuntimeError(f"missing {name} in {keys_path()}")
    return key


def chat(arm: str, messages: list[dict], temperature: float = 0,
         max_tokens: int | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Call OpenRouter chat completions. Returns a dict with content + metrics.

    ``max_tokens=None`` (the default) omits the field entirely from the
    request body, so the model uses its own full default output budget --
    no output cap is imposed by this harness, in any arm.

    Never raises the API key into the return value or an exception message.
    """
    key = get_key(arm)
    body = {
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "usage": {"include": True},
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://example.com/simplicio-llm-ab",
            "X-Title": "simplicio-llm-ab",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        status = e.code
    except Exception as e:
        latency = time.time() - t0
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "latency_s": latency,
            "key_masked": mask(key),
        }
    latency = time.time() - t0
    try:
        parsed = json.loads(raw)
    except Exception as e:
        return {
            "ok": False,
            "error": f"bad_json_response: {e}",
            "raw_snippet": raw[:500],
            "latency_s": latency,
            "status": status,
            "key_masked": mask(key),
        }
    if status != 200 or "error" in parsed:
        return {
            "ok": False,
            "error": parsed.get("error", parsed),
            "latency_s": latency,
            "status": status,
            "key_masked": mask(key),
        }
    usage = parsed.get("usage", {}) or {}
    choice = (parsed.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content", "")
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get(
        "reasoning_tokens", 0
    ) or 0
    cached_tokens = (usage.get("prompt_tokens_details") or {}).get(
        "cached_tokens", 0
    ) or 0
    cost = usage.get("cost", None)
    return {
        "ok": True,
        "content": content,
        "latency_s": latency,
        "model": parsed.get("model", MODEL),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost,
        "finish_reason": choice.get("finish_reason"),
        "key_masked": mask(key),
    }


def extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from model output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model output")
    candidate = text[start : end + 1]
    return json.loads(candidate)
