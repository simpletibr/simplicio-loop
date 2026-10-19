"""Command Code adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="command-code",
    name="Command Code",
    source="https://commandcode.ai/docs/memory",
    markers=(".commandcode",),
    entry_verified=True,
    note="Docs: reads AGENTS.md (not CLAUDE.md) at the project root or .commandcode/AGENTS.md.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
