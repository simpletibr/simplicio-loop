"""Antigravity adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="antigravity",
    name="Antigravity",
    source="https://antigravity.google/docs/rules",
    markers=(),
    entry_verified=True,
    note="Docs: workspace rules are AGENTS.md, GEMINI.md or .agents/rules/*.md.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
