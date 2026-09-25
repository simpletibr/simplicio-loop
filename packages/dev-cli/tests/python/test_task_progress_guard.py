"""Tests for issue #219: observable/cancelable task attempts on no-progress.

Issue #210 already bounded the *provider shell-out sub-call* itself
(heartbeats, startup-vs-total timeout, process-tree kill, cooperative
cancellation) inside ``providers._shell_out`` / ``task_operator``. Issue #219
closes the remaining gaps ABOVE that layer, in ``pipeline.run_task``'s
attempt loop itself:

- AC1/AC2: a stall that bubbles up from ``generate()`` as ``SystemExit``
  (exactly what #210's bounded provider call raises on timeout/cancel) used
  to propagate all the way out of ``run_task`` uncaught — crashing the whole
  ``simplicio-py task`` invocation with no terminal receipt at all. It is now
  caught and turned into a terminal ``applied=False`` receipt with an
  explicit reason (``status="stalled"``). A configurable whole-task deadline
  (``SIMPLICIO_TASK_DEADLINE_S``, opt-in, disabled by default) gives the same
  terminal-receipt treatment when attempts complete but the task as a whole
  is taking too long.
- AC4: the bound-path validator (``pipeline_stages.validate_generated_
  output``) now rejects a diff that deletes ~all of a pre-existing, single
  bound-path file — a destructive full-file replacement — instead of only
  checking whether the diff *mentions* an out-of-scope path.
- AC5: the retry loop now escalates its feedback once the same failure
  fingerprint (classification + log content) repeats across consecutive
  attempts, instead of silently resubmitting near-identical guidance.
"""

from __future__ import annotations

import sys

from simplicio import pipeline, pipeline_stages
from simplicio.pipeline_fixers import FixerResult

# ---------------------------------------------------------------------------
# AC1/AC2 — helpers
# ---------------------------------------------------------------------------


def test_task_deadline_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TASK_DEADLINE_S", raising=False)
    assert pipeline._task_deadline_s() == 0.0


def test_task_deadline_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TASK_DEADLINE_S", "not-a-number")
    assert pipeline._task_deadline_s() == 0.0
    monkeypatch.setenv("SIMPLICIO_TASK_DEADLINE_S", "-5")
    assert pipeline._task_deadline_s() == 0.0
    monkeypatch.setenv("SIMPLICIO_TASK_DEADLINE_S", "0")
    assert pipeline._task_deadline_s() == 0.0


