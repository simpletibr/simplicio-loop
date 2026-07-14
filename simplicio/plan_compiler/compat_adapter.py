"""N-1 compatibility adapter for ``GoalEnvelope``/``PlanDAG`` (issue #167 slice 11/23).

PR #171 versioned ``producer_id``/``consumer_id`` onto ``GoalEnvelope`` and
``PlanDAG`` (see :mod:`simplicio.plan_compiler.models`); a later slice added
``budget`` to ``PlanDAG``, and a further slice added ``trace_id`` to
``PlanDAG`` *without* bumping ``PLAN_DAG_VERSION`` again — so ``trace_id``
is, for this adapter's purposes, part of the same "version 2" field set as
``budget``. All these additions follow the
``PLAN_COMPILER_COMPATIBILITY["contract"] == "additive-fields-within-major"``
rule: the ``schema`` string (``simplicio.plan-dag/v1`` etc.) never bumped its
major version, but the *field set* a producer/consumer agrees on did grow.

This module gives that field-level growth an explicit, small version number
per type — ``GOAL_ENVELOPE_VERSION`` / ``PLAN_DAG_VERSION`` below — so "N" and
"N-1" have a concrete meaning distinct from the (unchanged) schema major:

``GoalEnvelope``:
    - version 0 (N-1): no ``producer_id``/``consumer_id`` fields at all
      (pre-#171 shape).
    - version 1 (N, current): adds ``producer_id``/``consumer_id`` (#171).

``PlanDAG``:
    - version 1 (N-1): has ``producer_id``/``consumer_id`` (#171), no
      ``budget``. ``trace_id`` (#166) is an untouched passthrough field —
      it survives every hop by design (Golden E2E AC "preserva trace_id")
      and is not part of this version's field-set contract.
    - version 2 (N, current): adds ``budget``; ``trace_id`` was already
      passthrough at N-1 and keeps flowing unchanged.

Only the immediately-previous version (N-1) is supported by
``adapt_outbound``/``adapt_inbound`` below — this is a narrow compatibility
edge for one hop of rollback/rollforward, not a general schema-migration
framework. Anything older than N-1 is rejected with a clear error, per the
issue's invariant 6 ("Compatibilidade Hermes fica em uma borda registrada").

Expiry: per plan step 26 ("Retirar alias só pela policy #193"), this compat
surface is not permanent. ``GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION`` and
``PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION`` are the mechanical trigger — once the
*current* version constant above reaches (or exceeds) the matching expiry
constant, every adapter call for that type raises
``CompatAdapterExpiredError`` instead of silently continuing to translate.
Bumping ``GOAL_ENVELOPE_VERSION``/``PLAN_DAG_VERSION`` for a new additive
field is exactly the trigger that eventually retires this module; when that
happens, retire the *old* N-1 pair per the policy referenced above and
introduce a fresh pair for the new N/N-1 boundary.
"""

from __future__ import annotations

from typing import Any

from simplicio.plan_compiler.errors import PlanCompilerError
from simplicio.plan_compiler.models import GoalEnvelope, PlanDAG

# --- current ("N") version numbers ------------------------------------------

GOAL_ENVELOPE_VERSION = 1
PLAN_DAG_VERSION = 2

# --- expiry markers ----------------------------------------------------------
# Mechanical trigger: once the current version constant above reaches this
# threshold, the adapter refuses to run. Set to "current N + 2" so there is
# one full additive-field generation of headroom before removal is forced.

GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION = GOAL_ENVELOPE_VERSION + 2
PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION = PLAN_DAG_VERSION + 2


class CompatAdapterError(PlanCompilerError):
    """Base class for every N-1 compat-adapter rejection."""


class UnsupportedCompatVersionError(CompatAdapterError):
    """Raised when a caller asks for anything other than the N-1 boundary."""

    def __init__(self, type_name: str, requested: int, current: int) -> None:
        self.type_name = type_name
        self.requested = requested
        self.current = current
        expected = current - 1
        super().__init__(
            f"{type_name} compat adapter only supports N-1 (version {expected}); "
            f"got version {requested} against current version {current}"
        )


class CompatAdapterExpiredError(CompatAdapterError):
    """Raised once a type's current version reaches its expiry threshold."""

    def __init__(self, type_name: str, current: int, expires_at: int) -> None:
        self.type_name = type_name
        self.current = current
        self.expires_at = expires_at
        super().__init__(
            f"{type_name} N-1 compat adapter has expired: current version "
            f"{current} reached the expiry threshold {expires_at}; retire "
            "this adapter and, if a new N-1 boundary is still needed, "
            "introduce a fresh adapter pair for it (see #193 alias policy)"
        )


