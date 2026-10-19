"""Kilocode adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="kilocode",
    name="Kilocode",
    source="https://kilo.ai/docs/customize/agents-md",
    markers=(".kilo",),
    entry_verified=True,
    note="Docs: AGENTS.md first, AGENT.md as backup; also reads .claude/skills/.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
