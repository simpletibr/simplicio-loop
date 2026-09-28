"""simplicio-loop — The Universal Looping AI Orchestrator.

A runtime-agnostic super-plugin (7 skills + loop/token hooks) that drains any
queue of work end-to-end on any LLM/runtime. This package ships the skills and
hooks and installs them into a runtime's skills location.
"""

# Single source of truth = the package metadata (pyproject `version`); the literal is only a
# fallback for an editable/source checkout that was never installed. No more version drift.
try:
    from importlib.metadata import version as _v, PackageNotFoundError

    try:
        __version__ = _v("simplicio-loop")
    except PackageNotFoundError:
        __version__ = "3.43.17"
except Exception:  # pragma: no cover
    __version__ = "3.43.17"
