"""Arm specs for the ablation benchmark (issue #1337; issue #1343 dropped the
Fast arms when the Fast operator was removed from the stack entirely).

Five arms vary which Simplicio operators (mapper, dev-cli) and skills the
real OpenCode agent has, isolating each operator's individual and paired
contribution to cost/speed against the ``normal`` (nothing installed)
baseline and the ``simplicio`` (full loop) reference:

    normal        -- no skill, no simplicio-* binary on PATH
    mapper        -- simplicio-mapper only
    devcli        -- simplicio-dev-cli only
    mapper-devcli -- simplicio-mapper + simplicio-dev-cli
    simplicio     -- simplicio-loop skill, ALL binaries on PATH (reference)

Each spec is ``{"skills": [...], "bins": [...], "prompt_prefix": str}``:

- ``skills``: skill directory NAMES under ``.claude/skills/`` to copy into
  the arm's repo (``opencode_agent.install_skills``).
- ``bins``: ``simplicio-*`` binary basenames allowed on the arm's isolated
  PATH (``opencode_agent.build_arm_path``) -- an arm never sees a binary
  outside this list, so a divergent result can be attributed to the tools
  actually available rather than an isolation leak.
- ``prompt_prefix``: text prepended to the task prompt. The single/pair
  arms spell out exactly which tools are installed and forbid the rest, so
  the model never tries a binary that isn't on its PATH; ``simplicio`` uses
  the existing ``/simplicio-loop `` slash-command convention; ``normal`` has
  no prefix at all.
"""
from __future__ import annotations

MAPPER_BIN = "simplicio-mapper"
DEVCLI_BIN = "simplicio-dev-cli"
LOOP_BIN = "simplicio-loop"

ALL_BINS = (MAPPER_BIN, DEVCLI_BIN, LOOP_BIN)


def _only_prefix(*named: tuple[str, str]) -> str:
    """``named`` is ``(binary, skill)`` pairs. Builds the shared
    "use only these tools" directive so every single/pair arm's prompt
    names its skill(s) and forbids every other ``simplicio-*`` binary."""
    tools = " and ".join(f"{binary} (skill {skill})" for binary, skill in named)
    return (
        f"Use only these tools for this task: {tools}. Do not invoke any "
        "other simplicio-* binary; none other is installed. "
    )


ARM_SPECS: dict[str, dict] = {
    "normal": {
        "skills": [],
        "bins": [],
        "prompt_prefix": "",
    },
    "mapper": {
        "skills": ["simplicio-mapper"],
        "bins": [MAPPER_BIN],
        "prompt_prefix": _only_prefix((MAPPER_BIN, "simplicio-mapper")),
    },
    "devcli": {
        "skills": ["simplicio-dev-cli"],
        "bins": [DEVCLI_BIN],
        "prompt_prefix": _only_prefix((DEVCLI_BIN, "simplicio-dev-cli")),
    },
    "mapper-devcli": {
        "skills": ["simplicio-mapper", "simplicio-dev-cli"],
        "bins": [MAPPER_BIN, DEVCLI_BIN],
        "prompt_prefix": _only_prefix(
            (MAPPER_BIN, "simplicio-mapper"), (DEVCLI_BIN, "simplicio-dev-cli"),
        ),
    },
    "simplicio": {
        "skills": ["simplicio-loop"],
        "bins": list(ALL_BINS),
        "prompt_prefix": "/simplicio-loop ",
    },
}

# Table order matters: it is the canonical arm ordering for the ablation
# report and the CLI's ``--arms`` validation set.
ARM_NAMES: tuple[str, ...] = tuple(ARM_SPECS.keys())


def spec(arm: str) -> dict:
    """The spec dict for ``arm``, or a ``ValueError`` naming the valid set."""
    try:
        return ARM_SPECS[arm]
    except KeyError:
        raise ValueError(f"unknown arm {arm!r}; choose from {ARM_NAMES}") from None
