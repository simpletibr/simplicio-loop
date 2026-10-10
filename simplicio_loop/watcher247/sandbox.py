"""Sandbox for every turbo / exec-CLI subprocess the watcher spawns.

Three layers, all decided here so tick.py only makes one call:
- scrubbed_env(): an allowlist of variables; a token leaves the env only when named in `keep`.
- wrap(): on Linux, the argv runs under bwrap, with the filesystem read-only except the item's own worktree, admin dir,
  shared objects and mapper base; the state dir is read-only too. A planner CLI also gets an empty HOME plus its own folders
  (HomeView). Detected, never installed.
- no engine: SandboxUnavailable (reason_code "sandbox_unavailable") unless the operator sets
  SIMPLICIO_247_ALLOW_UNSANDBOXED=1 explicitly.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

ALLOWED_ENV = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
OPT_OUT = "SIMPLICIO_247_ALLOW_UNSANDBOXED"


class SandboxUnavailable(RuntimeError):
    reason_code = "sandbox_unavailable"


@dataclass(frozen=True)
class HomeView:
    """What a planner CLI sees of the service user's HOME (#1570): an empty tmpfs plus these paths, relative to `home`.

    `rw`: the folders its CLI writes (login, token renewal, logs). Folders only: a bound single file breaks the CLI's atomic
    rename (EBUSY). `ro`: its binary and install tree; a symlink is recreated as a symlink, so list its target as well.
    `hide`: folders inside an `rw` folder that belong to another CLI (an empty tmpfs goes over them).
    Whatever is missing on the host is skipped: a family without a login yet still runs.
    """

    home: Path
    rw: tuple[str, ...] = ()
    ro: tuple[str, ...] = ()
    hide: tuple[str, ...] = ()


def scrubbed_env(environ: Mapping[str, str], *, home: Path, keep: Iterable[str] = ()) -> dict[str, str]:
    """Allowlisted env plus HOME. `keep` names the only other variables passed through."""
    env = {name: environ[name] for name in ALLOWED_ENV if name in environ}
    env.setdefault("PATH", DEFAULT_PATH)
    env["HOME"] = str(home)
    for name in keep:
        if name in environ:
            env[name] = environ[name]
    env["SIMPLICIO_LOOP_DAEMON"] = "0"  # after `keep`, which cannot undo it: a sandboxed command never reaches a daemon
    return env


def engine(which: Callable[[str], str | None] | None = None, platform: str | None = None) -> str | None:
    """'bwrap' or None. Only Linux has an engine. (systemd-run is not one: a --scope rejects the
    filesystem properties and a user-manager service does not enforce them reliably.)"""
    if (platform or sys.platform) != "linux":
        return None
    return "bwrap" if (which or shutil.which)("bwrap") else None


def refusal(environ: Mapping[str, str] | None = None, platform: str | None = None) -> str | None:
    """reason_code when the watcher must not run any subprocess, else None."""
    env = os.environ if environ is None else environ
    if engine(platform=platform) is None and env.get(OPT_OUT) != "1":
        return SandboxUnavailable.reason_code
    return None


def _layout(clone: str | Path) -> tuple[Path, Path, str] | None:
    """(work dir, shared .git dir, issue) of an item's worktree `<WORK>/<repo>.wt/<issue>`, from the path alone; None for anything else."""
    path = Path(clone)
    if not path.parent.name.endswith(".wt"):
        return None
    work = path.parent.parent
    return work, work / path.parent.name.removesuffix(".wt") / ".git", path.name


def worktree_binds(clone: str) -> list[str]:
    """bwrap binds for an item's worktree `<WORK>/<repo>.wt/<issue>` (#1601): its own admin dir, the shared object store and map base.

    wrap() makes the whole work dir read-only before these (and before the clone), so the rest of the base clone's .git (config,
    hooks, refs) and every other item's worktree and admin dir cannot be written from inside: one item cannot touch another's
    branch, plant a hook or move a ref. The paths come from the fixed layout, never from the `.git` file: that file is writable
    inside the sandbox, and a later step must not bind what an earlier one pointed it at. [] when `clone` is not an item's.
    """
    layout = _layout(clone)
    if layout is None:
        return []
    _work, common, number = layout
    writable = [common / "worktrees" / number, common / "objects", common / "simplicio"]  # simplicio/: the mapper's central base
    return [arg for target in writable if target.is_dir() for arg in ("--bind", str(target), str(target))]


