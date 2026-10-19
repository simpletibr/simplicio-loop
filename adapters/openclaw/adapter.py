"""OpenClaw adapter: the skills under `.agents/skills` (where OpenClaw scans); the loop runs on its scheduler.

OpenClaw does not scan `.claude/skills`, so the surface names `.agents/skills`. The native scheduler is what the
adapters/openclaw/README.md documents; it is not measured here, so the live status stays UNVERIFIED.
The surface is `planner.HOST_LAYOUT["openclaw"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "openclaw"
_SURFACE = HostSurface(HOST, loop_drive="native_scheduler")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
