"""Paths a plan may never name (issue #1565).

A hook or a ``core.*`` line planted in ``.git`` runs outside every sandbox with the credentials of whoever runs git next,
and ``.git`` is inside the repository, so the usual "stays under the root" check does not stop it. The loop refuses such a
path itself, before dev-cli is called, whichever dev-cli version is installed; dev-cli refuses it too (``_safe_path``).

The text is not enough: a repository may commit ``ln -s .git link``, and a dev-cli that predates its own symlink check
writes ``.git/hooks/pre-commit`` for ``link/hooks/pre-commit``. Given the root, the path is also resolved the way the
file system will, and refused when it lands inside ``.git`` or outside the root. A path that is absolute, climbs with
``..``, names a drive or holds ``:`` is refused before anything is read, so a plan learns nothing about a file it may not
name. A plan only creates or edits text files and cannot create a symlink, so a link made by the same plan is not a case.

The check and the write are two moments: a process that swaps a directory for a symlink to ``.git`` after the check and
before dev-cli writes (two dev-cli subprocesses) is not stopped here. It needs write access to the repository, which
already reaches ``.git/hooks``; only a dev-cli with its own symlink check (main, not 0.18.16) refuses again at write time.
A hard link to ``.git/config`` is no symlink and is not seen; both dev-cli versions replace the file instead of writing
through it (measured).
"""
from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

PATH_KEYS = ("path", "dest")
PLAN_KEYS = ("operations", "ops", "edits")


def _is_git_dir_name(part: str) -> bool:
    """One path component that names a git directory on a filesystem git supports.

    Case-insensitive volumes fold ``.GIT``; NTFS drops trailing dots and spaces and answers to the short name ``git~1``;
    HFS+ ignores zero-width code points (the cases git's own ``.git`` checks refuse).
    """
    name = "".join(ch for ch in part if unicodedata.category(ch) != "Cf").rstrip(". ").casefold()
    return name in {".git", "git~1"}


def inside_git_dir(path: str) -> bool:
    """True when any component of the plan path, with ``/`` or ``\\`` as separator, names a git directory."""
    return any(_is_git_dir_name(part) for part in path.replace("\\", "/").split("/"))


def _unsafe_relative(path: str) -> bool:
    portable = PurePosixPath(path.replace("\\", "/"))
    return (
        not path.strip() or "\0" in path or ":" in path or path in {".", ".."}
        or portable.is_absolute() or PureWindowsPath(path).is_absolute() or ".." in portable.parts
    )


def _resolved_refusal(root: str | os.PathLike[str], path: str) -> str | None:
    """Where ``path`` lands under ``root`` once every symlink is followed, even for a path that does not exist yet."""
    try:
        base = os.path.realpath(root)
        landing = Path(os.path.realpath(os.path.join(base, path))).relative_to(base)
    except ValueError:
        return f"{path!r} resolves outside the repository: a plan never writes beyond the root"
    except OSError:
        return f"{path!r} cannot be resolved inside the repository"
    if any(_is_git_dir_name(part) for part in landing.parts):
        return f"{path!r} resolves inside .git: a plan never writes a hook or a git setting"
    return None


def refusal(path: str, root: str | os.PathLike[str] | None = None) -> str | None:
    """The reason a plan may not write ``path``, or None. With ``root`` the path is also followed through its symlinks."""
    if inside_git_dir(path):
        return f"{path!r} is inside .git: a plan never writes a hook or a git setting"
    if _unsafe_relative(path):
        return f"unsafe_path: {path!r} is not a relative path inside the repository"
    return None if root is None else _resolved_refusal(root, path)


def operations_refusal(operations: Iterable[Any], root: str | os.PathLike[str]) -> str | None:
    """The first reason any ``path`` or ``dest`` of these operations may not be written, or None."""
    for operation in operations:
        if isinstance(operation, dict):
            for key in PATH_KEYS:
                value = operation.get(key)
                if isinstance(value, str) and (reason := refusal(value, root)):
                    return reason
    return None


def plan_refusal(plan: Any, root: str | os.PathLike[str]) -> str | None:
    """``operations_refusal`` over every operation list a host plan may carry (``operations``, ``ops`` or ``edits``)."""
    if not isinstance(plan, dict):
        return None
    for key in PLAN_KEYS:
        operations = plan.get(key)
        if isinstance(operations, list) and (reason := operations_refusal(operations, root)):
            return reason
    return None
