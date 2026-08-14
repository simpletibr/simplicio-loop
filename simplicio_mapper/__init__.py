"""Python package entrypoint for simplicio-mapper."""

from __future__ import annotations

# Static fallback — keep in lockstep with package.json and pyproject.toml.
# Guard: `python scripts/check-version-sync.py` (CI: version-sync.yml).
__version__ = "0.26.20"

try:
    from importlib.metadata import PackageNotFoundError, version as _distribution_version
except ImportError:  # pragma: no cover - stdlib on supported Pythons
    PackageNotFoundError = Exception  # type: ignore[misc,assignment]
    _distribution_version = None  # type: ignore[assignment]

if _distribution_version is not None:
    try:
        __version__ = _distribution_version("simplicio-mapper")
    except PackageNotFoundError:
        pass

__all__ = ["__version__"]
