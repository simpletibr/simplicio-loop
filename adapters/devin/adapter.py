"""Devin adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="devin",
    name="Devin",
    source="https://docs.devin.ai/onboard-devin/agents-md",
    markers=(),
    entry_verified=True,
    note="Docs: Devin looks for AGENTS.md in the repository before it starts coding.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
