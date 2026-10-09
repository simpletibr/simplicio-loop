"""Paths a plan may never name (issue #1565).

A hook or a ``core.*`` line planted in ``.git`` runs outside every sandbox with the credentials of whoever runs git next,
and ``.git`` is inside the repository, so the usual "stays under the root" check does not stop it. The loop refuses such a
path itself, before dev-cli is called, whichever dev-cli version is installed; dev-cli refuses it too (``_safe_path``).
"""
from __future__ import annotations

import unicodedata


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


def refusal(path: str) -> str | None:
    """The reason a plan may not write ``path``, or None."""
    return f"{path!r} is inside .git: a plan never writes a hook or a git setting" if inside_git_dir(path) else None
