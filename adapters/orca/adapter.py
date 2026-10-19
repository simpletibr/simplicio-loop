"""OrcaDev / Orca ADE adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="orca-dev",
    name="OrcaDev / Orca ADE",
    source="https://www.onorca.dev/docs/agents/supported",
    markers=(),
    entry_verified=False,
    note="UNVERIFIED: neither the supported-agents page nor the docs index names AGENTS.md. Client opt-in only: installed by name, never by --host all.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
