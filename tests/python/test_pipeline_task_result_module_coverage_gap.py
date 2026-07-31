"""Direct unit coverage for simplicio/pipeline_task_result.py.

The coordinator imports this module's `_task_result`; the regression test
below prevents a stale local copy from shadowing the extracted implementation.
"""

from __future__ import annotations

import pytest

from simplicio import pipeline_task_result as ptr


def test_pipeline_uses_extracted_task_result_assembler():
    from simplicio import pipeline

    assert pipeline._task_result is ptr._task_result


def test_pipeline_records_terminal_provider_receipt_in_standalone_mode(tmp_path, monkeypatch):
    """Provider refusal remains a typed terminal task result, never a crash."""
    from simplicio import pipeline
    from simplicio.providers import ProviderExecutionError

    target = tmp_path / "app.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    receipt = {
        "status": "blocked",
        "reason_code": "llm_execution_disabled",
        "message": "LLM execution is disabled",
    }

    def refuse(_prompt, _feedback=None):
        raise ProviderExecutionError(receipt)

    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "placeholder")
    monkeypatch.setattr(pipeline, "generate", refuse)

    result = pipeline.run_task(
        tmp_path,
        "python",
        "keep the file unchanged",
        "app.py",
        "- remains valid",
        "- local only",
        mode="standalone",
        quiet=True,
    )

    assert result["status"] == "blocked"
    assert result["provider_terminal"] == receipt
    assert result["blocked_preconditions"][0]["reason"] == "llm_execution_disabled"


def test_pipeline_run_compatibility_returns_only_applied_result(monkeypatch):
    from simplicio import pipeline

    monkeypatch.setattr(pipeline, "run_task", lambda *args, **kwargs: {"applied": True})
    assert pipeline.run(".", "python", "goal", "app.py", "- works", "- local") == {"applied": True}

    monkeypatch.setattr(pipeline, "run_task", lambda *args, **kwargs: {"applied": False})
    assert pipeline.run(".", "python", "goal", "app.py", "- works", "- local") is None


def test_pipeline_impact_compatibility_preserves_two_argument_hook(monkeypatch):
    from simplicio import pipeline

    calls = []

    def fake_impact(root, files):
        calls.append((root, files))
        return {"result": "not_needed"}

    monkeypatch.setattr(pipeline, "_run_impact_tests", fake_impact)
    assert pipeline._run_impact_tests_compat("root", ["app.py"], None) == {"result": "not_needed"}
    assert calls == [("root", ["app.py"])]


def test_pipeline_can_clear_last_verify_receipt(monkeypatch):
    from simplicio import pipeline

    monkeypatch.setattr(pipeline, "_LAST_VERIFY_RECEIPT", {"transaction_id": "old"})
    pipeline._remember_verify_receipt(None)
    assert pipeline._LAST_VERIFY_RECEIPT is None


def test_run_task_spec_rejects_invalid_typed_input():
    from simplicio import pipeline

    with pytest.raises(TypeError, match="requires"):
        pipeline.run_task_spec(".", "python", object())


def test_verify_receipt_payload_none_when_empty():
    assert ptr._verify_receipt_payload(None) is None
    assert ptr._verify_receipt_payload({}) is None


def test_verify_receipt_payload_shapes_fields():
    receipt = {
        "transaction_id": "t1",
        "base_sha": "abc",
        "candidate_sha": "def",
        "receipt_digest": "digest",
        "commands": ["pytest"],
        "exit_codes": [0],
        "stdout_tail": "ok",
        "stderr_tail": "",
        "files": ["a.py"],
    }
    payload = ptr._verify_receipt_payload(receipt)
    assert payload["command"] == "pytest"
    assert payload["exit_code"] == 0
    assert payload["files"] == ["a.py"]


def test_diff_summary_empty():
    assert ptr._diff_summary([]) == "no changed files reported"


def test_diff_summary_lists_files():
    assert ptr._diff_summary(["a.py", "b.py"]) == "changed a.py, b.py"


