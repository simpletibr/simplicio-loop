"""prompt.py — stacks the prompt layers."""

import os
import re
from functools import lru_cache

from .adaptive import build_adaptation_block
from .mapper import build_mapper_context
from .precedent import build_precedent_block
from .prompt_envelope import PromptEnvelope
from .skill_router import build_skill_block

_LAST_PROMPT_ENVELOPE: PromptEnvelope | None = None


@lru_cache(maxsize=4)
def _load_template(path: str) -> str:
    """Read the template once per process; it is a static file on disk."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _mapper(root, target, goal=""):
    return build_mapper_context(root, target, goal=goal)


def _assemble_python(
    tpl: str,
    stack: str,
    goal: str,
    target_block: str,
    prec: str,
    skill: str,
    adaptation: str,
    criteria: str,
    constraints: str,
) -> str:
    """Substitute the 6-layer template placeholders and strip `{# ... #}` comments."""
    for s, v in {
        "{{STACK}}": stack,
        "{{GOAL}}": goal,
        "{{TARGET}}": target_block,
        "{{PRECEDENT}}": prec,
        "{{SKILL}}": skill,
        "{{ADAPTATION}}": adaptation,
        "{{CRITERIA}}": criteria,
        "{{CONSTRAINTS}}": constraints,
    }.items():
        tpl = tpl.replace(s, v)
    return re.sub(r"\{#.*?#\}", "", tpl, flags=re.DOTALL).strip()


def build_prompt(root, stack, goal, target, criteria, constraints):
    tpl_path = os.path.join(os.path.dirname(__file__), "templates", "simplicio_prompt.md")
    tpl = _load_template(tpl_path)
    prec = build_precedent_block(root, stack, goal, k=2)
    skill = build_skill_block(root, goal)
    target_block = f"{target}\n\nTarget context:\n{_mapper(root, target, goal=goal)}"
    adaptation = build_adaptation_block(goal)
    global _LAST_PROMPT_ENVELOPE
    envelope = PromptEnvelope.from_layers(
        {
            "policy": "Simplicio execution policy",
            "goal": goal,
            "target": target_block,
            "precedent": prec,
            "skill": skill,
            "adaptation": adaptation,
            "acceptance": criteria,
            "constraints": constraints,
        },
        template_version="simplicio_prompt.md/v1",
    )
    _LAST_PROMPT_ENVELOPE = envelope
    return _assemble_python(tpl, stack, goal, target_block, prec, skill, adaptation, criteria, constraints)


def latest_prompt_envelope() -> PromptEnvelope | None:
    return _LAST_PROMPT_ENVELOPE


def set_prompt_retry_delta(
    *, reason: str, failure_class: str, diagnostics: str, affected_files: list[str]
) -> str | None:
    global _LAST_PROMPT_ENVELOPE
    if _LAST_PROMPT_ENVELOPE is None:
        return None
    _LAST_PROMPT_ENVELOPE = _LAST_PROMPT_ENVELOPE.with_retry_delta(
        reason=reason,
        failure_class=failure_class,
        diagnostics=diagnostics,
        affected_files=affected_files,
    )
    return _LAST_PROMPT_ENVELOPE.render_retry_delta()
