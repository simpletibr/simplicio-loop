"""Effect router: classify a task as ``Edit | Codegen | Llm`` before any tokens
are spent, and only ever let Runtime (``simplicio edit`` / ``execute_plan``)
apply the result.

Issue #709 (`feat(router): effect router Edit | Codegen | Llm — runtime apply
only`). #33 and #37 delivered the four LLM-reduction levers and the CST
codegen executors (``simplicio/scratch/codegen/``); that is mechanical scratch
generation, not this module. This module is the missing piece: the agent
classifies the task *before* spending tokens, and Runtime is the only thing
that ever writes bytes.

Rule (frozen enum first, per the issue body)::

    se da para apontar o trecho exato no arquivo  ->  EDIT
    senao, se a transformacao tem schema (AST/CST) ->  CODEGEN
    senao, e so entao                             ->  LLM
    depois de qualquer um                         ->  runtime apply + verify

``EffectMode`` is the frozen three-way enum. ``classify()`` implements the
routing rule against a Mapper survey. ``reject_full_file_llm_edit()`` /
``validate_llm_edit()`` implement the Mode 3 budget guard ("plano + edits,
nunca o arquivo inteiro"). ``EscalationState`` implements the certify-failure
retry/escalation contract ("retry no mesmo modo 1x; segunda falha sobe
Edit->Codegen->Llm. Nunca desce sem evidencia."). ``build_execution_report()``
assembles the ``simplicio.execution-report/v1`` receipt every apply must
produce.

This module never writes a file and never calls an LLM; it is pure
classification, validation and bookkeeping. The actual write path stays
``simplicio.mechanical_edit.execute_plan`` (Mode 1/pre-imaged) or the
whitelisted executors in ``simplicio.scratch.codegen.registry`` (Mode 2) —
this router only decides which one gets the task, and never reimplements
either.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

ROUTER_DECISION_SCHEMA = "simplicio.effect-router.decision/v1"
EXECUTION_REPORT_SCHEMA = "simplicio.execution-report/v1"

# Mode 3 budget guard: a Llm edit whose ``old`` is empty/blank and whose
# ``new`` is at or above this fraction of the current file's size is treated
# as full-file generation and rejected outright — "plano + edits, nunca o
# arquivo inteiro" (issue #709, Modo 3).
FULL_FILE_REJECT_RATIO = 0.9


class EffectMode(str, Enum):
    """The three-way effect enum issue #709 asks to freeze first."""

    MECHANICAL_EDIT = "mechanical_edit"
    CODEGEN = "codegen"
    LLM = "llm"


# Escalation only ever moves rightward through this tuple — "nunca desce sem
# evidencia" (never de-escalates without evidence).
_ESCALATION_ORDER: tuple[EffectMode, ...] = (
    EffectMode.MECHANICAL_EDIT,
    EffectMode.CODEGEN,
    EffectMode.LLM,
)


@dataclass(frozen=True)
class RouteDecision:
    """One ``classify()`` outcome.

    ``mode`` is ``None`` only for a refused route (ambiguous anchor, or a
    preimage miss). A refused route is fail-closed: the caller aborts rather
    than silently promoting the task to a more expensive mode on the first
    failure (Mode 1 contract: "preimage miss -> aborta, nao sobe LLM na
    primeira falha").
    """

    mode: EffectMode | None
    reason_code: str
    message: str
    refused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ROUTER_DECISION_SCHEMA,
            "mode": self.mode.value if self.mode is not None else None,
            "reason_code": self.reason_code,
            "message": self.message,
            "refused": self.refused,
        }


