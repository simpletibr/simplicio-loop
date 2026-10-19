"""GitHub Copilot adapter: repository instructions and the skills; the loop is self-paced (no stop hook).

The surface is `planner.HOST_LAYOUT["github-copilot"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "github-copilot"
_SURFACE = HostSurface(HOST, loop_drive="self_paced")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
