"""Integrated-mode boundary tests (issues #166, #167).

Both issues name the same unchecked acceptance criterion: "no modo
integrado, zero escrita/commit fora da Effect API do Runtime" (#166) / "modo
integrado não executa writes diretamente" (#167). ``pipeline.run_task``
previously had no integrated-mode concept at all -- these tests prove the
new ``mode="integrated"`` entry point added in ``simplicio/pipeline.py``:

- never touches the worktree (unlike ``mode="standalone"``, the unchanged
  default, which still applies via ``git apply``);
- compiles a real ``PlanDAG``/``EffectPlan`` bundle via
  ``compile_task_spec_to_plan()`` and hands every ``EffectPlan`` to the
  caller-supplied ``effect_sink`` -- the local stub boundary for the real
  ``simplicio-runtime`` Effect API (Runtime #3134/#3135);
- refuses to proceed (raises ``IntegratedModeRequiresSinkError``) instead of
  silently falling back to direct writes when no sink is supplied.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from simplicio import pipeline
from simplicio.atomic_execution import AttemptContext
from simplicio.plan_compiler import EffectPlan, PlanDAG, RecordingEffectSink

READY_RUNTIME = {
    "verified": True,
    "version": "3.6.0",
    "capabilities": ["simplicio.effect-transaction/v1"],
    "reason": "ok",
}
CANONICAL_CONTEXT = {
    "schema": "simplicio.context-snapshot/v1",
    "snapshot_id": "snapshot-real-1",
    "revision": "abc123",
    "digest": "sha256:context",
}
CANONICAL_PACK = {"schema": "simplicio.context-pack/v1"}
CONTEXT_HANDLE = "sha256:" + "c" * 64


@pytest.fixture(autouse=True)
def canonical_mapper_boundary(monkeypatch):
    def load(payload, **_kwargs):
        if payload is CANONICAL_CONTEXT:
            view = SimpleNamespace(snapshot_id="snapshot-real-1", revision="abc123", root_hash="root-hash")
            return SimpleNamespace(payload_bytes=b"canonical-context", view=view)
        from simplicio.plan_compiler.mapper_context import MapperContextError

        raise MapperContextError("TEST_CONTEXT_REJECTED", "not canonical")

    monkeypatch.setattr("simplicio.execution_mode.load_mapper_context", load)
    monkeypatch.setattr("simplicio.pipeline_integrated.load_mapper_context", load)
    monkeypatch.setattr("simplicio.execution_mode.RuntimeEffectSink", RuntimeTestSink)

    def bind(snapshot, pack, **_kwargs):
        assert snapshot is CANONICAL_CONTEXT
        assert pack is CANONICAL_PACK
        return SimpleNamespace(
            snapshot=load(snapshot),
            context_handle=SimpleNamespace(
                value=CONTEXT_HANDLE,
                to_dict=lambda: {
                    "schema": "simplicio.dev-cli.context-handle/v1",
                    "source_digest": "a" * 64,
                    "projection_digest": "b" * 64,
                },
            ),
        )

    monkeypatch.setattr("simplicio.pipeline_integrated.bind_mapper_context", bind)
    monkeypatch.setattr("simplicio.pipeline_integrated.verify_context_sources", lambda *a, **k: None)


class RuntimeTestSink(RecordingEffectSink):
    """Contract-shaped sink used only beyond the production negotiation gate."""

    def __init__(self):
        super().__init__(state="running")

    test_only = False


def _attempt() -> AttemptContext:
    return AttemptContext("attempt-1", "lease-1", "fence-7", CONTEXT_HANDLE)


def _valid_pipeline_diff() -> str:
    return "\n".join(
        [
            "diff --git a/src/app.py b/src/app.py",
            "--- a/src/app.py",
            "+++ b/src/app.py",
            "@@ -0,0 +1 @@",
            "+print('ok')",
            "",
            "TEST: pytest -q",
        ]
    )


def _snapshot(root: Path) -> dict[str, str]:
    """Content snapshot of every source file under root, for effect-free assertions.

    Excludes ``.simplicio/`` -- that directory holds observability evidence
    (``emit_event``'s ``events.jsonl``, run logs), which every pipeline mode
    (standalone included) legitimately writes as telemetry; it is not the
    application effect this test guards against. See
    ``simplicio/observability.py``'s ``emit_event`` contract (issue #107).
    """
    snapshot = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".simplicio" not in path.relative_to(root).parts:
            snapshot[str(path.relative_to(root))] = path.read_bytes().hex()
    return snapshot


def test_standalone_mode_is_unaffected_when_selected_explicitly(tmp_path, monkeypatch):
    """Explicit mode='standalone' must behave exactly as before."""
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")

    def fake_generate(prompt, feedback=None):
        return _valid_pipeline_diff()

    monkeypatch.setattr(pipeline, "generate", fake_generate)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(
        pipeline, "_apply_and_test", lambda output, root, bound_paths=None: (True, "1 passed")
    )
    monkeypatch.setattr(
        pipeline,
        "_run_impact_tests",
        lambda *a, **k: {
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
        },
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="standalone",
        quiet=True,
    )

    assert result["applied"] is True
    assert "plan" not in result
    assert "effects" not in result
    assert "effect_sink_results" not in result


def test_standalone_mode_explicit_matches_implicit_default(tmp_path, monkeypatch):
    """Passing mode='standalone' explicitly is a no-op vs. the default."""
    monkeypatch.setenv("SIMPLICIO_DISABLE_RUN_LOG", "1")
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "generate", lambda prompt, feedback=None: _valid_pipeline_diff())
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(
        pipeline, "_apply_and_test", lambda output, root, bound_paths=None: (True, "1 passed")
    )
    monkeypatch.setattr(
        pipeline,
        "_run_impact_tests",
        lambda *a, **k: {
            "status": "no_callers_found",
            "callers": [],
            "tests_run": [],
            "result": pipeline.IMPACT_RESULT_NOT_NEEDED,
        },
    )

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="standalone",
        quiet=True,
    )

    assert result["applied"] is True


def test_integrated_mode_without_sink_fails_closed_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    before = _snapshot(tmp_path)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )
    assert result["status"] == "blocked"
    assert result["warnings"] == ["RUNTIME_SINK_REQUIRED"]
    assert _snapshot(tmp_path) == before


def test_integrated_mode_without_attempt_fails_closed_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=RuntimeTestSink(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        quiet=True,
    )

    assert result["status"] == "blocked"
    assert result["warnings"] == ["COORDINATOR_CONTEXT_REQUIRED"]
    assert result["execution_profile"]["effective_mode"] == "blocked"


def test_integrated_mode_without_test_cmd_is_blocked_not_applied(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    sink = RuntimeTestSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=_attempt(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "blocked"
    assert sink.received == []


def test_integrated_mode_requires_pack_and_matching_digest_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    sink = RuntimeTestSink()

    missing = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=_attempt(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        quiet=True,
    )
    mismatch = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=AttemptContext("attempt-1", "lease-1", "fence-7", "sha256:" + "d" * 64),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )

    assert missing["warnings"] == ["CONTEXT_PACK_REQUIRED"]
    assert mismatch["warnings"] == ["CONTEXT_HANDLE_MISMATCH"]
    assert sink.received == []


def test_integrated_mode_blocks_source_drift_before_effect(tmp_path, monkeypatch):
    from simplicio.plan_compiler.mapper_context import MapperContextError

    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")

    def drift(*_args, **_kwargs):
        raise MapperContextError("SOURCE_DRIFT", "src/app.py changed")

    monkeypatch.setattr("simplicio.pipeline_integrated.verify_context_sources", drift)
    sink = RuntimeTestSink()
    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=_attempt(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )

    assert result["warnings"] == ["SOURCE_DRIFT"]
    assert result["blocked_preconditions"][0]["code"] == "SOURCE_DRIFT"
    assert sink.received == []


def test_integrated_mode_compiles_plan_and_dispatches_effect_without_writing(tmp_path, monkeypatch):
    """The core contract: compile a real PlanDAG/EffectPlan, hand it to the
    sink, and never touch the worktree -- unlike standalone mode, which does."""
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir(parents=True)
    target.write_text("old\n", encoding="utf-8")
    other = tmp_path / "README.md"
    other.write_text("keep me\n", encoding="utf-8")

    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    # generate() must not even be needed to prove the no-write guarantee, but
    # patch it anyway so a future change that calls it doesn't reach the
    # network/provider layer in this test.
    monkeypatch.setattr(pipeline, "generate", lambda *a, **k: _valid_pipeline_diff())

    before = _snapshot(tmp_path)
    sink = RuntimeTestSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- true state\n- false state",
        "- build passes",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=_attempt(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )

    after = _snapshot(tmp_path)
    assert after == before, "run_task must not modify the worktree in integrated mode"

    assert result["applied"] is False
    assert result["status"] == "integrated_atomic"

    assert len(sink.received) == 1
    effect = sink.received[0]
    assert isinstance(effect, EffectPlan)
    assert effect.kind == "write"
    assert effect.authority_required == "dev-cli.edit"

    plan = PlanDAG.from_dict(result["plan"])
    assert plan.plan_id == "plan-src/app.py"
    assert [node.node_id for node in plan.nodes] == ["edit", "verify"]
    # AC coverage: both parsed acceptance-criteria lines map onto every node.
    assert plan.nodes[0].acceptance_criteria_refs == ["AC1", "AC2"]

    assert result["effects"][0]["effect_id"] == effect.effect_id
    observation = result["observation"]
    assert observation["outcome"] == "effect_submitted"
    assert observation["attempt_id"] == "attempt-1"
    assert observation["lease_id"] == "lease-1"
    assert observation["fencing_token"] == "fence-7"
    assert observation["context_handle"] == CONTEXT_HANDLE
    assert result["plan"]["context_handle"] == CONTEXT_HANDLE
    assert result["effects"][0]["context_handle"] == CONTEXT_HANDLE
    assert sink.contexts[0].context_handle == CONTEXT_HANDLE
    assert result["context_binding"]["context_handle"] == CONTEXT_HANDLE
    assert observation["resources"]["effect_calls"] == 1
    assert observation["resources"]["threads_created"] == 0


def test_integrated_mode_needs_clarification_when_no_acceptance_criteria(tmp_path, monkeypatch):
    """compile_task_spec_to_plan raises PlanCompilationError with no AC lines
    -- run_task must surface this as a blocked result, not crash or write."""
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    before = _snapshot(tmp_path)
    sink = RuntimeTestSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "",  # no acceptance criteria lines at all
        "- build passes",
        mode="integrated",
        effect_sink=sink,
        integrated_attempt=_attempt(),
        runtime_handshake=READY_RUNTIME,
        context_snapshot=CANONICAL_CONTEXT,
        context_pack=CANONICAL_PACK,
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "blocked"
    assert "NEEDS_CLARIFICATION" in result["warnings"][0]
    assert sink.received == []
    assert _snapshot(tmp_path) == before
