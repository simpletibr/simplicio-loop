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

Protected paths (issue #1567). Some files control the watcher or the delivery line itself: the opt-in and the ``verify``
command in ``loop.toml``, the workflows and CODEOWNERS, the hooks, the systemd unit, the local CI, and the gates. A plan
that edits one of them lets the next step approve its own change, so ``PROTECTED_PATHS`` names them and no plan may
create, edit, move or delete one. A human changes them with a commit of their own, reviewed as any other. The list is
checked for writes only (``operations_refusal``): a plan may still read an excerpt of such a file. The path is compared the
way a forgiving file system reads it (case, ``\\``, ``.``, trailing dots and spaces, zero-width and compatibility code
points), after every symlink is followed, and a directory that holds a protected path counts as protected too, so a move
or a delete of the parent cannot carry the file away. A plan names the reason ``protected_path`` and never decides it.

Two more ways round the list are closed here. A gate written as ``name.py`` is shadowed by a new ``name/`` package, a
``name.so`` or a ``name.pyc`` beside it (python imports those first), so each ``.py`` entry protects the siblings of its
stem too, in ``__pycache__`` as well. And a full plan carries ``validation`` commands that dev-cli runs after the apply with
the permissions of the loop, so ``plan_refusal`` turns away any plan that holds one.
"""
from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

PATH_KEYS = ("path", "dest")
PLAN_KEYS = ("operations", "ops", "edits")

# One list, relative to the repository root. A name stands for itself and for everything below it. A ``.py`` entry also
# stands for the siblings that python imports in its place: ``name/``, ``name.*`` and ``__pycache__/name.*``.
PROTECTED_PATHS = (
    ".github",  # workflows, templates, CODEOWNERS
    "CODEOWNERS",
    "docs/CODEOWNERS",
    ".simplicio-loop",  # loop.toml (opt-in, allowed authors, verify) and the loop's own state
    "packaging/systemd",  # the unit and the env file of the watcher
    "scripts/check.py",  # the local CI
    "hooks",  # the hooks the host runs: action gate, stop hook, pre-commit
    "plugin/hooks",
    "simplicio_loop/_bundle/hooks",
    ".githooks",  # what a host or git runs on its own: hook directories and the files that name commands
    ".husky",
    ".pre-commit-config.yaml",
    ".vscode/tasks.json",
    ".codex/hooks.json",
    ".codex/config.toml",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/hooks",
    ".cursor/hooks.json",
    ".kiro/hooks",
    "simplicio_loop/plan_paths.py",  # this gate
    "simplicio_loop/intake_gate.py",  # the repo and issue opt-in
    "simplicio_loop/watcher247/sandbox.py",
    "simplicio_loop/watcher247/secret_scan.py",
    "simplicio_loop/watcher247/prompt_guard.py",
    "simplicio_loop/watcher247/env_guard.py",
    "simplicio_loop/watcher247/verify.py",  # runs the repo's verify command
    "simplicio_loop/watcher247/squad_flow.py",
    "simplicio_loop/watcher247/points/judge.py",
    "simplicio_loop/watcher247/points/delivery_gate.py",
)


def _fold(part: str) -> str:
    """One path component the way a forgiving file system reads it.

    Case-insensitive volumes fold ``.GIT``; NTFS drops trailing dots and spaces; HFS+ ignores zero-width code points and
    reads compatibility forms (a full-width dot) as their plain letter.
    """
    name = "".join(ch for ch in unicodedata.normalize("NFKC", part) if unicodedata.category(ch) != "Cf")
    return name.rstrip(". ").casefold()


def _is_git_dir_name(part: str) -> bool:
    """One path component that names a git directory (the cases git's own ``.git`` checks refuse; NTFS answers to ``git~1``)."""
    return _fold(part) in {".git", "git~1"}


def inside_git_dir(path: str) -> bool:
    """True when any component of the plan path, with ``/`` or ``\\`` as separator, names a git directory."""
    return any(_is_git_dir_name(part) for part in path.replace("\\", "/").split("/"))


def _unsafe_relative(path: str) -> bool:
    portable = PurePosixPath(path.replace("\\", "/"))
    return (
        not path.strip() or "\0" in path or ":" in path or not _parts(path)  # no component at all is the root itself
        or portable.is_absolute() or PureWindowsPath(path).is_absolute() or ".." in portable.parts
    )


def _landing(root: str | os.PathLike[str], path: str) -> Path:
    """Where ``path`` lands under ``root`` once every symlink is followed, even for a path that does not exist yet."""
    base = os.path.realpath(root)
    return Path(os.path.realpath(os.path.join(base, path))).relative_to(base)


def _resolved_refusal(root: str | os.PathLike[str], path: str) -> str | None:
    """The reason ``path`` may not be written when it lands in ``.git`` or outside ``root``, or None."""
    try:
        landing = _landing(root, path)
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


def _parts(path: str) -> tuple[str, ...]:
    """The folded components of ``path``: ``/`` or ``\\`` separate, ``.`` and empty parts vanish, ``..`` climbs."""
    parts: list[str] = []
    for component in path.replace("\\", "/").split("/"):
        if component == "..":
            if parts:
                parts.pop()
        elif name := _fold(component):
            parts.append(name)
    return tuple(parts)


_PROTECTED = tuple((entry, _parts(entry)) for entry in PROTECTED_PATHS)
_PACKAGES = tuple((entry, (*_parts(entry)[:-1], _parts(entry)[-1].removesuffix(".py")))
                  for entry in PROTECTED_PATHS if entry.endswith(".py"))  # `name/` shadows `name.py`


def _shadows(parts: tuple[str, ...], folder: tuple[str, ...], stem: str) -> bool:
    """True for ``folder/stem.*`` and ``folder/__pycache__/stem.*``: an extension or byte-code file python picks over the source."""
    rest = parts[len(folder):] if parts[:len(folder)] == folder else ()
    if rest[:1] == ("__pycache__",):
        rest = rest[1:]
    return bool(rest) and rest[0].startswith(stem + ".")


def _protected_entry(parts: tuple[str, ...]) -> str | None:
    """The protected entry that ``parts`` is, lies below, or holds (a parent directory carries its children away)."""
    for entry, protected in (*_PROTECTED, *_PACKAGES):
        shared = min(len(parts), len(protected))
        if shared and parts[:shared] == protected[:shared]:
            return entry
    for entry, package in _PACKAGES:
        if _shadows(parts, package[:-1], package[-1]):
            return entry
    return None


def protected_refusal(path: str, root: str | os.PathLike[str] | None = None) -> str | None:
    """The reason a plan may not create, edit, move or delete ``path``, or None. With ``root`` symlinks are followed first."""
    entry = _protected_entry(_parts(path))
    if entry is None and root is not None:
        try:
            entry = _protected_entry(_parts(_landing(root, path).as_posix()))
        except (ValueError, OSError):
            return None  # outside the root or unresolvable: `refusal` names that reason
    if entry is None:
        return None
    return f"protected_path: {path!r} touches protected {entry!r}: a plan never creates, edits, moves or deletes it"


def operations_refusal(operations: Iterable[Any], root: str | os.PathLike[str]) -> str | None:
    """The first reason any ``path`` or ``dest`` of these operations may not be written, or None."""
    for operation in operations:
        if isinstance(operation, dict):
            for key in PATH_KEYS:
                value = operation.get(key)
                if isinstance(value, str) and (reason := refusal(value, root) or protected_refusal(value, root)):
                    return reason
    return None


VALIDATION_REFUSAL = "protected_path: validation commands are not allowed in a plan: dev-cli runs them after the apply, anywhere"


def plan_refusal(plan: Any, root: str | os.PathLike[str]) -> str | None:
    """``operations_refusal`` over every operation list a host plan may carry (``operations``, ``ops`` or ``edits``).

    A plan with ``validation`` commands is refused whole: dev-cli runs them after the apply, from the root, and they can write
    where no operation may. The loop runs its own checks (``--verify``) outside the plan.
    """
    if not isinstance(plan, dict):
        return None
    if plan.get("validation"):
        return VALIDATION_REFUSAL
    for key in PLAN_KEYS:
        operations = plan.get(key)
        if isinstance(operations, list) and (reason := operations_refusal(operations, root)):
            return reason
    return None
