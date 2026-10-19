"""Amp adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="amp",
    name="Amp",
    source="https://ampcode.com/docs/customize/agents-md",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md is the primary file (AGENT.md and CLAUDE.md only where a directory has none).",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
