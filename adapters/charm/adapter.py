"""Charm adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="charm",
    name="Charm",
    source="https://github.com/charmbracelet/crush",
    markers=(),
    entry_verified=True,
    note="Docs: Crush includes AGENTS.md by default and reads .claude/skills/ (project and ~/.claude/skills/).",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
