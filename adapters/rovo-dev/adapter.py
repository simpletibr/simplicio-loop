"""Rovo Dev adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="rovo-dev",
    name="Rovo Dev",
    source="https://support.atlassian.com/rovo/docs/use-memory-in-rovo-dev-cli/",
    markers=(),
    entry_verified=True,
    note="Docs: project memory is stored in AGENTS.md and AGENTS.local.md.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
