"""Plan compiler contracts (issue #166): Goal + ContextSnapshot -> PlanDAG.

Public surface only — see :mod:`simplicio.plan_compiler.models` for the
schema definitions and ``docs/plan-compiler.md`` for the contract writeup.
"""

from __future__ import annotations

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.compile_task_spec import (
    PlanCompilationError,
    compile_task_spec_to_plan,
)
from simplicio.plan_compiler.errors import (
    PlanCompilerError,
    PlanValidationError,
    SchemaMismatchError,
)
from simplicio.plan_compiler.models import (
    CONTEXT_SNAPSHOT_SCHEMA,
    EFFECT_PLAN_SCHEMA,
    GOAL_ENVELOPE_SCHEMA,
    PLAN_COMPILER_COMPATIBILITY,
    PLAN_DAG_SCHEMA,
    VERIFICATION_PLAN_SCHEMA,
    ContextSnapshot,
    EffectPlan,
    GoalEnvelope,
    PlanDAG,
    PlanNode,
    VerificationPlan,
)

__all__ = [
    "CONTEXT_SNAPSHOT_SCHEMA",
    "EFFECT_PLAN_SCHEMA",
    "GOAL_ENVELOPE_SCHEMA",
    "PLAN_COMPILER_COMPATIBILITY",
    "PLAN_DAG_SCHEMA",
    "VERIFICATION_PLAN_SCHEMA",
    "ContextSnapshot",
    "EffectPlan",
    "GoalEnvelope",
    "PlanCompilationError",
    "PlanCompilerError",
    "PlanDAG",
    "PlanNode",
    "PlanValidationError",
    "SchemaMismatchError",
    "VerificationPlan",
    "canonical_hash",
    "compile_task_spec_to_plan",
]
