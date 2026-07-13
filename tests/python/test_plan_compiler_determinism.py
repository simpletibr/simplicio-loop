"""Determinism guarantee for the plan compiler (issue #166 slice N).

Turns the unchecked issue #166 acceptance criterion "Mesma entrada canônica
gera PlanDAG semanticamente idêntico no modo determinístico" into an
executable guarantee: compiling the *same* canonical `TaskSpec` +
`goal_id`/`context_snapshot_id`/`revision` input through
`compile_task_spec_to_plan()` — in two independent, freshly-built calls, with
no shared mutable state between them — must always produce a
semantically identical `PlanDAG`/`EffectPlan`/`VerificationPlan` bundle: same
node ids, same edges, same `to_dict()` payload and same `canonical_hash()`.

`compile_task_spec.py`/`canonical_hash.py`/`models.py` were audited for
non-determinism sources (random/uuid id generation, wall-clock timestamps,
unordered dict/set iteration reaching the hash input) and none were found:
every id is derived deterministically from `task_spec.task_id`/
`task_spec.source_hash` plus the caller-supplied `goal_id`/
`context_snapshot_id`/`revision`, and `canonical_hash()` serializes with
`sort_keys=True`. This test locks that property in for the full compile
entry point (the existing `test_canonical_hash_is_deterministic` in
`test_plan_compiler.py` only covered a hand-built `PlanDAG`, not a
`compile_task_spec_to_plan()` round trip).
"""

from __future__ import annotations

from simplicio.plan_compiler import compile_task_spec_to_plan
from simplicio.task_spec import TaskSpec

COMPILE_KWARGS = {
    "goal_id": "goal-1",
    "context_snapshot_id": "snap-1",
    "revision": "1",
}


def _task_spec(**overrides: object) -> TaskSpec:
    defaults: dict[str, object] = {
        "task_id": "T1",
        "source": {"kind": "argument"},
        "source_hash": "deadbeef",
        "language": "pt-BR",
        "acceptance_criteria": [{"id": "AC1"}, {"id": "AC2"}],
        "verification_commands": [
            {"command": "pytest tests/python/test_foo.py -q"},
            {"command": "pytest tests/python/test_bar.py -q", "verifier": "pytest", "timeout_s": 120.0},
        ],
    }
    defaults.update(overrides)
    return TaskSpec(**defaults)  # type: ignore[arg-type]


def test_compile_task_spec_is_deterministic_across_independent_calls() -> None:
    """Two fresh compiles of the same canonical input must be semantically identical."""
    plan_a, effects_a, verifications_a = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)
    plan_b, effects_b, verifications_b = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)

    # Same node ids and edges.
    assert [node.node_id for node in plan_a.nodes] == [node.node_id for node in plan_b.nodes]
    assert [node.depends_on for node in plan_a.nodes] == [node.depends_on for node in plan_b.nodes]

    # Full structural equality via to_dict() for the plan and every sibling artifact.
    assert plan_a.to_dict() == plan_b.to_dict()
    assert [effect.to_dict() for effect in effects_a] == [effect.to_dict() for effect in effects_b]
    assert [v.to_dict() for v in verifications_a] == [v.to_dict() for v in verifications_b]

    # Same canonical_hash() — the identity a Runtime/Loop consumer keys off of.
    assert plan_a.canonical_hash() == plan_b.canonical_hash()


def test_compile_task_spec_is_deterministic_across_repeated_calls_same_instance() -> None:
    """Compiling the same TaskSpec instance twice must not mutate shared state."""
    task_spec = _task_spec()

    plan_a, effects_a, verifications_a = compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)
    plan_b, effects_b, verifications_b = compile_task_spec_to_plan(task_spec, **COMPILE_KWARGS)

    assert plan_a.to_dict() == plan_b.to_dict()
    assert [effect.to_dict() for effect in effects_a] == [effect.to_dict() for effect in effects_b]
    assert [v.to_dict() for v in verifications_a] == [v.to_dict() for v in verifications_b]
    assert plan_a.canonical_hash() == plan_b.canonical_hash()


def test_compile_task_spec_hash_is_stable_across_process_like_repeats() -> None:
    """Repeating compile+hash N times must always yield the same hash (no id/order flakiness)."""
    hashes = set()
    for _ in range(5):
        plan, effects, verifications = compile_task_spec_to_plan(_task_spec(), **COMPILE_KWARGS)
        plan.validate(effects=effects, verifications=verifications)
        hashes.add(plan.canonical_hash())

    assert len(hashes) == 1, f"expected a single stable canonical_hash, got {hashes}"
