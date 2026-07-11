from __future__ import annotations

from simplicio.prompt_envelope import PromptEnvelope


def test_prompt_envelope_records_layers_budgets_and_stable_hashes(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_PROMPT_BUDGET_GOAL", "1")
    envelope = PromptEnvelope.from_layers(
        {"goal": "a long goal", "target": "src/app.py"}, template_version="v1"
    )
    receipt = envelope.receipt()

    assert receipt["schema"] == "simplicio.prompt-envelope/v1"
    assert receipt["prefix_hash"] == envelope.prefix_hash
    assert receipt["context_pack_hash"] == envelope.context_pack_hash
    assert receipt["needs_broader_context"] is True
    assert receipt["cache_eligible"] is False


def test_retry_delta_changes_only_delta_identity() -> None:
    envelope = PromptEnvelope.from_layers({"goal": "fix", "target": "src/app.py"}, template_version="v1")
    retry = envelope.with_retry_delta(
        reason="verification-failed",
        failure_class="assertion",
        diagnostics="expected 200",
        affected_files=["src/app.py"],
    )

    assert retry.prefix_hash == envelope.prefix_hash
    assert retry.delta_hash is not None
    assert retry.receipt()["retry_delta"]["affected_files"] == ["src/app.py"]
