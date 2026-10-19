"""oh-my-pi adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="oh-my-pi",
    name="oh-my-pi",
    source="https://github.com/can1357/oh-my-pi/blob/main/docs/context-files.md",
    markers=(".omp",),
    entry_verified=True,
    note="Docs: AGENTS.md at the repository root is a context file. The skills folder is not stated on that page.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
