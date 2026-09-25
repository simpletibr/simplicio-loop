"""simplicio-dev-cli command modules.

Command routing — dispatches ``gate``, ``nest``, and ``score-skill``
commands to the native Rust ``simplicio`` binary when available, with
automatic fallback to the Python implementation.

All three reach `route_command` (below) through
`simplicio.commands._shared.try_route_via_simplicio`, but via two different
paths — worth spelling out explicitly (issue #111 audit) so "score-skill is
delegable" doesn't read as dead documentation: ``gate``/``nest`` bypass the
main argparse parser entirely (`cli.py`'s ``_dispatch_nested`` calls
`try_route_via_simplicio` directly, before falling back to
`commands.gate`/`commands.nest`'s own ``main()``); ``score-skill`` goes
through the normal argparse subparser and `commands/score_skill.py`'s
``run()``, which calls `try_route_via_simplicio` itself
(`commands/score_skill.py:246`) before falling back to its own ``main()``.
"""

from __future__ import annotations

from ..runtime_bridge import call_simplicio, simplicio_available, use_native_implementation

# Re-exported for callers that check native-binary availability without
# reaching into `simplicio.runtime_bridge` directly.
__all__ = ["route_command", "simplicio_available"]


def route_command(
    cmd_name: str,
    args: list[str],
    *,
    prefer_native: bool = True,
    prefer_python: bool = False,
) -> int | None:
    """Route a command to the Rust binary or return ``None`` for Python fallback.

    When the Rust binary is available and *prefer_native* is ``True``, the
    command is executed via ``subprocess`` against the native ``simplicio``
    binary and its exit code is returned immediately.

    When Rust is unavailable or *prefer_python* is ``True``, the function
    returns ``None`` so the caller can invoke the Python implementation.

    Parameters
    ----------
    cmd_name:
        Subcommand name (e.g. ``"gate"``, ``"nest"``, ``"score-skill"``).
    args:
        Remaining command-line arguments for the subcommand.
    prefer_native:
        Whether to prefer the Rust binary when available (default ``True``).
    prefer_python:
        Force the Python fallback even when Rust is available (default ``False``).

    Returns
    -------
    Exit code (``int``) when the Rust binary handled the command, or
    ``None`` if the caller should fall back to the Python implementation.
    """
    if not use_native_implementation(prefer_native=prefer_native, prefer_python=prefer_python):
        return None

    try:
        result = call_simplicio([cmd_name, *args])
    except RuntimeError:
        return None
    except FileNotFoundError:
        return None

    # Forward the Rust binary's output to the user
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=__import__("sys").stderr)

    return result.returncode
