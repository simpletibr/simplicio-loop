"""Kimi adapter: `.claude/skills/` + `AGENTS.md`, self-paced.

The row below is the host's whole adapter; the behaviour is shared in simplicio_loop/install/surface.py.
"""
from simplicio_loop.install.surface import HostSurface

HOST = HostSurface(
    host="kimi",
    name="Kimi",
    source="https://moonshotai.github.io/kimi-code/en/customization/agents.html",
    markers=(".kimi-code",),
    entry_verified=True,
    note="Docs: project instructions are AGENTS.md or .kimi-code/AGENTS.md.",
)
detect = HOST.detect
capabilities = HOST.capabilities
decide = HOST.decide
verify_shipped_hooks = HOST.verify_shipped_hooks
