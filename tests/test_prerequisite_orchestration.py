import json
from pathlib import Path

import pytest

from simplicio_loop import cli_impl, provider_worker, runner


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        from io import BytesIO

        return BytesIO(self._payload)

    def __exit__(self, *_args):
        return False


def _provider_response(*, usage=None):
    response = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": json.dumps({"files": {"site/checkers.html": "<html></html>"}})},
        }],
    }
    if usage is not None:
        response["usage"] = usage
    return response


def test_openrouter_worker_pins_model_for_real_request_and_keeps_usage_unknown_distinct_from_zero():
    captured = {}

    def opener(request, *, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _Response(_provider_response())

    secret = "runtime-only-openrouter-secret"
    result = provider_worker.OpenRouterWorker(opener=opener).dispatch(
        task={"id": "TASK-CHECKERS-001", "goal": "create the game"},
        context={"mapper_generation": "generation-1"},
        run_id="run-1",
        task_index=1,
        allowed_paths=("site/checkers.html",),
        env={
            "OPENROUTER_API_KEY": secret,
            "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        },
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == f"Bearer {secret}"
    assert captured["payload"]["model"] == "deepseek/deepseek-v4.1-flash"
    assert captured["payload"]["temperature"] == 0
    assert result["usage"] is None
    assert result["usage_status"] == "unknown"
    assert result["input_tokens"] is None
    assert result["output_tokens"] is None
    assert secret not in json.dumps(result, sort_keys=True)


def test_openrouter_worker_preserves_observed_zero_usage_as_measured():
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    result = provider_worker.OpenRouterWorker(
        opener=lambda _request, *, timeout: _Response(_provider_response(usage=usage))
    ).dispatch(
        task={"id": "TASK-CHECKERS-001"},
        context={},
        run_id="run-1",
        task_index=1,
        allowed_paths=("site/checkers.html",),
        env={"OPENROUTER_API_KEY": "runtime-only-openrouter-secret"},
    )

    assert result["usage"] == usage
    assert result["usage_status"] == "measured"
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0


def test_openrouter_worker_forwards_only_authorized_environment_values():
    forwarded = provider_worker.forwarded_environment({
        "OPENROUTER_API_KEY": "runtime-only-openrouter-secret",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "SIMPLICIO_MODEL": "must-not-be-forwarded",
        "AWS_SECRET_ACCESS_KEY": "must-not-be-forwarded",
    })

    assert forwarded == {
        "OPENROUTER_API_KEY": "runtime-only-openrouter-secret",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    }


def test_openrouter_worker_rejects_unauthorized_proposal_path_before_plan_creation(tmp_path):
    proposal = {"files": {"outside.txt": "not authorized"}}

    with pytest.raises(provider_worker.ProviderWorkerError, match="outside authorized paths"):
        provider_worker.proposal_to_mechanical_plan(
            proposal,
            root=tmp_path,
            allowed_paths=("site/checkers.html",),
        )


def test_provider_worker_failure_is_fail_closed_and_never_selects_deterministic_fallback(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise provider_worker.ProviderWorkerError("provider transport failed", reason_code="provider_failed")

    monkeypatch.setattr(provider_worker.OpenRouterWorker, "dispatch", fail)

    with pytest.raises(provider_worker.ProviderWorkerError, match="provider transport failed"):
        runner._provider_worker_plan(
            task={"id": "TASK-CHECKERS-001", "goal": "create"},
            context={},
            run_id="run-1",
            task_index=1,
            attempt=1,
            root=tmp_path,
            allowed_paths=("site/checkers.html",),
            run_dir=tmp_path / "run",
            provider_worker="openrouter",
        )

    assert not list(tmp_path.rglob("mechanical-plan*.json"))


def test_deterministic_dev_cli_environment_does_not_receive_provider_key(tmp_path):
    env = runner._devcli_env(
        tmp_path,
        {
            "OPENROUTER_API_KEY": "runtime-only-openrouter-secret",
            "SIMPLICIO_MODEL": "codex-cli/gpt-5.4",
        },
    )

    assert "OPENROUTER_API_KEY" not in env
    assert env["SIMPLICIO_MODEL"] == "codex-cli/gpt-5.4"


def test_public_prepare_arms_a_run_without_executing_it(monkeypatch, capsys):
    calls = []

    def fake_arm(repo, task, delivery, max_iterations):
        calls.append((repo, task, delivery, max_iterations))
        return {
            "manifest": {"run_id": "run-prepared"},
            "state": {"phase": "awaiting_decision"},
            "run_dir": "/tmp/run-prepared",
        }

    monkeypatch.setattr(cli_impl, "arm_run", fake_arm)
    monkeypatch.setattr(cli_impl, "conduct_run", lambda *_args, **_kwargs: pytest.fail("execution started"))

    assert cli_impl.prepare("repo", "tasks.md", "verified", 12) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls == [("repo", "tasks.md", "verified", 12)]
    assert payload["run_id"] == "run-prepared"
    assert payload["execution_started"] is False
    assert payload["mutation_attempted"] is False


def test_dispatch_orders_dependent_tasks_before_dependents_even_when_input_is_reversed():
    items = [
        {"task_id": "TASK-CHECKERS-002", "task_index": 2, "task_spec": {"depends_on": ["TASK-CHECKERS-001"]}},
        {"task_id": "TASK-CHECKERS-001", "task_index": 1, "task_spec": {}},
    ]

    ordered = runner._ordered_dispatch_items(items)

    assert [item["task_id"] for item in ordered] == ["TASK-CHECKERS-001", "TASK-CHECKERS-002"]


def test_batch_omits_completed_predecessor_that_is_outside_the_current_indices():
    items = [
        {
            "task_id": "run-1-task-2",
            "task_index": 2,
            "task_spec": {"depends_on": ["TASK-CHECKERS-001"]},
        },
    ]

    filtered = runner._omit_satisfied_dispatch_dependencies(
        items,
        satisfied_aliases={"TASK-CHECKERS-001", "1", "task-1", "run-1-task-1"},
    )
    ordered = runner._ordered_dispatch_items(filtered)

    assert [item["task_id"] for item in ordered] == ["run-1-task-2"]
    assert filtered[0]["task_spec"]["depends_on"] == []


def test_public_batch_wave_and_prism_forward_explicit_provider_worker(monkeypatch):
    calls = []

    def fake_batch(repo, run_id, indices, **kwargs):
        calls.append((repo, run_id, indices, kwargs))
        return {"status": "completed", "workers": []}

    monkeypatch.setattr(cli_impl, "execute_operator_batch", fake_batch)

    for mode in ("batch", "wave", "prism"):
        assert cli_impl.batch(
            "repo", "run-1", "1,2", 0, 3, False, None, provider_worker="openrouter"
        ) == 2

    assert len(calls) == 3
    assert all(call[3]["provider_worker"] == "openrouter" for call in calls)


def test_prepare_plan_converts_provider_proposal_to_dev_cli_mechanical_plan(tmp_path):
    target = tmp_path / "site" / "checkers.html"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")

    plan = provider_worker.proposal_to_mechanical_plan(
        {"files": {"site/checkers.html": "new\n"}},
        root=tmp_path,
        allowed_paths=("site/checkers.html",),
    )

    assert plan["schema"] == "simplicio.mechanical-edit/v1"
    assert plan["touched_files"] == ["site/checkers.html"]
    assert plan["operations"][0]["op"] == "replace_range"
    assert plan["operations"][0]["text"] == "new\n"


def test_retry_after_independent_verification_forwards_detail_to_next_provider_dispatch(monkeypatch, tmp_path):
    prompts = []
    verifier_detail = "independent verifier: expected Turn: Black but observed Turn: Red"

    def opener(request, *, timeout):
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        prompts.append(payload["messages"][0]["content"])
        if len(prompts) == 2 and verifier_detail not in prompts[-1]:
            return _Response({"choices": []})
        return _Response(_provider_response())

    class _FakeWorker:
        def __init__(self):
            self._worker = provider_worker.OpenRouterWorker(opener=opener)

        def dispatch(self, **kwargs):
            return self._worker.dispatch(**kwargs)

    def fake_execute(repo, run_id, task_index, **kwargs):
        del repo
        assert kwargs["provider_worker"] == "openrouter"
        feedback = kwargs.get("repair_feedback")
        runner._provider_worker_plan(
            task={"id": "TASK-CHECKERS-001", "goal": "repair the game"},
            context={"mapper_generation": "generation-1"},
            run_id=run_id,
            task_index=task_index,
            attempt=1,
            root=tmp_path,
            allowed_paths=("site/checkers.html",),
            run_dir=tmp_path / "provider-run",
            provider_worker=kwargs["provider_worker"],
            repair_feedback=feedback,
        )
        return {
            "run_dir": str(tmp_path),
            "state": {
                "phase": "validating",
                "attempts": 1,
                "operator": {"execution_state": "applied", "receipt": ""},
            },
        }

    verification_results = iter([
        {"verified": False, "reason": verifier_detail},
        {"verified": True, "status": "VERIFIED"},
    ])
    (tmp_path / "provider-run").mkdir()
    monkeypatch.setenv("OPENROUTER_API_KEY", "runtime-only-openrouter-secret")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(runner, "OpenRouterWorker", _FakeWorker)
    monkeypatch.setattr(runner, "execute_operator", fake_execute)
    monkeypatch.setattr(runner, "_verified_delivery_gate_enabled", lambda: True)
    monkeypatch.setattr(
        runner,
        "_run_verified_delivery_gate",
        lambda **_kwargs: next(verification_results),
    )
    attempts = runner._run_operator_item_process(
        {
            "repo": str(tmp_path),
            "run_id": "run-1",
            "task_index": 1,
            "worker_id": "worker-1",
            "task_id": "task-1",
            "provider_worker": "openrouter",
        },
        retry_budget=1,
    )

    assert [attempt["status"] for attempt in attempts] == ["failed", "succeeded"]
    assert len(prompts) == 2
    assert verifier_detail not in prompts[0]
    assert verifier_detail in prompts[1]


def test_failed_independent_watcher_preserves_concrete_detail_for_repair_feedback(tmp_path):
    detail = "FAIL - board exposes 4 cells; observed role=list"
    watcher_receipt = tmp_path / "watcher-state.json"
    watcher_receipt.write_text(json.dumps({
        "status": "UNVERIFIED",
        "match": False,
        "reported": detail,
    }), encoding="utf-8")

    result = runner._run_verified_delivery_gate(
        run_id="run-1",
        task_id="task-1",
        actor="loop",
        attempt_id="attempt-1",
        receipt_verdict={"status": "VERIFIED"},
        evidence_receipt="",
        watcher_receipt=str(watcher_receipt),
        merge=None,
        worktree_context={},
    )

    assert result["verified"] is False
    assert detail in result["reason"]


def test_provider_worker_receives_current_authorized_target_for_editing_task(monkeypatch, tmp_path):
    target = tmp_path / "site" / "checkers.html"
    target.parent.mkdir()
    current = "<html><body>existing game</body></html>\n"
    target.write_text(current, encoding="utf-8")
    captured = {}

    class _FakeWorker:
        def dispatch(self, **kwargs):
            captured["context"] = kwargs["context"]
            return {
                "proposal": {"files": {"site/checkers.html": current + "<!-- changed -->\n"}},
                "response_sha256": "response-hash",
                "provider_call_count": 1,
                "usage": None,
                "usage_status": "unknown",
                "input_tokens": None,
                "output_tokens": None,
                "cached_tokens": None,
                "reasoning_tokens": None,
                "cost": None,
                "cost_status": "unknown",
            }

    monkeypatch.setenv("OPENROUTER_API_KEY", "runtime-only-openrouter-secret")
    monkeypatch.setattr(runner, "OpenRouterWorker", _FakeWorker)
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    runner._provider_worker_plan(
        task={"id": "TASK-CHECKERS-002", "type": "editing"},
        context={"mapper_generation": "generation-1"},
        run_id="run-1",
        task_index=2,
        attempt=1,
        root=tmp_path,
        allowed_paths=("site/checkers.html",),
        run_dir=run_dir,
        provider_worker="openrouter",
    )

    assert captured["context"]["current_targets"] == {"site/checkers.html": current}
