"""The explicit OpenRouter worker must reserve a usable completion budget.

The pinned reasoning model (`deepseek/deepseek-v4.1-flash`) exposes hidden
reasoning inside the completion budget.  A request that leaves too little room
returns an empty `content` with `finish_reason == "length"`, which the worker
previously reported as a generic invalid response.  These tests pin the two
contracts that make the failure actionable and the delivery possible:

* the request spends no budget on hidden reasoning and always reserves a
  realistic completion window;
* a truncated response is classified as truncation, not as an unknown schema
  failure, so the block names its cause.
"""

import json

import pytest

from simplicio_loop import provider_worker


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        from io import BytesIO

        return BytesIO(self._payload)

    def __exit__(self, *_args):
        return False


def _env(**extra):
    env = {
        "OPENROUTER_API_KEY": "runtime-only-openrouter-secret",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }
    env.update(extra)
    return env


def _dispatch(opener, *, env=None):
    return provider_worker.OpenRouterWorker(opener=opener).dispatch(
        task={"id": "TASK-CHECKERS-001", "goal": "create the game"},
        context={"mapper_generation": "generation-1"},
        run_id="run-1",
        task_index=1,
        allowed_paths=("site/checkers.html",),
        env=_env(**(env or {})),
    )


def test_request_reserves_completion_budget_and_spends_none_on_hidden_reasoning():
    captured = {}

    def opener(request, *, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"files": {"site/checkers.html": "<html></html>"}}
                            )
                        },
                    }
                ]
            }
        )

    _dispatch(opener)

    payload = captured["payload"]
    assert payload["reasoning"] == {"enabled": False}
    assert payload["max_tokens"] >= 8192


def test_truncated_response_is_reported_as_truncation_with_the_budget():
    def opener(_request, *, timeout):
        return _Response(
            {
                "choices": [{"finish_reason": "length", "message": {"content": None}}],
                "usage": {"prompt_tokens": 107, "completion_tokens": 2048},
            }
        )

    with pytest.raises(provider_worker.ProviderWorkerError) as error:
        _dispatch(opener)

    assert error.value.reason_code == "provider_response_truncated"
    assert "2048" in str(error.value)


def test_max_tokens_override_is_honoured_when_positive_and_bounded():
    captured = {}

    def opener(request, *, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {"files": {"site/checkers.html": "<html></html>"}}
                            )
                        },
                    }
                ]
            }
        )

    _dispatch(opener, env={"SIMPLICIO_OPENROUTER_MAX_TOKENS": "24576"})
    assert captured["payload"]["max_tokens"] == 24576

    _dispatch(opener, env={"SIMPLICIO_OPENROUTER_MAX_TOKENS": "not-a-number"})
    assert captured["payload"]["max_tokens"] == provider_worker.OPENROUTER_MAX_TOKENS

    _dispatch(opener, env={"SIMPLICIO_OPENROUTER_MAX_TOKENS": "16"})
    assert captured["payload"]["max_tokens"] == provider_worker.OPENROUTER_MAX_TOKENS
