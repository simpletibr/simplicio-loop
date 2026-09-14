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


def _dispatch(opener, *, env=None, repair_feedback=None):
    kwargs = {
        "task": {"id": "TASK-CHECKERS-001", "goal": "create the game"},
        "context": {"mapper_generation": "generation-1"},
        "run_id": "run-1",
        "task_index": 1,
        "allowed_paths": ("site/checkers.html",),
        "env": _env(**(env or {})),
    }
    if repair_feedback is not None:
        kwargs["repair_feedback"] = repair_feedback
    return provider_worker.OpenRouterWorker(opener=opener).dispatch(
        **kwargs,
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


def test_no_feedback_prompt_is_byte_identical_to_the_existing_prompt():
    task = {"id": "TASK-CHECKERS-001", "goal": "create the game"}
    context = {"mapper_generation": "generation-1"}
    expected = (
        "You are an explicitly authorized external coding worker. You are not an execution authority. "
        "Return only a JSON object with a non-empty top-level `files` object mapping authorized relative "
        "paths to complete UTF-8 file contents. Do not claim that changes were applied or verified. "
        "Do not return markdown fences or any path outside the authorized targets.\n\n"
        "Task:\n"
        '{"goal": "create the game", "id": "TASK-CHECKERS-001"}\n\n'
        "Mapper context:\n"
        '{"mapper_generation": "generation-1"}'
        "\n\nAccessible HTML game contract:\n"
        + provider_worker.ACCESSIBLE_HTML_GAME_CONTRACT
    )

    assert provider_worker._request_prompt(task, context) == expected
    assert provider_worker._request_prompt(task, context, repair_feedback=None) == expected
    assert provider_worker._request_prompt(task, context, repair_feedback="") == expected
    assert "Start game" in expected
    assert "Turn: Black" in expected
    assert "Checkers board" in expected


def test_repair_feedback_is_forwarded_bounded_and_secret_html_free():
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

    detail = "independent verifier: expected Turn: Black but observed Turn: Red"
    _dispatch(opener, repair_feedback=detail)
    prompt = captured["payload"]["messages"][0]["content"]
    assert detail in prompt

    fixture_value = "repair-feedback-openrouter-secret-123456"
    secret_field = "api" + "_key"
    unsafe = f"{detail}; {secret_field}={fixture_value}\n<html><body>raw proposal</body></html>"
    _dispatch(opener, repair_feedback=unsafe)
    prompt = captured["payload"]["messages"][0]["content"]
    assert fixture_value not in prompt
    assert "<html><body>raw proposal</body></html>" not in prompt
    assert len(prompt) <= (
        len(provider_worker._request_prompt(
            {"id": "TASK-CHECKERS-001", "goal": "create the game"},
            {"mapper_generation": "generation-1"},
        )) + provider_worker.MAX_REPAIR_FEEDBACK_CHARS + 128
    )

    long_detail = "verifier detail: " + ("x" * (provider_worker.MAX_REPAIR_FEEDBACK_CHARS + 100))
    _dispatch(opener, repair_feedback=long_detail)
    prompt = captured["payload"]["messages"][0]["content"]
    assert prompt.endswith(long_detail[:provider_worker.MAX_REPAIR_FEEDBACK_CHARS])


def test_request_prompt_includes_current_targets_and_accessible_game_contract():
    current = "<!DOCTYPE html><html><body>existing game</body></html>"
    prompt = provider_worker._request_prompt(
        {"id": "TASK-CHECKERS-002", "goal": "edit the game"},
        {
            "mapper_generation": "generation-1",
            "current_targets": {"site/checkers.html": current},
        },
    )

    assert current in prompt
    assert "Start game" in prompt
    assert "Turn: Black" in prompt
    assert "Simplicio" in prompt
    assert "Checkers board" in prompt
    assert "Reset game" in prompt
    assert "Score:" in prompt
