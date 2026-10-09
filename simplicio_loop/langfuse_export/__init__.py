"""Opt-in exporter from the loop's own records to Langfuse (issue #1595).

Off by default: nothing here runs unless ``langfuse_enabled = true`` in ``.simplicio-loop/loop.toml``
and credentials are present. Reads only ``simplicio.execution-report/v1`` and ``dashboard-event/v1``,
maps them (run = trace, task = span, gate = span + score, tokens only when MEASURED), queues the
payloads on disk and posts them in batches. See ``docs/LANGFUSE.md``.
"""

from __future__ import annotations

from .exporter import export_once, langfuse_dir

__all__ = ["export_once", "langfuse_dir"]
