"""Effect-sink boundary for "modo integrado" (issues #166, #167).

Both #166 ("No modo integrado, zero escrita/commit fora da Effect API do
Runtime") and #167 ("Modo integrado não executa writes diretamente") name
the same invariant: when the Dev CLI runs in integrated mode, it must never
apply an effect (write a file, run ``git apply``, commit) itself. Its job in
that mode is only to compile a ``PlanDAG``/``EffectPlan`` (see
:mod:`simplicio.plan_compiler.compile_task_spec`) and hand the ``EffectPlan``
to whatever authorizes and applies it.

That "whatever" is the real ``simplicio-runtime`` Effect API — tracked
upstream as Runtime issues #3134/#3135, which do not exist as importable
code in this repository. This module defines the local, typed boundary the
Dev CLI calls into instead: an ``EffectSink`` callable that
:func:`simplicio.pipeline.run_task` invokes once per compiled ``EffectPlan``
when ``mode="integrated"``. This is a **stub boundary**, not the Runtime
itself — swapping in a real sink that talks to ``simplicio-runtime`` over
its future Effect API is the intended integration point once that API
ships. Until then, :class:`RecordingEffectSink` is the reference
implementation: it records every ``EffectPlan`` it receives and applies
none of them, which is what proves (in tests) that the contract holds
without a real Runtime.

``pipeline.run_task`` refuses to proceed in integrated mode when no sink is
provided — it never silently falls back to direct writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from simplicio.plan_compiler.models import EffectPlan


@dataclass(frozen=True)
class EffectApplyResult:
    """What a sink reports back after receiving one ``EffectPlan``.

    ``accepted`` only means the sink took custody of the effect (e.g. queued
    it for the Runtime to authorize) — it does NOT mean the effect was
    applied to any worktree. Applying the effect is exclusively the
    Runtime's job once its Effect API exists.
    """

    effect_id: str
    accepted: bool
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class EffectSink(Protocol):
    """Callable boundary: receives one ``EffectPlan``, never applies it.

    A concrete implementation may forward the ``EffectPlan`` to
    ``simplicio-runtime``'s Effect API (once it exists), to a message queue,
    or — for tests — simply record it. It must never itself write to the
    worktree, run ``git apply``, or otherwise mutate persistent state; that
    authority belongs to the Runtime.
    """

    def __call__(self, effect: EffectPlan) -> EffectApplyResult: ...


class IntegratedModeRequiresSinkError(RuntimeError):
    """Raised when ``mode="integrated"`` runs without an ``effect_sink``.

    Integrated mode must refuse to proceed rather than silently falling
    back to direct writes when no sink is configured — see #166/#167.
    """


class RecordingEffectSink:
    """Reference no-op ``EffectSink``: records ``EffectPlan``s, applies none.

    This is the sink used by this repository's own tests to prove the
    integrated-mode contract (compile a plan, hand it to the sink, never
    touch the worktree) without needing the real ``simplicio-runtime``
    Effect API to exist. Production integrations should replace this with
    a sink that actually forwards to the Runtime.
    """

    def __init__(self) -> None:
        self.received: list[EffectPlan] = []

    def __call__(self, effect: EffectPlan) -> EffectApplyResult:
        self.received.append(effect)
        return EffectApplyResult(
            effect_id=effect.effect_id,
            accepted=True,
            detail="recorded by local stub sink; not applied (no Runtime Effect API wired yet)",
        )
