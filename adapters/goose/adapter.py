"""goose adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in adapters/agents_md.py.
"""
from adapters.agents_md import AgentsMdHost

HOST = AgentsMdHost(
    host="goose",
    name="goose",
    source="https://goose-docs.ai/docs/guides/context-engineering/using-goosehints/",
    markers=(),
    entry_verified=True,
    note="Docs: goose loads AGENTS.md and .goosehints by default at every level of the working directory.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