def _check_goal_envelope_not_expired() -> None:
    if GOAL_ENVELOPE_VERSION >= GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION:
        raise CompatAdapterExpiredError(
            "GoalEnvelope", GOAL_ENVELOPE_VERSION, GOAL_ENVELOPE_ADAPTER_EXPIRES_AT_VERSION
        )


def _check_plan_dag_not_expired() -> None:
    if PLAN_DAG_VERSION >= PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION:
        raise CompatAdapterExpiredError("PlanDAG", PLAN_DAG_VERSION, PLAN_DAG_ADAPTER_EXPIRES_AT_VERSION)


# --- GoalEnvelope N-1 <-> N ---------------------------------------------------


def adapt_goal_envelope_outbound(goal: GoalEnvelope, target_version: int) -> dict[str, Any]:
    """Downgrade a current (N) ``GoalEnvelope`` to an N-1-shaped dict.

    Rejects any ``target_version`` other than ``GOAL_ENVELOPE_VERSION - 1``.
    """
    _check_goal_envelope_not_expired()
    if target_version != GOAL_ENVELOPE_VERSION - 1:
        raise UnsupportedCompatVersionError("GoalEnvelope", target_version, GOAL_ENVELOPE_VERSION)
    payload = goal.to_dict()
    # version 0 predates producer_id/consumer_id (#171): drop them cleanly.
    payload.pop("producer_id", None)
    payload.pop("consumer_id", None)
    return payload


def adapt_goal_envelope_inbound(data: dict[str, Any], source_version: int) -> GoalEnvelope:
    """Upgrade an N-1-shaped ``GoalEnvelope`` dict into a current (N) instance.

    Rejects any ``source_version`` other than ``GOAL_ENVELOPE_VERSION - 1``.
    Fields that did not exist at N-1 (``producer_id``/``consumer_id``) are
    filled with their existing dataclass defaults (``""``).
    """
    _check_goal_envelope_not_expired()
    if source_version != GOAL_ENVELOPE_VERSION - 1:
        raise UnsupportedCompatVersionError("GoalEnvelope", source_version, GOAL_ENVELOPE_VERSION)
    upgraded = dict(data)
    upgraded.setdefault("producer_id", "")
    upgraded.setdefault("consumer_id", "")
    return GoalEnvelope.from_dict(upgraded)


# --- PlanDAG N-1 <-> N --------------------------------------------------------


def adapt_outbound(plan: PlanDAG, target_version: int) -> dict[str, Any]:
    """Downgrade a current (N) ``PlanDAG`` to an N-1-shaped dict.

    N-1 for ``PlanDAG`` (version ``PLAN_DAG_VERSION - 1``) has
    ``producer_id``/``consumer_id`` (#171) but no ``budget`` — an additive
    field that landed *within* the current ``PLAN_DAG_VERSION`` (see
    ``models.PlanDAG``) without a version bump of its own, so it drops
    cleanly here. ``trace_id`` (#166) is an untouched passthrough field that
    survives every hop by design (Golden E2E AC "preserva trace_id") and is
    kept as-is. Rejects any ``target_version`` other than
    ``PLAN_DAG_VERSION - 1`` with a clear error (only one hop of
    compatibility is supported).
    """
    _check_plan_dag_not_expired()
    if target_version != PLAN_DAG_VERSION - 1:
        raise UnsupportedCompatVersionError("PlanDAG", target_version, PLAN_DAG_VERSION)
    payload = plan.to_dict()
    payload.pop("budget", None)
    return payload


def adapt_inbound(data: dict[str, Any], source_version: int) -> PlanDAG:
    """Upgrade an N-1-shaped ``PlanDAG`` dict into a current (N) instance.

    Rejects any ``source_version`` other than ``PLAN_DAG_VERSION - 1``.
    ``budget`` (absent at N-1) is filled with its dataclass default
    (``None``, meaning "no budget ceiling"). ``trace_id`` is a passthrough
    field already present at N-1; the ``setdefault`` below only covers a
    caller that omitted it.
    """
    _check_plan_dag_not_expired()
    if source_version != PLAN_DAG_VERSION - 1:
        raise UnsupportedCompatVersionError("PlanDAG", source_version, PLAN_DAG_VERSION)
    upgraded = dict(data)
    upgraded.setdefault("budget", None)
    upgraded.setdefault("trace_id", None)
    upgraded.setdefault("producer_id", "")
    upgraded.setdefault("consumer_id", "")
    return PlanDAG.from_dict(upgraded)
