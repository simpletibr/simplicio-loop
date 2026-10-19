"""Droid adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="droid",
    name="Droid",
    source="https://docs.factory.com/harness/agents-md",
    markers=(),
    entry_verified=True,
    note="Docs: AGENTS.md is the project briefing. The catalog URL (docs.factory.ai) redirects to docs.factory.com.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