def _normalise_digest(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.removeprefix("sha256:")


def _hit_for(
    task: Mapping[str, Any],
    mapper_hits: Sequence[Mapping[str, Any]] | None,
) -> Mapping[str, Any] | None:
    if not mapper_hits:
        return None
    path = task.get("path")
    for hit in mapper_hits:
        if hit.get("path") == path:
            return hit
    return None


def _default_codegen_whitelist() -> set[str]:
    """The already-registered scratch codegen executors (issue #37).

    Issue #709 explicitly forbids opening a second, generic codegen engine
    here ("Reuse da whitelist ja existente em scratch/codegen/ (nao abrir
    motor generico)") — this router only reads the executor names that
    already exist.
    """
    try:
        from .scratch.codegen.registry import registered_executors
    except Exception:  # pragma: no cover - scratch subsystem is optional
        return set()
    return {executor.name for executor in registered_executors()}


def classify(
    task: Mapping[str, Any],
    mapper_hits: Sequence[Mapping[str, Any]] | None = None,
    *,
    codegen_registry: Sequence[str] | None = None,
) -> RouteDecision:
    """classify(task, mapper_hits) -> Edit | Codegen | Llm.

    ``task`` fields consulted (all optional except where noted):
      - ``path`` -- the file the task targets.
      - ``old`` -- candidate exact anchor text; combined with ``exact_span``.
      - ``exact_span`` -- ``True`` when the caller believes it can point at
        the exact span in the file.
      - ``expected_sha256`` -- the source hash the task was decided against
        (the Mapper generation that produced ``old``).
      - ``transform`` -- a named codegen transform, matched against
        ``codegen_registry``.

    ``mapper_hits`` is the Mapper survey restricted to ``task["path"]``: a
    sequence of ``{"path", "occurrences", "sha256"}`` rows.

    Routing:

    1. ``exact_span`` + a matching hit with exactly one occurrence -> Edit.
       If the hit's current ``sha256`` disagrees with the task's
       ``expected_sha256``, that is a **preimage miss**: refused, fail
       closed, never silently promoted to Llm.
       If the hit reports more than one occurrence, the anchor is
       ambiguous: refused, fail closed, same reason.
    2. Otherwise, a named ``transform`` on the codegen whitelist -> Codegen.
    3. Otherwise (0 hits, or genuine uncertainty) -> Llm, budgeted by
       ``validate_llm_edit``/``reject_full_file_llm_edit`` at apply time.
    """
    hit = _hit_for(task, mapper_hits)
    old = task.get("old")
    exact_span = bool(task.get("exact_span")) and isinstance(old, str) and bool(old)

    if exact_span and hit is not None:
        expected = _normalise_digest(task.get("expected_sha256"))
        observed = _normalise_digest(hit.get("sha256"))
        if expected is not None and observed is not None and expected != observed:
            return RouteDecision(
                mode=None,
                reason_code="preimage_miss",
                message=(
                    "Mapper survey hash has drifted since the task was decided "
                    f"for {task.get('path')!r}; abort, do not escalate on the first failure"
                ),
                refused=True,
            )
        occurrences = hit.get("occurrences")
        if occurrences == 1:
            return RouteDecision(
                mode=EffectMode.MECHANICAL_EDIT,
                reason_code="exact_span_unique",
                message=f"unique anchor found in {task.get('path')!r}",
            )
        if isinstance(occurrences, int) and occurrences > 1:
            return RouteDecision(
                mode=None,
                reason_code="ambiguous_anchor",
                message=f"anchor is ambiguous in {task.get('path')!r} ({occurrences} occurrences)",
                refused=True,
            )
        # occurrences == 0 (or missing/unknown) falls through to Codegen/Llm.

    transform = task.get("transform")
    whitelist = set(codegen_registry) if codegen_registry is not None else _default_codegen_whitelist()
    if isinstance(transform, str) and transform in whitelist:
        return RouteDecision(
            mode=EffectMode.CODEGEN,
            reason_code="codegen_whitelist_hit",
            message=f"named transform {transform!r} is a registered codegen executor",
        )

    return RouteDecision(
        mode=EffectMode.LLM,
        reason_code="no_exact_span_no_codegen_match",
        message="no unique anchor and no whitelisted transform; falling to a budgeted Llm plan",
    )


def reject_full_file_llm_edit(
    old: str | None,
    new: str,
    file_size: int,
    *,
    ratio: float = FULL_FILE_REJECT_RATIO,
) -> bool:
    """``True`` when a Llm edit looks like full-file generation.

    Mode 3 budget (issue #709): "output: plano + edits, nunca o arquivo
    inteiro. MCP reject se `old` vazio e `new` ~= tamanho do arquivo." An
    empty/blank ``old`` paired with a ``new`` payload at or above ``ratio``
    of the file's current byte size is rejected outright, independent of
    which tool (MCP or CLI) is asking.
    """
    if old:
        return False
    if file_size <= 0:
        return bool(new)
    return len(new) >= ratio * file_size


def validate_llm_edit(
    old: str | None,
    new: str,
    file_size: int,
    *,
    ratio: float = FULL_FILE_REJECT_RATIO,
) -> list[dict[str, Any]]:
    """Return a list of error dicts (empty when the edit is within budget).

    Shares the ``{"code", "message"}`` error shape used throughout
    ``simplicio.mechanical_edit`` so callers can append it to the same
    ``errors`` list without translation.
    """
    if reject_full_file_llm_edit(old, new, file_size, ratio=ratio):
        return [
            {
                "code": "full_file_generation_rejected",
                "message": (
                    "Llm plan rejected: empty/blank old with new approximately the size of the "
                    "whole file; Mode 3 budget forbids full-file generation, only plan + edits"
                ),
            }
        ]
    return []


@dataclass
class EscalationState:
    """Track certify-failure retry/escalation for one task across attempts.

    Contract (issue #709, Router step 5): "apply -> simplicio edit + deliver
    certify; certify falhou -> retry no mesmo modo 1x; segunda falha sobe
    Edit->Codegen->Llm. Nunca desce sem evidencia."

    ``record_failure()`` returns the mode the *next* attempt should use:
    the same mode on the first failure (a retry), the next mode in
    ``EffectMode`` order on a second consecutive failure in the same mode
    (with no intervening success). ``record_success()`` resets the retry
    counter for the current mode; it never moves ``mode`` backward.
    """

    mode: EffectMode
    _attempts_in_mode: int = field(default=0, init=False, repr=False)
    _history: list[EffectMode] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._history.append(self.mode)

    def record_failure(self) -> EffectMode:
        self._attempts_in_mode += 1
        if self._attempts_in_mode < 2:
            return self.mode
        index = _ESCALATION_ORDER.index(self.mode)
        if index + 1 >= len(_ESCALATION_ORDER):
            # Already at the terminal exception mode (Llm); nothing to
            # escalate to. Stay put -- the caller decides what "give up"
            # means for this task.
            return self.mode
        self.mode = _ESCALATION_ORDER[index + 1]
        self._attempts_in_mode = 0
        self._history.append(self.mode)
        return self.mode

    def record_success(self) -> None:
        self._attempts_in_mode = 0

    @property
    def history(self) -> tuple[EffectMode, ...]:
        """Every mode this task has run in, in escalation order, no repeats."""
        return tuple(self._history)


def _canonical_digest(value: Any) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_execution_report(
    *,
    mode: EffectMode,
    task: Mapping[str, Any],
    tokens: Mapping[str, int] | None = None,
    patches: Sequence[Mapping[str, Any]] | None = None,
    certify: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a ``simplicio.execution-report/v1`` receipt.

    Issue #709: "Receipt: `simplicio.execution-report/v1` com `mode`,
    tokens, patches, certify." This function only records what a downstream
    apply already did or planned (``execute_plan`` / a codegen executor /
    the Llm plan's edits); Runtime never invents text, and this receipt
    never invents evidence either -- callers pass in the real ``tokens``,
    ``patches`` and ``certify`` payloads they observed.
    """
    report: dict[str, Any] = {
        "schema": EXECUTION_REPORT_SCHEMA,
        "mode": mode.value,
        "task_path": task.get("path"),
        "tokens": dict(tokens) if tokens is not None else {"input": 0, "output": 0},
        "patches": [dict(patch) for patch in patches] if patches is not None else [],
        "certify": dict(certify) if certify is not None else {"status": "pending"},
    }
    report["report_digest"] = _canonical_digest(report)
    return report
