"""hub_adapter.py — dev-cli as a deterministic Hub worker (issue #231, MVP slice).

Scope note (see ADR-006): the "Loop Hub" and "Runtime/Process Supervisor"
this issue describes are separate packages/repos (`simplicio-loop`,
`simplicio-runtime`) with no network contract published anywhere this repo
can consume today. Building an HTTP/gRPC client against an unspecified,
unpublished remote contract would be fabricating an integration, not
implementing one. What this module implements instead is the part of the
issue's plan that is genuinely local and safe:

- the propagated-identity contract (``HubTaskIdentity``) the issue's AC 3
  requires end to end;
- the ``mechanical | semantic | blocked`` router (AC 5), reusing the
  existing deterministic path (:mod:`simplicio.mechanical_edit`) as the
  zero-token "mechanical" route and the existing LLM path
  (:mod:`simplicio.pipeline`) as "semantic";
- the "no duplicate local scheduler while a Hub is driving" guardrail
  (AC 1 / plan step 12), wired into
  :meth:`simplicio.orchestrator.multi_task.TaskBatch.drain` via its new
  ``disallow_local_pool`` parameter;
- a ``doctor``-shaped status report.

Real Hub network wiring (claim/lease over the wire, capability negotiation
with a remote Runtime, cross-repo conformance) is out of scope here and is
registered as follow-up in ADR-006.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

HubMode = Literal["auto", "on", "off"]
Route = Literal["mechanical", "semantic", "blocked"]

_VALID_MODES = ("auto", "on", "off")


def resolve_hub_mode(explicit: str | None = None) -> HubMode:
    """Resolve `--hub {auto,on,off}` (AC 11): explicit CLI flag wins over
    `SIMPLICIO_HUB`, which wins over the `auto` default. An unrecognized
    value falls back to `auto` rather than erroring — the same fail-open
    posture as the rest of this package's env parsing (e.g.
    `pipeline._resolve_max_attempts`)."""
    raw = (explicit if explicit is not None else os.environ.get("SIMPLICIO_HUB", "")).strip().lower()
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    return "auto"


class HubModeBlocked(RuntimeError):
    """Raised when `mode="on"` is requested but a required precondition —
    complete propagated identity, or a routable task — is missing. This is
    the explicit, logged failure the issue's AC demands in place of a
    silent standalone fallback (mirrors the map_view.py / ADR-005 principle:
    reject incompatible/incomplete state loudly, never silently)."""


@dataclass(frozen=True)
class HubTaskIdentity:
    """The identifiers issue #231 AC 3 requires propagated end to end:
    ecosystem/run/task/attempt/lease/fence/trace/idempotency."""

    ecosystem_id: str = ""
    run_id: str = ""
    task_id: str = ""
    attempt: int = 1
    lease: str = ""
    fence: int = 0
    trace_id: str = ""
    idempotency_key: str = ""

    def is_complete(self) -> bool:
        """The minimum subset a Hub-driven attempt cannot safely proceed
        without: which run/task this is, which lease authorizes mutating
        it, and an idempotency key so a retried attempt cannot double-apply."""
        return bool(self.run_id and self.task_id and self.lease and self.idempotency_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ecosystem_id": self.ecosystem_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "attempt": self.attempt,
            "lease": self.lease,
            "fence": self.fence,
            "trace_id": self.trace_id,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_env(cls) -> HubTaskIdentity:
        """Read the propagated identity from env vars a Hub-launched
        process would set — the same convention this package already uses
        for out-of-band context (e.g. `SIMPLICIO_MODEL`, `SIMPLICIO_ROOT`)."""
        raw_attempt = os.environ.get("SIMPLICIO_HUB_ATTEMPT", "1").strip()
        raw_fence = os.environ.get("SIMPLICIO_HUB_FENCE", "0").strip()
        try:
            attempt = int(raw_attempt) if raw_attempt else 1
        except ValueError:
            attempt = 1
        try:
            fence = int(raw_fence) if raw_fence else 0
        except ValueError:
            fence = 0
        return cls(
            ecosystem_id=os.environ.get("SIMPLICIO_HUB_ECOSYSTEM_ID", ""),
            run_id=os.environ.get("SIMPLICIO_HUB_RUN_ID", ""),
            task_id=os.environ.get("SIMPLICIO_HUB_TASK_ID", ""),
            attempt=attempt,
            lease=os.environ.get("SIMPLICIO_HUB_LEASE", ""),
            fence=fence,
            trace_id=os.environ.get("SIMPLICIO_HUB_TRACE_ID", ""),
            idempotency_key=os.environ.get("SIMPLICIO_HUB_IDEMPOTENCY_KEY", ""),
        )


def route_task(*, plan: dict[str, Any] | None, goal: str) -> Route:
    """`mechanical | semantic | blocked` (issue #231 AC 5 / plan step 5).

    `mechanical`: `plan` already carries the deterministic operations shape
    :func:`simplicio.mechanical_edit.execute_plan_json` consumes — zero LLM
    tokens (AC: "Edição mecânica consome zero tokens").
    `semantic`: no mechanical plan, but a goal exists for the LLM path
    (:mod:`simplicio.pipeline`).
    `blocked`: neither — nothing this adapter can route.
    """
    if isinstance(plan, dict):
        operations = plan.get("operations")
        if isinstance(operations, list) and operations:
            return "mechanical"
    if goal.strip():
        return "semantic"
    return "blocked"


@dataclass
class HubTaskAdapter:
    """The per-task adapter: resolves mode, identity, and routing, and
    exposes the guardrails/status the issue's AC set requires."""

    mode: HubMode
    identity: HubTaskIdentity

    @classmethod
    def create(cls, *, mode: str | None = None) -> HubTaskAdapter:
        return cls(mode=resolve_hub_mode(mode), identity=HubTaskIdentity.from_env())

    def guard_identity(self) -> None:
        """AC: a Hub-driven run must not silently fall back to standalone
        behavior when the identity it needs hasn't actually been propagated."""
        if self.mode == "on" and not self.identity.is_complete():
            raise HubModeBlocked(
                "hub mode=on requires run_id/task_id/lease/idempotency_key "
                "to be propagated from the Hub (SIMPLICIO_HUB_RUN_ID, "
                "SIMPLICIO_HUB_TASK_ID, SIMPLICIO_HUB_LEASE, "
                "SIMPLICIO_HUB_IDEMPOTENCY_KEY) — refusing to fall back to "
                "standalone behavior silently"
            )

    def route(self, *, plan: dict[str, Any] | None, goal: str) -> Route:
        route = route_task(plan=plan, goal=goal)
        if self.mode == "on" and route == "blocked":
            raise HubModeBlocked(
                "task has neither a mechanical plan (dict with a non-empty "
                "'operations' list) nor a goal to route semantically"
            )
        return route

    @property
    def local_scheduler_allowed(self) -> bool:
        """False in `mode="on"` — issue #231 AC 1 / plan step 12: no local
        pool/scheduler may run while a Hub owns concurrency. Callers pass
        this through to `TaskBatch.drain(disallow_local_pool=...)`."""
        return self.mode != "on"

    def doctor_status(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.hub-adapter-status/v1",
            "mode": self.mode,
            "identity": self.identity.to_dict(),
            "identity_complete": self.identity.is_complete(),
            "local_scheduler_allowed": self.local_scheduler_allowed,
        }
