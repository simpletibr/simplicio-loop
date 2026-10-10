"""The OpenRouter worker does not send a request above the input-token ceiling (#1608, part C)."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from simplicio_loop import provider_worker
from simplicio_loop.input_ceiling import ENV_NAME, TOML_KEY


class _Response:
    def __enter__(self):
        body = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"files": {"a.txt": "x"}})}}]}
        return BytesIO(json.dumps(body).encode("utf-8"))

    def __exit__(self, *_args):
        return False


def _dispatch(opener, tmp_path, *, goal="create the file", **env):
    environ = {"OPENROUTER_API_KEY": "runtime-only-secret", **env}
    return provider_worker.OpenRouterWorker(opener=opener).dispatch(
        task={"id": "T-1", "goal": goal}, context={"mapper_generation": "g1"}, run_id="run-1", task_index=1,
        allowed_paths=("a.txt",), env=environ, repo_root=tmp_path)


def _counting_opener():
    calls = []

    def opener(request, *, timeout):
        calls.append(request)
        return _Response()

    return opener, calls


def test_a_prompt_under_the_ceiling_is_sent_and_labelled_estimated(tmp_path):
    opener, calls = _counting_opener()
    result = _dispatch(opener, tmp_path)
    assert len(calls) == 1
    budget = result["input_budget"]
    assert budget["basis"] == "ESTIMATED" and budget["ceiling"] == 98_000 and budget["status"] == "ok"


def test_a_prompt_over_the_ceiling_is_not_sent(tmp_path):
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, tmp_path, goal="word " * 5000, **{ENV_NAME: "1000"})
    assert raised.value.reason_code == "input_ceiling_exceeded"
    assert calls == []


def test_the_ceiling_of_loop_toml_applies(tmp_path):
    (tmp_path / ".simplicio-loop").mkdir()
    (tmp_path / ".simplicio-loop" / "loop.toml").write_text("%s = 1000\n" % TOML_KEY, encoding="utf-8")
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, tmp_path, goal="word " * 5000)
    assert raised.value.reason_code == "input_ceiling_exceeded" and calls == []


def test_a_bad_ceiling_fails_loud_without_sending(tmp_path):
    opener, calls = _counting_opener()
    with pytest.raises(provider_worker.ProviderWorkerError) as raised:
        _dispatch(opener, tmp_path, **{ENV_NAME: "abc"})
    assert raised.value.reason_code == "ceiling_invalid" and calls == []
