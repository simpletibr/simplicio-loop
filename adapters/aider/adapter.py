"""Aider adapter: `CONVENTIONS.md`, read through `.aider.conf.yml`; the loop is self-paced from the shell.

Aider loads a file only when its config names it under `read:`, so the surface is the conventions file plus that
config. The surface is `planner.HOST_LAYOUT["aider"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "aider"
_SURFACE = HostSurface(HOST, loop_drive="self_paced")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
