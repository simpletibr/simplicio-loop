"""Continue adapter: the rule file `.continue/rules/simplicio-loop.md` and the skills; the loop is self-paced.

The surface is `planner.HOST_LAYOUT["continue"]`, bound in `simplicio_loop/install/surface.py`.
"""
from simplicio_loop.install.surface import HostSurface

HOST = "continue"
_SURFACE = HostSurface(HOST, loop_drive="self_paced")
detect = _SURFACE.detect
verify = _SURFACE.verify
capabilities = _SURFACE.capabilities
