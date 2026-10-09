"""simplicio-loop — The Universal Looping AI Orchestrator.

A runtime-agnostic super-plugin (7 skills + loop/token hooks) that drains any
queue of work end-to-end on any LLM/runtime. This package ships the skills and
hooks and installs them into a runtime's skills location.
"""


def __getattr__(name: str) -> str:
    # Single source of truth = the package metadata (pyproject `version`); the literal is only a
    # fallback for an editable/source checkout that was never installed. No more version drift.
    # Read on first use, not at import: the thin client imports this package on every command, and
    # importlib.metadata alone costs more than the rest of the client.
    if name != "__version__":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            __version__ = version("simplicio-loop")
        except PackageNotFoundError:
            __version__ = "3.48.1"
    except Exception:  # pragma: no cover
        __version__ = "3.48.1"
    globals()["__version__"] = __version__
    return __version__
