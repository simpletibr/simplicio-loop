"""The turbo provider does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import asyncio

import httpx
import pytest

from simplicio_loop import turbo_provider
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY

_BIG = [{"role": "user", "content": "word " * 5000}]
_SMALL = [{"role": "user", "content": "hello"}]


@pytest.fixture
def sent(monkeypatch, tmp_path):
    """Count the requests that reach the transport; run from an empty repo so no loop.toml leaks in."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.chdir(tmp_path)
    seen: list[httpx.Request] = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def pooled():
        return client

    monkeypatch.setattr(turbo_provider, "_http_client", pooled)
    return seen


def _complete(messages, **kwargs):
    return asyncio.run(turbo_provider.complete("a", messages, session_id="s", hedge=0, **kwargs))


def test_a_prompt_under_the_ceiling_is_sent(sent):
    assert _complete(_SMALL)["ok"] and len(sent) == 1


def test_a_prompt_over_the_ceiling_is_not_sent(sent, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1000")
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def test_the_ceiling_of_loop_toml_applies(sent, tmp_path):
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "loop.toml").write_text("%s = 1000\n" % TOML_KEY, encoding="utf-8")
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG, repo_root=tmp_path)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def test_the_response_format_counts_toward_the_prompt(sent, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1000")
    schema = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"description": "word " * 5000}}}
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_SMALL, response_format=schema)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def test_a_bad_ceiling_fails_loud_without_sending(sent, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "abc")
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_SMALL)
    assert raised.value.reason_code == "ceiling_invalid" and sent == []
