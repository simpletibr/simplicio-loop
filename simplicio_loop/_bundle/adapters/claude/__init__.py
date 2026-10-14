"""Claude Code host adapter (Plugin v1 / L03)."""

from .adapter import (
    SCHEMA,
    AdapterError,
    capabilities,
    decide,
    descriptor,
    detect,
    handshake,
    verify_shipped_hooks,
)

__all__ = [
    "SCHEMA",
    "AdapterError",
    "capabilities",
    "decide",
    "descriptor",
    "detect",
    "handshake",
    "verify_shipped_hooks",
]