def test_task_deadline_honors_env_override(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TASK_DEADLINE_S", "42")
    assert pipeline._task_deadline_s() == 42.0


def test_retry_escalation_after_defaults_to_two(monkeypatch):
    monkeypatch.delenv("SIMPLICIO_RETRY_ESCALATION_AFTER", raising=False)
    assert pipeline._retry_escalation_after() == 2


def test_retry_escalation_after_honors_env_override(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_RETRY_ESCALATION_AFTER", "3")
    assert pipeline._retry_escalation_after() == 3
    monkeypatch.setenv("SIMPLICIO_RETRY_ESCALATION_AFTER", "not-a-number")
    assert pipeline._retry_escalation_after() == 2
    monkeypatch.setenv("SIMPLICIO_RETRY_ESCALATION_AFTER", "0")
    assert pipeline._retry_escalation_after() == 2


def test_failure_fingerprint_is_stable_for_identical_logs():
    assert pipeline._failure_fingerprint("AssertionError: boom") == pipeline._failure_fingerprint(
        "AssertionError: boom"
    )


def test_failure_fingerprint_differs_for_different_logs():
    assert pipeline._failure_fingerprint("AssertionError: boom") != pipeline._failure_fingerprint(
        "SyntaxError: nope"
    )


# ---------------------------------------------------------------------------
# AC2 — a provider stall (SystemExit from generate()) yields a terminal
# receipt instead of crashing run_task.
# ---------------------------------------------------------------------------


def test_run_task_turns_provider_stall_into_terminal_receipt_instead_of_crashing(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")

    events = []

    def fake_generate(prompt, feedback=None):
        raise SystemExit(
            "simplicio: Codex CLI (`codex exec`) never started producing output "
            "(>30s startup deadline). No provider output arrived before the startup deadline."
        )

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        pipeline,
        "emit_event",
        lambda event_type, payload, **kwargs: events.append((event_type, payload, kwargs)),
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- behavior proven",
        "- keep compatibility",
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "stalled"
    assert "startup deadline" in result["warnings"][0]
    # Never applied anything to the real worktree.
    assert target.read_text(encoding="utf-8") == "old\n"
    stall_events = [payload for name, payload, _ in events if name == "task_no_progress"]
    assert stall_events, "expected a task_no_progress event for the stalled provider call"
    assert stall_events[0]["attempt"] == 1


def test_run_task_stops_at_configured_task_deadline(tmp_path, monkeypatch):
    """A configured SIMPLICIO_TASK_DEADLINE_S stops the loop with a terminal
    'stalled' receipt before burning through every remaining attempt, even
    though each individual attempt fails quickly (no per-attempt stall)."""

    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setenv("SIMPLICIO_TASK_DEADLINE_S", "10")
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")

    # Fake a monotonic clock that jumps well past the 10s deadline on the
    # second call (task start + attempt-1 heartbeat), so attempt 2 never
    # reaches generate().
    clock = iter([0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0])

    def fake_monotonic():
        try:
            return next(clock)
        except StopIteration:
            return 100.0

    monkeypatch.setattr(pipeline.time, "monotonic", fake_monotonic)

    generate_calls = []

    def fake_generate(prompt, feedback=None):
        generate_calls.append(feedback)
        return "not a diff at all"

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "prompt")

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- behavior proven",
        "- keep compatibility",
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "stalled"
    assert "deadline" in result["warnings"][0]
    # Exactly one attempt was allowed to call generate() before the deadline
    # check on the second loop iteration stopped the task.
    assert len(generate_calls) == 1


# ---------------------------------------------------------------------------
# AC5 — retry escalation after repeated identical failures.
# ---------------------------------------------------------------------------


def test_run_task_escalates_feedback_after_repeated_identical_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")

    feedbacks = []

    def fake_generate(prompt, feedback=None):
        feedbacks.append(feedback)
        # Never a valid diff — every attempt fails identically (same
        # validation-failure classification/log every time).
        return "no diff here, sorry"

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        pipeline,
        "try_static_fixers",
        lambda *a, **k: FixerResult("none", False, "no static fixer matched"),
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- behavior proven",
        "- keep compatibility",
        quiet=True,
    )

    assert result["applied"] is False
    # MAX_ATTEMPTS default is 5; feedbacks[0] is None (first attempt), and by
    # the default escalation threshold (2) the 3rd attempt's feedback (built
    # from the 2nd attempt's failure) must carry the escalation directive.
    assert feedbacks[0] is None
    assert any(fb and "ESCALATION" in fb for fb in feedbacks[1:])


def test_run_task_does_not_escalate_on_a_single_failure(tmp_path, monkeypatch):
    """A single failure (not yet repeated) must not trigger escalation —
    only genuinely *repeated* identical failures should."""

    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    target = tmp_path / "app.py"
    target.write_text("old\n", encoding="utf-8")

    outputs = iter(
        [
            "no diff here, sorry",
            "\n".join(
                [
                    "diff --git a/app.py b/app.py",
                    "--- a/app.py",
                    "+++ b/app.py",
                    "@@ -1 +1 @@",
                    "-old",
                    "+new",
                    "",
                    "TEST: pytest -q",
                ]
            ),
        ]
    )
    feedbacks = []

    def fake_generate(prompt, feedback=None):
        feedbacks.append(feedback)
        return next(outputs)

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(
        pipeline,
        "try_static_fixers",
        lambda *a, **k: FixerResult("none", False, "no static fixer matched"),
    )
    # No callers found -> impact result is "not needed", so the primary
    # test passing is enough to promote (matches
    # test_run_impact_tests_mapper_returns_no_callers's convention).
    monkeypatch.setattr(pipeline, "map_ask", lambda *a, **k: [])
    monkeypatch.setenv(
        "SIMPLICIO_TEST_CMD",
        f"{sys.executable} -c \"from pathlib import Path; import sys; sys.exit(0 if Path('app.py').read_text() == 'new\\n' else 1)\"",
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "change app",
        "app.py",
        "- behavior proven",
        "- keep compatibility",
        quiet=True,
    )

    assert result["applied"] is True
    assert len(feedbacks) == 2
    assert feedbacks[1] is not None
    assert "ESCALATION" not in feedbacks[1]


# ---------------------------------------------------------------------------
# AC4 — destructive full-file-replacement rejection.
# ---------------------------------------------------------------------------


def _big_file_text(n_lines: int = 20) -> str:
    return "\n".join(f"line{i}" for i in range(1, n_lines + 1)) + "\n"


def _full_replace_diff(n_lines: int = 20) -> str:
    old = [f"-line{i}" for i in range(1, n_lines + 1)]
    return "\n".join(
        [
            "diff --git a/big.py b/big.py",
            "--- a/big.py",
            "+++ b/big.py",
            f"@@ -1,{n_lines} +1,2 @@",
            *old,
            "+totally different content",
            "+that replaces everything",
            "",
        ]
    )


def test_validate_generated_output_rejects_destructive_full_file_replacement(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    result = pipeline_stages.validate_generated_output(
        _full_replace_diff(), bound_paths=["big.py"], root=str(tmp_path)
    )

    assert result.ok is False
    assert "destructive full-file rewrite" in result.reason


def test_validate_generated_output_allows_localized_diff_on_same_file(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    localized_diff = "\n".join(
        [
            "diff --git a/big.py b/big.py",
            "--- a/big.py",
            "+++ b/big.py",
            "@@ -5,1 +5,1 @@",
            "-line5",
            "+line5 modified",
            "TEST: pytest -q",
            "",
        ]
    )

    result = pipeline_stages.validate_generated_output(
        localized_diff, bound_paths=["big.py"], root=str(tmp_path)
    )

    assert result.ok is True


def test_validate_generated_output_skips_destructive_check_without_root(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    # No `root=` supplied (e.g. legacy callers, or a caller that cannot
    # resolve the pre-image) — the check is skipped, not a crash.
    result = pipeline_stages.validate_generated_output(
        _full_replace_diff() + "\nTEST: pytest -q", bound_paths=["big.py"]
    )

    assert result.ok is True


def test_validate_generated_output_skips_destructive_check_for_multi_file_bound_paths(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    # bound_paths resolves to more than one concrete file -> no single
    # "the whole file" comparison is meaningful; the check is a no-op.
    result = pipeline_stages.validate_generated_output(
        _full_replace_diff() + "\nTEST: pytest -q",
        bound_paths=["big.py", "other.py"],
        root=str(tmp_path),
    )

    assert result.ok is True


def test_validate_generated_output_skips_destructive_check_for_small_files(tmp_path):
    target = tmp_path / "small.py"
    target.write_text("a\nb\n", encoding="utf-8")

    diff = "\n".join(
        [
            "diff --git a/small.py b/small.py",
            "--- a/small.py",
            "+++ b/small.py",
            "@@ -1,2 +1,2 @@",
            "-a",
            "-b",
            "+x",
            "+y",
            "TEST: pytest -q",
            "",
        ]
    )

    result = pipeline_stages.validate_generated_output(diff, bound_paths=["small.py"], root=str(tmp_path))

    assert result.ok is True


def test_run_apply_stage_rejects_destructive_full_file_replacement(tmp_path, monkeypatch):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")

    result = pipeline_stages.run_apply_stage(_full_replace_diff(), str(tmp_path), bound_paths=["big.py"])

    assert result.ok is False
    assert "destructive full-file rewrite" in result.log
    # The real file must be untouched — this is caught pre-apply.
    assert target.read_text(encoding="utf-8") == _big_file_text()


# ---------------------------------------------------------------------------
# AC4 — narrow unit coverage for the helper functions' individual branches.
# ---------------------------------------------------------------------------


def test_diff_section_for_file_falls_back_to_plus_plus_marker_when_no_diff_git_line():
    patch = "\n".join(
        [
            "--- a/big.py",
            "+++ b/big.py",
            "@@ -1,2 +1,2 @@",
            "-a",
            "+x",
            "",
        ]
    )

    section = pipeline_stages._diff_section_for_file(patch, "big.py")

    assert "@@ -1,2 +1,2 @@" in section


def test_diff_section_for_file_returns_empty_when_target_absent():
    patch = "diff --git a/other.py b/other.py\n--- a/other.py\n+++ b/other.py\n"

    assert pipeline_stages._diff_section_for_file(patch, "big.py") == ""


def test_full_file_replacement_hints_skips_undecodable_pre_image(tmp_path):
    target = tmp_path / "big.py"
    target.write_bytes(b"\xff\xfe" + b"\x00" * 40)  # not valid UTF-8

    hints = pipeline_stages._full_file_replacement_hints(_full_replace_diff(), str(tmp_path), ["big.py"])

    assert hints == []


def test_full_file_replacement_hints_not_flagged_when_deletions_below_threshold(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    # Only 2 of 20 lines deleted, well under the 90% destructive threshold —
    # a legitimate small edit, even though it starts at line 1.
    diff = "\n".join(
        [
            "diff --git a/big.py b/big.py",
            "--- a/big.py",
            "+++ b/big.py",
            "@@ -1,2 +1,2 @@",
            "-line1",
            "-line2",
            "+line1 modified",
            "+line2 modified",
            "",
        ]
    )

    hints = pipeline_stages._full_file_replacement_hints(diff, str(tmp_path), ["big.py"])

    assert hints == []


def test_full_file_replacement_hints_not_flagged_when_context_kept(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_big_file_text(), encoding="utf-8")

    # Deletes every line but also keeps a handful as context, well above the
    # 10% context-ratio cutoff — this is not "delete everything", so it must
    # not be flagged as destructive.
    lines = ["diff --git a/big.py b/big.py", "--- a/big.py", "+++ b/big.py", "@@ -1,20 +1,20 @@"]
    for i in range(1, 21):
        if i % 2 == 0:
            lines.append(f" line{i}")
        else:
            lines.append(f"-line{i}")
            lines.append(f"+line{i} modified")
    diff = "\n".join(lines) + "\n"

    hints = pipeline_stages._full_file_replacement_hints(diff, str(tmp_path), ["big.py"])

    assert hints == []
