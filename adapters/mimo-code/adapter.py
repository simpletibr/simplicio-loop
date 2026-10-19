"""MiMo Code adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="mimo-code",
    name="MiMo Code",
    source="https://mimo.xiaomi.com/mimocode/rules",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md in the project root (CLAUDE.md fallback); user-level ~/.claude/skills/ is named.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
