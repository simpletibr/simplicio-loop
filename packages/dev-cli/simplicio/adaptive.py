"""Model-adaptive prompt helpers and lightweight task decomposition."""

from __future__ import annotations

import os
import re

WEAK_MODEL_HINTS = (
    "tiny",
    "small",
    "mini",
    "local",
    "3b",
    "7b",
    "8b",
    "qwen",
    "llama",
    "mistral",
)

# Strong non-Claude models that reliably produce unified diffs but may not
# follow the full DIFF + TEST + EVIDENCE multi-part output contract that
# Claude follows implicitly.  These models benefit from "diff-focused"
# validation: accept a valid diff without a mandatory inline TEST block.
DIFF_FOCUSED_MODEL_HINTS = (
    "glm",
    "deepseek",
    "gpt-",
    "gpt4",
    "gpt 4",
    "gpt-4",
    "gpt-5",
    "gemini",
    "o1",
    "o3",
    "o4",
    "mistral-large",
    "command-r",
    "yi-",
    "moonshot",
    "kimi",
    "k2",
    "llama3",
    "qwen2.5",
    "qwen3",
)


def _model_name(model: str | None = None) -> str:
    return (model or os.environ.get("SIMPLICIO_MODEL") or os.environ.get("MODEL") or "").lower()


def model_profile(model: str | None = None) -> dict[str, str]:
    name = _model_name(model)
    if any(hint in name for hint in WEAK_MODEL_HINTS):
        return {
            "name": name or "unknown",
            "tier": "scaffolded",
            "guidance": (
                "Use extra scaffolding, explicit file/path checks, short steps, "
                "and concrete verification before producing the final diff."
            ),
        }
    return {
        "name": name or "unknown",
        "tier": "efficient",
        "guidance": (
            "Use concise reasoning, rely on the mapper and precedents, and avoid redundant explanation."
        ),
    }


def model_tier(model: str | None = None) -> str:
    """Classify the model into a validation tier.

    Returns one of:

    - ``"claude-class"`` — Claude models that follow the full multi-part
      output contract (DIFF + TEST + EVIDENCE) reliably.  Validation
      requires both a diff and a TEST block.
    - ``"diff-focused"`` — Strong non-Claude models (GLM, DeepSeek, GPT,
      Gemini, etc.) that produce valid diffs but may skip the inline
      TEST block.  Validation accepts diff-only output.
    - ``"scaffolded"`` — Weak / local / small models.  Same relaxed
      validation as diff-focused (they cannot reliably produce tests).
    - ``"unknown"`` — No model set.  Defaults to strict validation.
    """
    name = _model_name(model)
    if not name:
        return "unknown"
    if "claude" in name or "anthropic" in name:
        return "claude-class"
    if any(hint in name for hint in DIFF_FOCUSED_MODEL_HINTS):
        return "diff-focused"
    if any(hint in name for hint in WEAK_MODEL_HINTS):
        return "scaffolded"
    # Default strong non-Claude model to diff-focused.  If the model
    # can't produce diffs either, the user should set
    # SIMPLICIO_VALIDATION_MODE or use claude-cli shell-out.
    return "diff-focused"


def get_validation_mode(model: str | None = None) -> str:
    """Return ``"strict"`` or ``"diff"`` for the output validator.

    Respects the ``SIMPLICIO_VALIDATION_MODE`` env var when set
    (``strict`` or ``diff``).  Otherwise derives from :func:`model_tier`:

    - claude-class / unknown → ``"strict"``
    - diff-focused / scaffolded → ``"diff"``
    """
    explicit = os.environ.get("SIMPLICIO_VALIDATION_MODE", "").strip().lower()
    if explicit in ("strict", "diff"):
        return explicit
    tier = model_tier(model)
    if tier in ("diff-focused", "scaffolded"):
        return "diff"
    return "strict"


def split_task(goal: str, max_steps: int = 6) -> list[str]:
    parts = [
        part.strip(" .")
        for part in re.split(r"\s*(?:;|\band\b|,|\bthen\b)\s*", goal, flags=re.I)
        if part.strip(" .")
    ]
    if len(parts) <= 1:
        return []
    return parts[:max_steps]


def build_adaptation_block(goal: str, model: str | None = None) -> str:
    profile = model_profile(model)
    tier = model_tier(model)
    lines = [
        "[MODEL ADAPTATION]",
        f"Model profile: {profile['tier']} ({profile['name']}).",
        f"Validation tier: {tier}.",
        profile["guidance"],
    ]
    if tier in ("diff-focused", "scaffolded"):
        lines.append(
            "Focus on producing a valid unified diff. "
            "A TEST block is optional — include it only if straightforward."
        )
        lines.append(
            "Example diff format:\n"
            "```diff\n"
            "diff --git a/path/to/file.py b/path/to/file.py\n"
            "new file mode 100644\n"
            "index 0000000..0000000\n"
            "--- /dev/null\n"
            "+++ b/path/to/file.py\n"
            "@@ -0,0 +1,10 @@\n"
            "+first line of the file\n"
            "+second line\n"
            "```"
        )
    steps = split_task(goal)
    if steps:
        lines.extend(["", "[TASK DECOMPOSITION]"])
        lines.extend(f"{i}. {step}" for i, step in enumerate(steps, start=1))
        lines.append("Complete each step in order; verify the relevant files before moving on.")
    return "\n".join(lines)
