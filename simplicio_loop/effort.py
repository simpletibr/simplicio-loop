"""Per-phase LLM reasoning-effort hints (issue #1310 follow-up).

`simplicio-loop` never calls an LLM itself -- the HOST (Claude Code, Codex,
Cursor, ...) does, on every turn. This module is the single source of truth
for which reasoning effort each phase of the plan-once/apply-once hot path
should run at, so the host can honor it without either side re-deriving the
mapping:

- ``plan``    (the host writing ops.json from ``orient --brief``'s output)
  -> ``high``   -- the one step that decides the exact find/replace text;
                   worth spending reasoning budget on.
- ``execute`` (the host running ``simplicio-loop apply``, or fixing a
  mechanical BLOCKED/FAIL from it) -> ``low`` -- deterministic tool-driven
  work; the operators (dev-cli/mapper), not the LLM, do the heavy lifting.
- ``review``  (the host reviewing an ``apply`` PASS result / declaring done)
  -> ``medium`` -- enough budget to catch a real problem without paying for
                   ``high`` on a mostly-mechanical check.

Both ``orient --brief`` (``cli_impl.orient_brief``) and ``apply`` (via
``next_effort_for_status``) import this table rather than hardcoding their
own copy.
"""
from __future__ import annotations

PHASE_EFFORT: dict[str, str] = {
    "plan": "high",
    "execute": "low",
    "review": "medium",
}


def next_effort_for_status(status: str) -> str:
    """Effort for the turn that follows an ``apply`` result of ``status``.

    ``PASS`` -> the next turn reviews the result (or declares done):
    ``PHASE_EFFORT["review"]``. Anything else (``BLOCKED``, ``FAIL``, or an
    unrecognized status) -> a mechanical fix turn with the exact failing
    find/check tail already in hand: ``PHASE_EFFORT["execute"]``.
    """
    if status == "PASS":
        return PHASE_EFFORT["review"]
    return PHASE_EFFORT["execute"]
