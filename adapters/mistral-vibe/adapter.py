"""Mistral Vibe adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="mistral-vibe",
    name="Mistral Vibe",
    source="https://github.com/mistralai/mistral-vibe",
    markers=(".vibe",),
    entry_verified=True,
    note="Docs: AGENTS.md from the working directory upward. Skills are discovered in .vibe/skills/ and .agents/skills/, not .claude/skills/.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
