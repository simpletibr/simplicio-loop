import json
import pytest

from simplicio import pipeline, providers, task_operator


def _failed_process(stderr="credit balance exhausted"):
    return task_operator.BoundedRunResult(
        phase=task_operator.PHASE_FAILED,
        elapsed_s=0.1,
        returncode=7,
        stdout="",
        stderr=stderr,
        recovery="child exited",
        label="Codex CLI",
        cmd=["codex", "exec"],
    )


def test_shell_out_maps_credit_exhaustion_to_terminal_receipt(monkeypatch):
    monkeypatch.setattr(task_operator, "run_bounded_subprocess", lambda *args, **kwargs: _failed_process())
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers._shell_out(
            ["codex", "exec"],
            "Codex CLI",
            provider="codex-cli",
            model="gpt-5.6-luna",
            effort="high",
        )
    receipt = error.value.receipt
    assert receipt["schema"] == "simplicio.provider-terminal/v1"
    assert receipt["status"] == "blocked"
    assert receipt["reason_code"] == "provider_capacity_unavailable"
    assert receipt["provider"] == "codex-cli"
    assert receipt["model"] == "gpt-5.6-luna"
    assert receipt["effort"] == "high"
    assert receipt["duration_ms"] >= 0


def test_shell_out_maps_silent_child_exit_without_fabricating_success(monkeypatch):
    monkeypatch.setattr(task_operator, "run_bounded_subprocess", lambda *args, **kwargs: _failed_process(stderr=""))
    with pytest.raises(providers.ProviderExecutionError) as error:
        providers._shell_out(["codex", "exec"], "Codex CLI", provider="codex-cli")
    assert error.value.receipt["reason_code"] == "provider_child_exit_silent"
    assert error.value.receipt["status"] == "failed"


def test_pipeline_emits_terminal_and_returns_without_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "python -c pass")
    monkeypatch.setenv("SIMPLICIO_MODEL", "codex-cli/gpt-5.6-luna")
    (tmp_path / "app.py").write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")

    def fail_generate(*args, **kwargs):
        raise providers.ProviderExecutionError({
            "schema": "simplicio.provider-terminal/v1",
            "status": "blocked",
            "reason_code": "provider_capacity_unavailable",
            "message": "provider capacity unavailable",
            "provider": "codex-cli",
            "model": "gpt-5.6-luna",
            "effort": "high",
        })

    monkeypatch.setattr(pipeline, "generate", fail_generate)
    result = pipeline.run_task(
        str(tmp_path), "python", "change app", "app.py", "- keep behavior", "", quiet=True
    )
    assert result["status"] == "blocked"
    assert result["applied"] is False
    assert result["provider_terminal"]["reason_code"] == "provider_capacity_unavailable"
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "old\n"
    events = [
        json.loads(line)
        for line in (tmp_path / ".simplicio" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["event"] for event in events] == [
        "task_start", "task_progress", "provider_terminal", "task_terminal"
    ]
