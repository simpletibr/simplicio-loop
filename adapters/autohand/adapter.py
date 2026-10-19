"""Autohand Code adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="autohand",
    name="Autohand Code",
    source="https://docs.autohand.ai/working-with-autohand-code/agents-md",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md at the project root (./AGENTS.md).",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