def item_git_env(cwd: str | Path | None) -> dict[str, str]:
    """GIT_DIR / GIT_COMMON_DIR / GIT_WORK_TREE for host-side git in an item's worktree, from the fixed layout; {} elsewhere.

    The item can rewrite its own `.git` file (and `commondir`) from inside the sandbox; git on the host would then resolve to another
    item's admin dir and commit onto its branch. With these variables git never reads the file.
    """
    layout = _layout(cwd) if cwd is not None else None
    if layout is None:
        return {}
    _work, common, number = layout
    return {"GIT_DIR": str(common / "worktrees" / number), "GIT_COMMON_DIR": str(common), "GIT_WORK_TREE": str(cwd)}


def _home_args(view: HomeView) -> list[str]:
    """bwrap args for a planner's HOME: an empty tmpfs, then the family's folders and binary. Fails closed (SandboxUnavailable)
    when HOME is not an absolute directory other than `/`: without the tmpfs the whole HOME would stay readable."""
    home = view.home
    if not home.is_absolute() or home == Path("/") or not home.is_dir():
        raise SandboxUnavailable(f"cannot mount an empty HOME over {home}: not an absolute directory")
    args = ["--tmpfs", str(home)]
    for name in view.rw:
        if (home / name).is_dir():
            args += ["--bind-try", str(home / name), str(home / name)]
    for name in view.hide:
        if (home / name).is_dir():
            args += ["--tmpfs", str(home / name)]
    for name in view.ro:
        path = home / name
        if path.is_symlink():
            args += ["--symlink", os.readlink(path), str(path)]
        else:
            args += ["--ro-bind-try", str(path), str(path)]
    return args


def wrap(argv: list[str], *, clone: Path, state_dir: Path, platform: str | None = None,
         environ: Mapping[str, str] | None = None, which: Callable[[str], str | None] | None = None,
         home: HomeView | None = None) -> list[str]:
    """Return argv run inside the sandbox; raise SandboxUnavailable when none is possible.

    Writable from inside: the item's own worktree, its admin dir, the shared objects, the mapper base, the family folders of
    `home` and the private /tmp and /dev. Everything else, the whole state dir included, is read-only. Without `home` the
    HOME stays visible read-only (turbo and the test commands, until step 2 of #1570 measures what they read from it).
    """
    env = os.environ if environ is None else environ
    kind = engine(which, platform)
    if kind is None:
        if env.get(OPT_OUT) == "1":
            return list(argv)
        raise SandboxUnavailable("no sandbox (bwrap) on this host; set "
                                 f"{OPT_OUT}=1 to run unsandboxed")
    clone, state_dir = str(clone), str(state_dir)
    if kind == "bwrap":
        return [
            "bwrap",
            "--ro-bind", "/", "/",          # whole filesystem read-only,
            # Own pid namespace + a /proc mounted for it: the watcher's pid (and its environ, which holds the
            # EnvironmentFile secrets, same uid) is neither listed nor readable. scrubbed_env cannot hide that.
            "--unshare-pid",
            "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp",
            *([] if home is None else _home_args(home)),  # a planner: empty HOME + its own folders, before any bind under HOME
            # The state dir stays read-only (#1656): claims, budget, STOP, status, fixes, baseline, issues-disabled, work/, logs/.
            # The host writes them; the item writes none, so it cannot queue fixes, hide issues or create STOP.
            "--ro-bind", state_dir, state_dir,
            "--bind", clone, clone,          # ...except this item's own clone
            *worktree_binds(clone),          # and its own admin dir
            "--chdir", clone,
            "--die-with-parent", "--new-session",
            "--", *argv,
        ]
