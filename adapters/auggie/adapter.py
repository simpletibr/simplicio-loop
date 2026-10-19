"""Auggie adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="auggie",
    name="Auggie",
    source="https://docs.augmentcode.com/cli/rules",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md at the workspace root is always loaded (also CLAUDE.md and .augment/rules/*.md).",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
