"""Pi adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="pi",
    name="Pi",
    source="https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md",
    markers=(".pi",),
    entry_verified=True,
    note="Docs: AGENTS.md context file. Pi discovers skills in .pi/skills/, not .claude/skills/; the AGENTS.md block points the agent at .claude/skills/.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
