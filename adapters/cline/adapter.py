"""Cline adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="cline",
    name="Cline",
    source="https://docs.cline.bot/customization/cline-rules",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md is read next to .clinerules/. The skills folder is not stated on that page.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
