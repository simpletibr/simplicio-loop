"""Gemini CLI adapter: `GEMINI.md` and the skills; the loop is self-paced.

The surface is `planner.HOST_LAYOUT["gemini"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "gemini"
_SURFACE = HostSurface(HOST, loop_drive="self_paced")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
