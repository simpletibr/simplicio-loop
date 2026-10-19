"""Codebuff adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="codebuff",
    name="Codebuff",
    source="https://www.codebuff.com/docs/help/faq",
    markers=(),
    entry_verified=True,
    note="Docs: one file per directory, in the order knowledge.md, AGENTS.md, CLAUDE.md; a knowledge.md beside the block takes precedence.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
