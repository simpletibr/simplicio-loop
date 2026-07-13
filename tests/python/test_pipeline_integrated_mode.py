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

from simplicio import pipeline
from simplicio.plan_compiler import EffectPlan, PlanDAG, RecordingEffectSink
from simplicio.plan_compiler.effect_sink import IntegratedModeRequiresSinkError


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


def test_standalone_mode_is_unaffected_default_and_still_applies_via_git_apply(tmp_path, monkeypatch):
    """mode='standalone' (the implicit default) must behave exactly as before."""
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


def test_integrated_mode_without_sink_raises_and_never_writes(tmp_path, monkeypatch):
    """No effect_sink => refuse to proceed; must not fall back to direct writes."""
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    before = _snapshot(tmp_path)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")

    try:
        pipeline.run_task(
            str(tmp_path),
            "python",
            "add api",
            "src/app.py",
            "- passes",
            "- small",
            mode="integrated",
            quiet=True,
        )
        raised = False
    except IntegratedModeRequiresSinkError:
        raised = True

    assert raised, "integrated mode without a sink must raise, not silently write"
    assert _snapshot(tmp_path) == before


def test_integrated_mode_without_test_cmd_is_blocked_not_applied(tmp_path, monkeypatch):
    monkeypatch.delenv("SIMPLICIO_TEST_CMD", raising=False)
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    sink = RecordingEffectSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- passes",
        "- small",
        mode="integrated",
        effect_sink=sink,
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "blocked"
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
    sink = RecordingEffectSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "- true state\n- false state",
        "- build passes",
        mode="integrated",
        effect_sink=sink,
        quiet=True,
    )

    after = _snapshot(tmp_path)
    assert after == before, "run_task must not modify the worktree in integrated mode"

    assert result["applied"] is False
    assert result["status"] == "integrated_planned"

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
    assert len(result["effect_sink_results"]) == 1
    assert result["effect_sink_results"][0]["effect_id"] == effect.effect_id
    assert result["effect_sink_results"][0]["accepted"] is True
    assert "not applied" in result["effect_sink_results"][0]["detail"]


def test_integrated_mode_needs_clarification_when_no_acceptance_criteria(tmp_path, monkeypatch):
    """compile_task_spec_to_plan raises PlanCompilationError with no AC lines
    -- run_task must surface this as a blocked result, not crash or write."""
    monkeypatch.setenv("SIMPLICIO_TEST_CMD", "pytest -q")
    monkeypatch.setattr(pipeline, "build_prompt", lambda *args, **kwargs: "prompt")
    before = _snapshot(tmp_path)
    sink = RecordingEffectSink()

    result = pipeline.run_task(
        str(tmp_path),
        "python",
        "add api",
        "src/app.py",
        "",  # no acceptance criteria lines at all
        "- build passes",
        mode="integrated",
        effect_sink=sink,
        quiet=True,
    )

    assert result["applied"] is False
    assert result["status"] == "blocked"
    assert "NEEDS_CLARIFICATION" in result["warnings"][0]
    assert sink.received == []
    assert _snapshot(tmp_path) == before
