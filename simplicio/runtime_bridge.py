"""Runtime bridge — discover and delegate to the Rust simplicio binary.

Provides a unified interface for detecting the native Rust ``simplicio``
binary on the PATH and routing CLI commands to it via ``subprocess``, with
graceful Python fallback when the binary is unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def discover_simplicio() -> str | None:
    """Locate the ``simplicio`` Rust binary on the PATH.

    Returns the absolute path to the binary, or ``None`` if it is not found.
    Also respects the ``SIMPLICIO_BIN`` environment variable override.
    """
    explicit = os.environ.get("SIMPLICIO_BIN")
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    found = shutil.which("simplicio")
    return found


def simplicio_available() -> bool:
    """Return ``True`` if the Rust ``simplicio`` binary is available."""
    return discover_simplicio() is not None


def call_simplicio(
    args: list[str],
    *,
    input_text: str | None = None,
    capture_output: bool = True,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    """Call the Rust ``simplicio`` binary with *args*.

    Parameters
    ----------
    args:
        Command-line arguments to pass to the ``simplicio`` binary.
    input_text:
        Optional string to feed to the process's stdin.
    capture_output:
        If ``True`` (default), capture stdout and stderr.
    timeout:
        Timeout in seconds (no timeout if ``None``).

    Returns
    -------
    ``subprocess.CompletedProcess`` with ``stdout`` and ``stderr`` populated
    when *capture_output* is ``True``.

    Raises
    ------
    RuntimeError
        If the ``simplicio`` binary cannot be found.
    subprocess.TimeoutExpired
        If the call exceeds *timeout*.
    """
    binary = discover_simplicio()
    if binary is None:
        raise RuntimeError(
            "simplicio (Rust binary) not found on PATH. Install the simplicio-runtime or set SIMPLICIO_BIN."
        )
    cmd = [binary, *args]
    completed = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        capture_output=capture_output,
        timeout=timeout,
    )
    return completed


def use_native_implementation(
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> bool:
    """Decide whether to use the Rust binary or Python fallback.

    ``prefer_native`` is the default behaviour — use Rust when available.
    ``prefer_python`` forces Python fallback regardless of availability.
    If both are ``False`` the function falls back to the default heuristic
    (prefer native when available).

    Returns ``True`` to indicate the Rust binary should be used.
    """
    if prefer_python:
        return False
    if not simplicio_available():
        return False
    return prefer_native
