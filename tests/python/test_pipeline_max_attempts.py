"""Pin `pipeline.run_task`'s attempt budget and its external opt-out.

Issue #166 ("Retry global, feature/sprint scheduler e operational memory
deixam de ter dois owners ativos") flags `pipeline.run_task`'s internal
retry loop as a genuine double-retry risk when invoked from a host loop
that already owns retry policy (e.g. simplicio-loop): before this slice,
`MAX_ATTEMPTS` was hardcoded with no lever for such a caller to request a
single atomic attempt. See docs/plan-compiler.md#control-plane-ownership-
inventory-retry--feature-sprint-scheduling for the full inventory.

These tests pin:
  1. The unchanged default (`MAX_ATTEMPTS == 5`, no env set) as a regression
     guard — if this drifts, it's exactly the kind of duplication risk this
     doc is meant to catch.
  2. `SIMPLICIO_MAX_ATTEMPTS=1` makes `run_task` perform exactly one
     generate/apply/test attempt regardless of `MAX_ATTEMPTS`.
  3. Invalid/unset `SIMPLICIO_MAX_ATTEMPTS` falls back to `MAX_ATTEMPTS`
     unchanged (fail-safe default, not a silent behavior change).
"""

from __future__ import annotations

from types import SimpleNamespace

from simplicio import pipeline
from simplicio.pipeline import IMPACT_RESULT_NOT_NEEDED, run_task


def test_max_attempts_default_is_five_when_env_unset(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_MAX_ATTEMPTS", raising=False)
    assert pipeline.MAX_ATTEMPTS == 5
    assert pipeline._resolve_max_attempts() == 5


def test_resolve_max_attempts_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "not-a-number")
    assert pipeline._resolve_max_attempts() == pipeline.MAX_ATTEMPTS
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "0")
    assert pipeline._resolve_max_attempts() == pipeline.MAX_ATTEMPTS
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "-1")
    assert pipeline._resolve_max_attempts() == pipeline.MAX_ATTEMPTS


def test_resolve_max_attempts_honors_env_override(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "1")
    assert pipeline._resolve_max_attempts() == 1
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "9")
    assert pipeline._resolve_max_attempts() == 9


def _fake_apply_and_test_always_fails(*_args, **_kwargs):
    return False, "AssertionError: boom"


def test_run_task_makes_a_single_attempt_when_opted_out(monkeypatch, tmp_path):
    """A caller that already owns retry policy can force exactly one
    generate/apply/test attempt via SIMPLICIO_MAX_ATTEMPTS=1, even though
    every attempt fails and MAX_ATTEMPTS (unchanged) would otherwise retry."""

    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "1")
    monkeypatch.setattr("simplicio.pipeline.build_prompt", lambda *args, **kwargs: "BASE PROMPT")
    monkeypatch.setattr(
        "simplicio.pipeline.validate_generated_output",
        lambda *args, **kwargs: SimpleNamespace(ok=True, reason=""),
    )
    monkeypatch.setattr(
        "simplicio.pipeline._configured_test_command", lambda: ("pytest -q", None), raising=False
    )
    monkeypatch.setattr("simplicio.pipeline.log_run", lambda *args, **kwargs: None)
    monkeypatch.setattr("simplicio.pipeline.emit_event", lambda *args, **kwargs: None)
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")

    calls: list[str] = []

    def fake_generate(prompt: str, feedback: str | None = None):
        calls.append(prompt)
        return "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"

    monkeypatch.setattr("simplicio.pipeline.generate", fake_generate)
    monkeypatch.setattr("simplicio.pipeline._apply_and_test", _fake_apply_and_test_always_fails)
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

    assert len(calls) == 1
    assert result["applied"] is False
