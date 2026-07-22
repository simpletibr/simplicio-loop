"""Plan compiler contracts (issue #166): Goal + Mapper context -> PlanDAG.

Public surface only — see :mod:`simplicio.plan_compiler.models` for the
schema definitions and ``docs/plan-compiler.md`` for the contract writeup.
"""

from __future__ import annotations

from simplicio.plan_compiler.canonical_hash import canonical_hash
from simplicio.plan_compiler.compat_adapter import (
    GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION,
    GOAL_ENVELOPE_VERSION,
    PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION,
    PLAN_DAG_VERSION,
    CompatAdapterError,
    CompatAdapterExpiredError,
    UnsupportedCompatVersionError,
    adapt_goal_envelope_inbound,
    adapt_goal_envelope_outbound,
    adapt_inbound,
    adapt_outbound,
)
from simplicio.plan_compiler.compile_task_spec import (
    PlanCompilationError,
    compile_task_spec_to_plan,
)
from simplicio.plan_compiler.effect_sink import (
    EffectDispatchContext,
    EffectOutcome,
    EffectSink,
    IntegratedModeRequiresSinkError,
    RecordingEffectSink,
)
from simplicio.plan_compiler.errors import (
    PlanCompilerError,
    PlanValidationError,
    SchemaMismatchError,
)
from simplicio.plan_compiler.mapper_context import (
    DEV_CLI_FALLBACK_CONTEXT_SCHEMA,
    MAPPER_CONTEXT_SNAPSHOT_SCHEMA,
    MAPPER_CONTRACT_COMMIT,
    MAPPER_CONTRACT_MANIFEST_SHA256,
    MapperContextAdapter,
    MapperContextError,
    MapperContextView,
    load_mapper_context,
)
from simplicio.plan_compiler.models import (
    EFFECT_PLAN_SCHEMA,
    GOAL_ENVELOPE_SCHEMA,
    PLAN_COMPILER_COMPATIBILITY,
    PLAN_DAG_SCHEMA,
    VERIFICATION_PLAN_SCHEMA,
    EffectPlan,
    GoalEnvelope,
    PlanDAG,
    PlanNode,
    VerificationPlan,
)
from simplicio.plan_compiler.runtime_effect_sink import RuntimeEffectError, RuntimeEffectSink

__all__ = [
    "DEV_CLI_FALLBACK_CONTEXT_SCHEMA",
    "EFFECT_PLAN_SCHEMA",
    "GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION",
    "GOAL_ENVELOPE_SCHEMA",
    "GOAL_ENVELOPE_VERSION",
    "PLAN_COMPILER_COMPATIBILITY",
    "PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION",
    "PLAN_DAG_SCHEMA",
    "PLAN_DAG_VERSION",
    "VERIFICATION_PLAN_SCHEMA",
    "CompatAdapterError",
    "CompatAdapterExpiredError",
    "EffectDispatchContext",
    "EffectOutcome",
    "EffectPlan",
    "EffectSink",
    "GoalEnvelope",
    "IntegratedModeRequiresSinkError",
    "MAPPER_CONTRACT_COMMIT",
    "MAPPER_CONTRACT_MANIFEST_SHA256",
    "MAPPER_CONTEXT_SNAPSHOT_SCHEMA",
    "MapperContextAdapter",
    "MapperContextError",
    "MapperContextView",
    "PlanCompilationError",
    "PlanCompilerError",
    "PlanDAG",
    "PlanNode",
    "PlanValidationError",
    "RecordingEffectSink",
    "RuntimeEffectError",
    "RuntimeEffectSink",
    "SchemaMismatchError",
    "UnsupportedCompatVersionError",
    "VerificationPlan",
    "adapt_goal_envelope_inbound",
    "adapt_goal_envelope_outbound",
    "adapt_inbound",
    "adapt_outbound",
    "canonical_hash",
    "compile_task_spec_to_plan",
    "load_mapper_context",
]
