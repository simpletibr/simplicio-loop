"""Simplicio Agent (formerly Hermes) adapter: the skill copy; the loop is the native one.

The native loop is what adapters/simplicio_agent/README.md documents; this tree does not measure it, so the live status
stays UNVERIFIED. The surface is `planner.HOST_LAYOUT["simplicio_agent"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "simplicio_agent"
_SURFACE = HostSurface(HOST, loop_drive="native_loop")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
