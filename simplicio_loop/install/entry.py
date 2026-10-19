"""The marker block Loop writes into a host's entry file (AGENTS.md, GEMINI.md, ...), and the files a host reads that
need more than the block.

Two installers write these: the packaged `simplicio-loop install` (planner.py) and the checkout installer
(scripts/install_lib.py). Both call `body_for`, `merge` and `remove` here, so they write the same bytes and never fight
over the block. Loop owns only the block; the rest of a file that already existed stays the user's. Standard library
only: the checkout installer imports this module too.
"""
from __future__ import annotations

BEGIN = "<!-- simplicio-loop:begin -->"
END = "<!-- simplicio-loop:end -->"
LEGACY_BEGIN = "<!-- simplicio-tasks:begin -->"
LEGACY_END = "<!-- simplicio-tasks:end -->"
# A rule file the host reads with YAML frontmatter first: Continue ignores a `.continue/rules/*.md` file without it.
FRONTMATTER = {".continue/rules/simplicio-loop.md": "---\nname: simplicio-loop\nalwaysApply: true\n---\n"}
# A config file the host reads instead of a markdown instructions file: aider loads only what this lists under `read:`.
CONFIG = {".aider.conf.yml": "read:\n  - CONVENTIONS.md\n  - .claude/skills/simplicio-loop/SKILL.md\n"}


def block(skills_root: str = ".claude/skills") -> str:
    """The block, from BEGIN to END (no trailing newline). `skills_root` is where the skill copy the block names lives:
    the project's `.claude/skills`, or `~/.claude/skills` in a user-level file."""
    body = (
        BEGIN + "\n"
        "## simplicio-loop — Unified Core + Loop (multi-LLM floor)\n\n"
        f"Load and follow `{skills_root}/simplicio-loop/SKILL.md` and companions "
        "(`simplicio-orient`, `simplicio-review`, `simplicio-compress`, `simplicio-learn`, "
        "`simplicio-autoresearch`; `simplicio-tasks` = legacy alias) **IN FULL**.\n\n"
        "**Operator floor (Claude / Codex / Grok / Cursor / VS Code / Antigravity / Kiro / Hermes):**\n"
        "1. Arm STRICT env (`SIMPLICIO_LOOP_STRICT=1`, `FORBID_HAND_EDIT=1`, "
        "`EXECUTION_PROFILE=standalone`). There is no Runtime/MCP backend in this stack.\n"
        "2. `simplicio-loop preflight --strict --json` before work.\n"
        "3. Core: survey with `simplicio-mapper`; mutate with "
        "`simplicio-dev-cli edit --plan` — not host Write/Edit under STRICT.\n"
        "4. Host integrations (Orca, boards, chat) **only if the client requested** them "
        "(`docs/CLIENT_INTEGRATIONS.md`).\n"
        "5. Evidence-gated close/PR; MEASURED|/UNVERIFIED|; no theater ACs.\n"
        "6. Self-paced hosts re-read `.simplicio-loop/orchestrator/loop/scratchpad.md` every turn.\n\n"
        "Rules: `packaging/host-rules/simplicio-loop-operator-flow.md` · "
        "`docs/MULTI_LLM_CONTRACT.md` · clamp: `python3 hooks/orient_clamp.py -- <cmd>`.\n"
    )
    body += (
        "\nInvoke: `/simplicio-loop <body of work>` · "
        "Prism drain: `python3 scripts/arm_drain_prism.py --repo . --slots 4 --json`\n"
        + END
    )
    return body


def merge(existing: str, skills_root: str = ".claude/skills") -> str:
    """`existing` with the block in place: appended below the user's text, or refreshed where it already is.

    A legacy `simplicio-tasks` block is replaced by the current one, where it stands.
    """
    begin, end = _markers(existing)
    if begin is None:
        return (existing.rstrip() + "\n\n" if existing.strip() else "") + block(skills_root) + "\n"
    pre = existing.split(begin)[0].rstrip()
    post = existing.split(end, 1)[1]
    return (pre + "\n\n" if pre else "") + block(skills_root) + post


def body_for(rel: str, existing: str, skills_root: str = ".claude/skills") -> str:
    """The text of the entry file `rel` once Loop's block is in it. A file that does not exist yet starts with the
    frontmatter its host reads first, and a file that lacks that frontmatter gets it in front."""
    front = FRONTMATTER.get(rel, "")
    text = merge(existing or front, skills_root)
    if front and not text.startswith("---"):
        text = front + "\n" + text
    return text


def remove(existing: str) -> str | None:
    """`existing` without the block, or None when there is no block. Text the user wrote around it stays."""
    start = existing.find(BEGIN)
    if start < 0:
        return None
    stop = existing.find(END, start)
    if stop < 0:
        return None
    stop += len(END)
    head = existing[:start].rstrip()
    tail = existing[stop:].lstrip("\n")
    return (head + "\n" if head else "") + tail


def _markers(existing: str) -> tuple[str | None, str | None]:
    if BEGIN in existing and END in existing:
        return BEGIN, END
    if LEGACY_BEGIN in existing and LEGACY_END in existing:
        return LEGACY_BEGIN, LEGACY_END
    return None, None
