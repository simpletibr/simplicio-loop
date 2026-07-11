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

# Optional Rust hot-path (issues #17/#18). If `simplicio_core` is installed
# (built via `cd rust/simplicio-core && maturin develop --release`), the
# substitution + comment-strip step runs ~5x faster. The Python fallback
# below stays the source of truth and is what pip-installed users get
# until a wheel ships.
try:
    from simplicio_core import build_6layer_prompt as _rs_build
except ImportError:  # pragma: no cover - exercised at import time
    _rs_build = None


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
    """Python reference implementation — exact contract the Rust impl mirrors."""
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
    if _rs_build is not None:
        return _rs_build(tpl, stack, goal, target_block, prec, skill, adaptation, criteria, constraints)
    return _assemble_python(tpl, stack, goal, target_block, prec, skill, adaptation, criteria, constraints)


def latest_prompt_envelope() -> PromptEnvelope | None:
    return _LAST_PROMPT_ENVELOPE


def set_prompt_retry_delta(
    *, reason: str, failure_class: str, diagnostics: str, affected_files: list[str]
) -> None:
    global _LAST_PROMPT_ENVELOPE
    if _LAST_PROMPT_ENVELOPE is not None:
        _LAST_PROMPT_ENVELOPE = _LAST_PROMPT_ENVELOPE.with_retry_delta(
            reason=reason,
            failure_class=failure_class,
            diagnostics=diagnostics,
            affected_files=affected_files,
        )
