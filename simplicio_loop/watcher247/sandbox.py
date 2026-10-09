"""Sandbox for every turbo / exec-CLI subprocess the watcher spawns.

Three layers, all decided here so tick.py only makes one call:
- scrubbed_env(): an allowlist of variables; a token leaves the env only when named in `keep`.
- wrap(): on Linux, the argv runs under bwrap, with the filesystem read-only except the clone and the
  state dir. Detected, never installed.
- no engine: SandboxUnavailable (reason_code "sandbox_unavailable") unless the operator sets
  SIMPLICIO_247_ALLOW_UNSANDBOXED=1 explicitly.
"""
from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

ALLOWED_ENV = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
OPT_OUT = "SIMPLICIO_247_ALLOW_UNSANDBOXED"


class SandboxUnavailable(RuntimeError):
    reason_code = "sandbox_unavailable"


def scrubbed_env(environ: Mapping[str, str], *, home: Path, keep: Iterable[str] = ()) -> dict[str, str]:
    """Allowlisted env plus HOME. `keep` names the only other variables passed through."""
    env = {name: environ[name] for name in ALLOWED_ENV if name in environ}
    env.setdefault("PATH", DEFAULT_PATH)
    env["HOME"] = str(home)
    env["SIMPLICIO_LOOP_DAEMON"] = "0"  # a sandboxed command neither starts nor reaches a daemon outside the sandbox
    for name in keep:
        if name in environ:
            env[name] = environ[name]
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


def worktree_binds(clone: str) -> list[str]:
    """bwrap binds for a LINKED git worktree (#1601): its own admin dir, the shared object store and the shared map base.

    The rest of the base clone's .git (config, hooks, refs) stays read-only inside the sandbox, so one item cannot touch another's
    branch or plant a hook. [] when `clone` is a plain clone.
    """
    dotgit = Path(clone) / ".git"
    if not dotgit.is_file():
        return []
    admin = Path(dotgit.read_text(encoding="utf-8").strip().removeprefix("gitdir:").strip())
    common = admin.parent.parent
    writable = [admin, common / "objects", common / "simplicio"]  # simplicio/: the mapper's central base, shared by every worktree
    return [arg for path in writable if path.is_dir() for arg in ("--bind", str(path), str(path))]


def wrap(argv: list[str], *, clone: Path, state_dir: Path, platform: str | None = None,
         environ: Mapping[str, str] | None = None, which: Callable[[str], str | None] | None = None) -> list[str]:
    """Return argv run inside the sandbox; raise SandboxUnavailable when none is possible."""
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
            "--ro-bind", "/", "/",          # whole filesystem read-only...
            # Own pid namespace + a /proc mounted for it: the watcher's pid (and its environ, which holds the
            # EnvironmentFile secrets, same uid) is neither listed nor readable. scrubbed_env cannot hide that.
            "--unshare-pid",
            "--dev", "/dev", "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--bind", clone, clone,          # ...except the clone and the state dir
            "--bind", state_dir, state_dir,
            *worktree_binds(clone),
            "--chdir", clone,
            "--die-with-parent", "--new-session",
            "--", *argv,
        ]
