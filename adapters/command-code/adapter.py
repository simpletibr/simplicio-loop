"""Command Code adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="command-code",
    name="Command Code",
    source="https://commandcode.ai/docs/memory",
    markers=(".commandcode",),
    entry_verified=True,
    note="Docs: reads AGENTS.md (not CLAUDE.md) at the project root or .commandcode/AGENTS.md.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
