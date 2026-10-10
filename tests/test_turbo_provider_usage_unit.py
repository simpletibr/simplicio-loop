"""A usage the provider did not report is never MEASURED (#1612): `"usage": null`, `{}` and a missing key are not a measure.

The tokens of a task are reported MEASURED only from `usage_reported`, so a reply without a real usage object must say
`False` (the tokens stay 0 and the metric stays out of the MEASURED total).
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.input_ceiling import ENV_NAME

_MISSING = object()


def _complete(monkeypatch, tmp_path, usage):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.chdir(tmp_path)
    body = {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
    if usage is not _MISSING:
        body["usage"] = usage

    async def handler(request):
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def pooled():
        return client

    monkeypatch.setattr(turbo_provider, "_http_client", pooled)
    return asyncio.run(turbo_provider.complete("a", [{"role": "user", "content": "hi"}], session_id="s", hedge=0,
                                               repo_root=tmp_path))


@pytest.mark.parametrize("usage", [_MISSING, None, {}, {"prompt_tokens": 5}, [], "x"])
def test_a_reply_without_a_real_usage_is_not_measured(monkeypatch, tmp_path, usage):
    reply = _complete(monkeypatch, tmp_path, usage)
    assert reply["ok"] is True
    assert reply["usage_reported"] is False
    assert reply["completion_tokens"] == 0


@pytest.mark.parametrize("usage,tokens", [({"completion_tokens": 7}, 7), ({"completion_tokens": 0, "prompt_tokens": 3}, 0)])
def test_a_reply_with_completion_tokens_is_measured(monkeypatch, tmp_path, usage, tokens):
    reply = _complete(monkeypatch, tmp_path, usage)
    assert reply["usage_reported"] is True
    assert reply["completion_tokens"] == tokens
