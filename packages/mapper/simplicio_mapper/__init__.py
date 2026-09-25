"""Python package entrypoint for simplicio-mapper."""

from __future__ import annotations

# Static fallback — keep in lockstep with package.json and pyproject.toml.
# Guard: `python scripts/check-version-sync.py` (CI: version-sync.yml).
__version__ = "0.26.34"

try:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _distribution_version
except ImportError:  # pragma: no cover - stdlib on supported Pythons
    PackageNotFoundError = Exception  # type: ignore[misc,assignment]
    _distribution_version = None  # type: ignore[assignment]

# Prefer the checked-in source version when a stale or duplicate dist-info is
# present in the ambient interpreter. A wheel built from this tree carries the
# same value, so a matching metadata value is harmless; a mismatching value is
# installation drift, not a reason to report the wrong checkout version.
if _distribution_version is not None:
    try:
        detected_version = _distribution_version("simplicio-mapper")
    except (PackageNotFoundError, ValueError):
        detected_version = None
    if isinstance(detected_version, str) and detected_version.strip() == __version__:
        __version__ = detected_version.strip()

__all__ = ["__version__"]
