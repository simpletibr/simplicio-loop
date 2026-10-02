"""Static assets of the Simplicio Live dashboard (issue #1399).

``static/components/`` holds the "Simplicio Live" kit: native Web Components (Custom Elements +
Shadow DOM, ES modules) with no build step and no runtime dependencies, shared with the
``simplicio-loop-marketing`` distribution panel. ``static/components.html`` is the static
catalog of every component in every state and theme.
"""
from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
COMPONENTS_DIR = STATIC_DIR / "components"
CATALOG_PAGE = STATIC_DIR / "components.html"

__all__ = ["CATALOG_PAGE", "COMPONENTS_DIR", "STATIC_DIR"]
