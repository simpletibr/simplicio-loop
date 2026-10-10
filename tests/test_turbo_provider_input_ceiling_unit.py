"""The turbo provider does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from simplicio_loop import turbo, turbo_cli, turbo_provider
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY

_BIG = [{"role": "user", "content": "word " * 5000}]
_SMALL = [{"role": "user", "content": "hello"}]


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


@pytest.fixture
def sent(monkeypatch, tmp_path, repo):
    """Count the requests that reach the transport. The cwd is ANOTHER empty directory than `repo`, so a gate that
    falls back to the cwd reads no loop.toml of the repo."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.delenv(ENV_NAME, raising=False)
    monkeypatch.chdir(elsewhere)
    seen: list[httpx.Request] = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def pooled():
        return client

    monkeypatch.setattr(turbo_provider, "_http_client", pooled)
    return seen


def _write_toml(root: Path, body: str) -> None:
    (root / ".simplicio-loop").mkdir(exist_ok=True)
    (root / ".simplicio-loop" / "loop.toml").write_text(body, encoding="utf-8")


def _complete(messages, **kwargs):
    return asyncio.run(turbo_provider.complete("a", messages, session_id="s", hedge=0, **kwargs))


def test_a_prompt_under_the_ceiling_is_sent(sent):
    assert _complete(_SMALL)["ok"] and len(sent) == 1


def test_a_prompt_over_the_ceiling_is_not_sent(sent, monkeypatch):
    monkeypatch.setenv(ENV_NAME, "1000")
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def test_the_ceiling_of_loop_toml_applies(sent, repo):
    _write_toml(repo, "%s = 1000\n" % TOML_KEY)
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG, repo_root=repo)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def test_the_loop_toml_of_the_cwd_is_not_the_one_read(sent, repo):
    _write_toml(Path.cwd(), "%s = 1\n" % TOML_KEY)
    assert _complete(_SMALL, repo_root=repo)["ok"] and len(sent) == 1


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


def test_the_ceiling_boundary_refuses_only_above_it(sent, monkeypatch):
    """tokens - 1 refuses with 0 requests; tokens and tokens + 1 send."""
    projected: list[int] = []
    real = turbo_provider.enforce_budget

    def spy(projection, ceiling, *args):
        projected.append(projection.tokens)
        return real(projection, ceiling, *args)

    monkeypatch.setattr(turbo_provider, "enforce_budget", spy)
    assert _complete(_BIG)["ok"] and len(sent) == 1
    tokens = projected[-1]
    sent.clear()
    monkeypatch.setenv(ENV_NAME, str(tokens - 1))
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []
    for ceiling in (tokens, tokens + 1):
        monkeypatch.setenv(ENV_NAME, str(ceiling))
        before = len(sent)
        assert _complete(_BIG)["ok"] and len(sent) == before + 1


def test_the_warm_up_call_is_gated_too(sent, monkeypatch):
    """The 1-token warm-up carries the large header, so it must not skip the gate."""
    monkeypatch.setenv(ENV_NAME, "1000")
    with pytest.raises(turbo_provider.TurboProviderError) as raised:
        _complete(_BIG, max_tokens=1)
    assert raised.value.reason_code == "input_ceiling_exceeded" and sent == []


def _production_complete(monkeypatch, repo, messages_per_call):
    """Run `turbo_cli` in provider mode (the production call shape: functools.partial of turbo_provider.complete) with
    run_turbo replaced by one that sends `messages_per_call` through the `complete` it was given."""
    errors: list[turbo_provider.TurboProviderError] = []

    async def run_turbo(root, tasks, complete, dev_cli=None, scope_for=None):
        for messages in messages_per_call:
            try:
                await complete("simplicio", messages)
            except turbo_provider.TurboProviderError as exc:
                errors.append(exc)
        raise RuntimeError("stop after the model call")

    monkeypatch.setattr(turbo, "run_turbo", run_turbo)
    rc = turbo_cli.run(str(repo), ["write hello.txt"], provider="openrouter")
    return rc, errors


def test_turbo_cli_reads_the_loop_toml_of_its_repo_not_of_the_cwd(sent, monkeypatch, repo, capsys):
    _write_toml(repo, "%s = 1000\n" % TOML_KEY)
    assert Path.cwd().resolve() != repo.resolve()
    rc, errors = _production_complete(monkeypatch, repo, [_BIG])
    assert rc == 2 and [e.reason_code for e in errors] == ["input_ceiling_exceeded"] and sent == []


def test_turbo_cli_fails_loud_on_an_invalid_ceiling_of_its_repo(sent, monkeypatch, repo, capsys):
    _write_toml(repo, '%s = "abc"\n' % TOML_KEY)
    assert Path.cwd().resolve() != repo.resolve()
    rc, errors = _production_complete(monkeypatch, repo, [_SMALL])
    assert rc == 2 and [e.reason_code for e in errors] == ["ceiling_invalid"] and sent == []


def test_turbo_cli_ignores_the_loop_toml_of_the_cwd(sent, monkeypatch, repo, capsys):
    _write_toml(Path.cwd(), "%s = 1\n" % TOML_KEY)
    rc, errors = _production_complete(monkeypatch, repo, [_SMALL])
    assert errors == [] and len(sent) == 1
