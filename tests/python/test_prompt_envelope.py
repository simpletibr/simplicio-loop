from __future__ import annotations

from simplicio.prompt_envelope import PromptEnvelope


def test_prompt_envelope_records_layers_budgets_and_stable_hashes(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PROMPT_BUDGET_GOAL", "1")
    monkeypatch.setenv("SIMPLICIO_PROMPT_TASK_CLASS", "review")
    monkeypatch.setenv("SIMPLICIO_MODEL_CONTEXT_WINDOW", "16384")
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5.4-medium")
    envelope = PromptEnvelope.from_layers(
        {"goal": "a long goal", "target": "src/app.py"}, template_version="v1"
    )
    receipt = envelope.receipt()

    assert receipt["schema"] == "simplicio.prompt-envelope/v1"
    assert receipt["prefix_hash"] == envelope.prefix_hash
    assert receipt["context_pack_hash"] == envelope.context_pack_hash
    assert receipt["task_class"] == "review"
    assert receipt["context_window"] == 16384
    assert receipt["provider"] == "codex-cli"
    assert receipt["model"] == "codex-cli/gpt-5.4-medium"
    assert receipt["needs_broader_context"] is True
    assert receipt["cache_eligible"] is False
    goal_layer = next(row for row in receipt["layers"] if row["layer"] == "goal")
    assert goal_layer["effective_budget"] == 1
    assert goal_layer["budget_source"] == "env"
    assert goal_layer["truncation"] == "needs_broader_context"


def test_prompt_envelope_orders_layers_deterministically_and_scales_profile_budget(monkeypatch) -> None:
    monkeypatch.delenv("SIMPLICIO_PROMPT_TASK_CLASS", raising=False)
    monkeypatch.setenv("SIMPLICIO_MODEL_CONTEXT_WINDOW", "16384")

    envelope = PromptEnvelope.from_layers(
        {
            "constraints": "keep it safe",
            "goal": "fix bug",
            "policy": "policy block",
            "target": "src/app.py",
            "skill": "python skill",
        },
        template_version="v1",
        task_class="diagnosis",
    )
    receipt = envelope.receipt()

    assert receipt["immutable_prefix"]["layers"] == ["policy", "goal", "target", "skill", "constraints"]
    target_layer = next(row for row in receipt["layers"] if row["layer"] == "target")
    assert target_layer["effective_budget"] == 4400
    assert target_layer["budget_source"] == "profile"


def test_retry_delta_changes_only_delta_identity_and_redacts_receipt() -> None:
    envelope = PromptEnvelope.from_layers(
        {"goal": "fix", "target": "src/app.py", "policy": "stay within contract"},
        template_version="v1",
    )
    retry = envelope.with_retry_delta(
        reason="verification-failed",
        failure_class="assertion",
        diagnostics="expected 200 but got 500",
        affected_files=["src/app.py"],
    )

    assert retry.prefix_hash == envelope.prefix_hash
    assert retry.delta_hash is not None
    assert envelope.render() not in retry.render_retry_delta()
    receipt = retry.receipt()["retry_delta"]
    assert receipt["schema"] == "simplicio.prompt-retry-delta/v1"
    assert receipt["affected_files"] == ["src/app.py"]
    assert receipt["diagnostics_excerpt"] == "expected 200 but got 500"
