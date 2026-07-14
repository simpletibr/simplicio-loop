from __future__ import annotations

from types import SimpleNamespace

from simplicio import prompt as prompt_module
from simplicio.pipeline import IMPACT_RESULT_NOT_NEEDED, run_task
from simplicio.prompt_envelope import PromptEnvelope


def test_run_task_reuses_stable_prefix_and_sends_only_retry_delta(monkeypatch, tmp_path):
    envelope = PromptEnvelope.from_layers(
        {"policy": "policy", "goal": "fix bug", "target": "src/app.py"},
        template_version="v1",
    )
    monkeypatch.setattr(prompt_module, "_LAST_PROMPT_ENVELOPE", envelope)
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *args, **kwargs: "BASE PROMPT")
    monkeypatch.setattr("simplicio.pipeline.MAX_ATTEMPTS", 2)
    monkeypatch.setattr(
        "simplicio.pipeline.validate_generated_output",
        lambda *args, **kwargs: SimpleNamespace(ok=True, reason=""),
    )
    # run_task fails closed with "verification command missing" unless
    # SIMPLICIO_TEST_CMD is set — it reads the env var directly, there is no
    # _configured_test_command hook (this monkeypatch was a no-op vestige of
    # an older implementation).
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr("simplicio.pipeline.log_run", lambda *args, **kwargs: None)
    monkeypatch.setattr("simplicio.pipeline.emit_event", lambda *args, **kwargs: None)

    calls: list[tuple[str, str | None]] = []

    def fake_generate(prompt: str, feedback: str | None = None):
        calls.append((prompt, feedback))
        return "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"

    outcomes = iter([(False, "AssertionError: boom"), (True, "")])
    monkeypatch.setattr("simplicio.pipeline.generate", fake_generate)
    monkeypatch.setattr("simplicio.pipeline._apply_and_test", lambda *args, **kwargs: next(outcomes))
    monkeypatch.setattr(
        "simplicio.pipeline._run_impact_tests",
        lambda *args, **kwargs: {
            "result": IMPACT_RESULT_NOT_NEEDED,
            "status": "no_changed_files",
            "callers": [],
            "tests_run": [],
        },
    )

    result = run_task(tmp_path, "python", "fix bug", "src/app.py", "", "", quiet=True)

    assert len(calls) == 2
    assert calls[0] == ("BASE PROMPT", None)
    assert calls[1][0] == "BASE PROMPT"
    assert calls[1][1] is not None
    assert "Retry delta:" in calls[1][1]
    assert "BASE PROMPT" not in calls[1][1]
    assert result["prompt_envelope"]["retry_delta"]["affected_files"] == ["src/app.py"]