def test_task_result_basic_applied(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result("T01", "prompt", "output", applied=True)
    assert result["task_id"] == "T01"
    assert result["applied"] is True
    assert result["status"] == "applied"
    assert "verify" not in result
    assert "impact" not in result


def test_task_result_failed_status_default(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result("T01", "prompt", "", applied=False)
    assert result["status"] == "failed"


def test_task_result_includes_patch_receipt(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", {"sha": "abc"})
    result = ptr._task_result("T01", "prompt", "output", applied=True)
    assert result["patch"] == {"sha": "abc"}


def test_task_result_verify_all_zero_marks_verified(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        verify={"commands": ["pytest"], "exit_codes": [0]},
    )
    assert result["verify"]["status"] == "verified"


def test_task_result_verify_nonzero_marks_failed(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        verify={"commands": ["pytest"], "exit_codes": [1]},
    )
    assert result["verify"]["status"] == "failed"


def test_task_result_verify_no_exit_codes_unverified(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        verify={"commands": [], "exit_codes": []},
    )
    assert result["verify"]["status"] == ptr.IMPACT_RESULT_UNVERIFIED


def test_task_result_impact_passed(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        impact={
            "callers": ["mod.fn"],
            "tests_run": ["tests/test_fn.py"],
            "result": "verified",
            "command": "pytest tests/test_fn.py",
            "returncode": 0,
            "output_tail": "ok",
            "status": "passed",
        },
    )
    assert result["impact"]["status"] == "verified"
    assert "receipt" in result["impact"]


def test_task_result_impact_failed(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        impact={
            "callers": [],
            "tests_run": [],
            "command": "pytest",
            "returncode": 1,
            "status": "failed",
        },
    )
    assert result["impact"]["status"] == "failed"


def test_task_result_preserves_native_impact_receipt(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    receipt = {"schema": "simplicio.runtime-impact/v1", "status": "passed"}
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        impact={"status": "passed", "receipt": receipt},
    )
    assert result["impact"]["receipt"] == receipt


def test_task_result_impact_unknown_status_unverified(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    result = ptr._task_result(
        "T01",
        "prompt",
        "output",
        applied=True,
        impact={"status": "unknown"},
    )
    assert result["impact"]["status"] == ptr.IMPACT_RESULT_UNVERIFIED
    assert "receipt" in result["impact"]


def test_task_result_blocked_preconditions_included(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)
    blockers = [{"reason": "x", "message": "m"}]
    result = ptr._task_result(
        "T01", "prompt", "", applied=False, status="blocked", blocked_preconditions=blockers
    )
    assert result["blocked_preconditions"] == blockers


def test_task_result_prompt_envelope_receipt(monkeypatch):
    from simplicio import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_LAST_PATCH_RECEIPT", None)

    class _Envelope:
        def receipt(self):
            return {"schema": "envelope/v1"}

    result = ptr._task_result("T01", "prompt", "output", applied=True, prompt_envelope=_Envelope())
    assert result["prompt_envelope"] == {"schema": "envelope/v1"}


# ---------------------------------------------------------------------------
# _dry_run_preconditions
# ---------------------------------------------------------------------------


def test_dry_run_preconditions_missing_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(ptr, "artifact_status", lambda root: {})
    monkeypatch.setattr(ptr, "map_handoff", lambda root: None)
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    reasons = {b["reason"] for b in blockers}
    assert "artifacts_missing" in reasons
    assert "no_handoff_targets" in reasons


def test_dry_run_preconditions_stale_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {
            "project_map": {"present": True},
            "precedent_index": {"present": True},
            "inspection": {"warnings": ["index looks stale"]},
        },
    )
    monkeypatch.setattr(
        ptr,
        "map_handoff",
        lambda root: {"context_pack": {"files": [{"path": "a.py"}]}},
    )
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    reasons = {b["reason"] for b in blockers}
    assert "artifacts_stale" in reasons


def test_dry_run_preconditions_context_pack_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(ptr, "map_handoff", lambda root: {"context_pack": "not-a-dict"})
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    reasons = {b["reason"] for b in blockers}
    assert "no_handoff_targets" in reasons


def test_dry_run_preconditions_needs_broader_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(
        ptr,
        "map_handoff",
        lambda root: {"context_pack": {"needs_broader_context": True, "files": []}},
    )
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    reasons = {b["reason"] for b in blockers}
    assert "broader_context_required" in reasons


def test_dry_run_preconditions_no_files_in_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(ptr, "map_handoff", lambda root: {"context_pack": {"files": []}})
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    reasons = {b["reason"] for b in blockers}
    assert "no_handoff_targets" in reasons


def test_dry_run_preconditions_target_not_in_files_but_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(ptr, "map_handoff", lambda root: {"context_pack": {"files": [{"path": "other.py"}]}})
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    target_blocker = next(b for b in blockers if b["reason"] == "target_resolution_failed")
    assert target_blocker["next_surface"] == "context_pack"


def test_dry_run_preconditions_target_missing_from_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(ptr, "map_handoff", lambda root: {"context_pack": {"files": [{"path": "a.py"}]}})
    blockers = ptr._dry_run_preconditions(tmp_path, "missing/missing.py")
    reasons = {b["reason"] for b in blockers}
    assert "target_resolution_failed" in reasons


def test_dry_run_preconditions_all_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )
    monkeypatch.setattr(ptr, "map_handoff", lambda root: {"context_pack": {"files": [{"path": "a.py"}]}})
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(tmp_path, "a.py")
    assert blockers == []


def test_dry_run_preconditions_prefers_supplied_canonical_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ptr,
        "artifact_status",
        lambda root: {"project_map": {"present": True}, "precedent_index": {"present": True}},
    )

    def fail_generic_handoff(root):
        raise AssertionError("generic mapper handoff must not replace canonical pack")

    monkeypatch.setattr(ptr, "map_handoff", fail_generic_handoff)
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(
        tmp_path,
        "a.py",
        context_pack={"files": [{"path": "a.py"}]},
    )
    assert blockers == []


def test_dry_run_preconditions_accepts_explicit_degraded_local_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ALLOW_DEGRADED_MAPPER", "1")
    monkeypatch.setattr(ptr, "artifact_status", lambda root: {})
    monkeypatch.setattr(ptr, "map_handoff", lambda root: None)
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    blockers = ptr._dry_run_preconditions(
        tmp_path,
        "a.py",
        context_pack={
            "fidelity": {"gate": "degraded_local", "status": "UNVERIFIED"},
            "files": [{"path": "a.py"}],
        },
        allow_degraded_mapper=True,
    )
    assert blockers == []


def test_dry_run_preconditions_dedups_identical_blockers(tmp_path, monkeypatch):
    monkeypatch.setattr(ptr, "artifact_status", lambda root: {})
    monkeypatch.setattr(ptr, "map_handoff", lambda root: None)
    blockers = ptr._dry_run_preconditions(tmp_path, "missing.py")
    keys = [(b["reason"], b["next_surface"]) for b in blockers]
    assert len(keys) == len(set(keys))
