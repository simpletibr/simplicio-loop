"""Bound-path integrity — checked before AND after generation (issue #210 AC6).

Before this slice, `validate_generated_output`/`_bound_path_warnings` only
ever inspected the *returned diff text* for paths outside `bound_paths` —
there was no check of the actual on-disk state of a bound file across the
window a provider subprocess is running in. That left the issue's repro
scenario uncaught: a target file deleted out-of-band while the provider
stalled would never show up as a diff-text violation (the diff, if any,
never mentions a path it didn't touch).

`snapshot_bound_paths`/`bound_path_drift` (simplicio/pipeline_stages.py)
close that gap, and `pipeline.run_task` wires them in immediately around
each `generate()` call (both the dry-run path and the main attempt loop).
"""

from __future__ import annotations

from simplicio import pipeline
from simplicio.pipeline_stages import bound_path_drift, snapshot_bound_paths

# --------------------------------------------------------------------------- #
# Unit: snapshot_bound_paths / bound_path_drift
# --------------------------------------------------------------------------- #


def test_snapshot_records_existing_file_identity(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")

    snapshot = snapshot_bound_paths(str(tmp_path), ["a.txt"])

    key = str(target)
    assert key in snapshot
    exists, size, mtime_ns = snapshot[key]
    assert exists is True
    assert size == len("hello")
    assert mtime_ns > 0


def test_snapshot_records_absence_for_missing_file(tmp_path):
    snapshot = snapshot_bound_paths(str(tmp_path), ["missing.txt"])
    key = str(tmp_path / "missing.txt")
    assert snapshot[key] == (False, 0, 0)


def test_snapshot_skips_glob_bound_patterns(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("x", encoding="utf-8")
    snapshot = snapshot_bound_paths(str(tmp_path), ["sub/**"])
    assert snapshot == {}


def test_drift_empty_when_nothing_changed(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")
    baseline = snapshot_bound_paths(str(tmp_path), ["a.txt"])

    assert bound_path_drift(str(tmp_path), ["a.txt"], baseline) == []


def test_drift_detects_deletion(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")
    baseline = snapshot_bound_paths(str(tmp_path), ["a.txt"])

    target.unlink()

    warnings = bound_path_drift(str(tmp_path), ["a.txt"], baseline)
    assert len(warnings) == 1
    assert "deleted out-of-band" in warnings[0]
    assert str(target) in warnings[0]


def test_drift_detects_out_of_band_mutation(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("hello", encoding="utf-8")
    baseline = snapshot_bound_paths(str(tmp_path), ["a.txt"])

    # Force a distinguishable size + mtime change (not just a same-second
    # touch, which some filesystems coalesce at 1s mtime resolution).
    target.write_text("hello world, much longer now", encoding="utf-8")

    warnings = bound_path_drift(str(tmp_path), ["a.txt"], baseline)
    assert len(warnings) == 1
    assert "mutated out-of-band" in warnings[0]


def test_drift_detects_out_of_band_creation(tmp_path):
    baseline = snapshot_bound_paths(str(tmp_path), ["created.txt"])
    (tmp_path / "created.txt").write_text("new", encoding="utf-8")

    warnings = bound_path_drift(str(tmp_path), ["created.txt"], baseline)
    assert len(warnings) == 1
    assert "created out-of-band" in warnings[0]


def test_drift_ignores_paths_not_in_baseline(tmp_path):
    # A path snapshotted under a different bound_paths set (or never
    # snapshotted at all) should not be reported — bound_path_drift only
    # reports drift for paths it was actually asked to watch.
    (tmp_path / "untracked.txt").write_text("x", encoding="utf-8")
    assert bound_path_drift(str(tmp_path), ["untracked.txt"], {}) == []


# --------------------------------------------------------------------------- #
# Integration: wired into pipeline.run_task around generate()
# --------------------------------------------------------------------------- #


def _common_monkeypatches(monkeypatch):
    monkeypatch.setattr(pipeline, "build_prompt", lambda *a, **k: "BASE PROMPT")
    monkeypatch.setattr(pipeline, "log_run", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "emit_event", lambda *a, **k: None)
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")


def test_run_task_blocks_when_bound_file_deleted_during_generate(monkeypatch, tmp_path):
    """Reproduces the issue's own repro: a bound target is removed
    out-of-band in the window between the pre-generate snapshot and
    generate() returning (standing in for "deleted while the provider
    subprocess stalled"). run_task must refuse to proceed to apply/promote
    against a worktree that just had a bound file pulled out from under it,
    and must report the changed path — not silently retry against garbage."""
    _common_monkeypatches(monkeypatch)
    target = tmp_path / "app.py"
    target.write_text("original content\n", encoding="utf-8")

    def fake_generate(prompt, feedback=None):
        # Simulate the file being deleted while "the provider was running".
        target.unlink()
        return "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"

    monkeypatch.setattr(pipeline, "generate", fake_generate)

    result = pipeline.run_task(
        str(tmp_path), "python", "fix bug", "app.py", "", "", bound_paths=["app.py"], quiet=True
    )

    assert result["applied"] is False
    assert result["status"] == "blocked"
    assert any("deleted out-of-band" in w for w in result["warnings"])
    blockers = result.get("blocked_preconditions") or []
    assert any(b.get("code") == "bound_path_out_of_band_mutation" for b in blockers)


def test_run_task_proceeds_normally_when_no_drift(monkeypatch, tmp_path):
    """Sanity check: the drift gate must not fire (or otherwise change
    behavior) on the ordinary, nothing-mutated-out-of-band path."""
    _common_monkeypatches(monkeypatch)
    target = tmp_path / "app.py"
    target.write_text("original content\n", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "generate",
        lambda prompt, feedback=None: "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n",
    )
    monkeypatch.setattr(
        pipeline,
        "_apply_and_test",
        lambda *a, **k: (False, "AssertionError: unrelated failure, not a drift issue"),
    )
    monkeypatch.setenv("SIMPLICIO_MAX_ATTEMPTS", "1")

    result = pipeline.run_task(
        str(tmp_path), "python", "fix bug", "app.py", "", "", bound_paths=["app.py"], quiet=True
    )

    # Reaches the normal fail-closed-on-test-failure path, not the
    # out-of-band-mutation short circuit.
    assert not any(
        b.get("code") == "bound_path_out_of_band_mutation"
        for b in (result.get("blocked_preconditions") or [])
    )


def test_dry_run_reports_drift_as_a_warning_without_raising(monkeypatch, tmp_path):
    _common_monkeypatches(monkeypatch)
    monkeypatch.setattr(pipeline, "_dry_run_preconditions", lambda *a, **k: [])
    target = tmp_path / "app.py"
    target.write_text("original content\n", encoding="utf-8")

    def fake_generate(prompt, feedback=None):
        target.write_text("mutated out of band while the provider ran\n", encoding="utf-8")
        return ""

    monkeypatch.setattr(pipeline, "generate", fake_generate)

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "fix bug",
        "app.py",
        "",
        "",
        bound_paths=["app.py"],
        dry_run_task=True,
    )

    assert result["status"] == "dry_run"
    assert any("mutated out-of-band" in w for w in result["warnings"])
