"""Where the code of a PR runs: a scrubbed environment inside bwrap, never the watcher's own environment (#1649, B1).

The gate runs the PR's tests and mutants. That is the PR author's code, with the watcher's privileges, so it gets:
- `child_env`: `sandbox.scrubbed_env` (an allowlist, no token, `keep` empty) and HOME = an empty directory;
- `make_jail`: bwrap through `sandbox.wrap` with the HOME of the service user replaced by an empty tmpfs (`HomeView` with nothing),
  the tree under test writable and the rest read-only. No bwrap, no run: `sandbox.SandboxUnavailable` (reason_code
  `sandbox_unavailable`). The opt-out variable of the watcher (`SIMPLICIO_247_ALLOW_UNSANDBOXED`) is NOT honored here.

Residual risk: `sandbox.wrap` does not `--unshare-net`, so the PR's code can still reach the network (see docs/SQUADS.md).
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..watcher247 import sandbox

NO_HOME = Path("/nonexistent-review-gate-home")  # HOME of a child that is not under bwrap: nothing there to read
WrapFor = Callable[[Path], Callable[[list[str]], list[str]]]


def child_env(extra: Mapping[str, str] | None, home: Path | None = None) -> dict[str, str]:
    """The environment of one test run: allowlisted host variables, `extra` (PYTHONPATH...) and an empty HOME."""
    home = NO_HOME if home is None else home
    env = {**sandbox.scrubbed_env(os.environ, home=home), **(extra or {})}
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


@dataclass(frozen=True)
class Jail:
    home: Path  # HOME of the child: an empty tmpfs under bwrap
    wrap_for: WrapFor  # root of the tree to run in -> argv wrapper


def _python_ro(python: str, home: Path) -> tuple[str, ...]:
    """Folders under HOME the interpreter needs (its venv or install tree), read-only; HOME stays empty otherwise."""
    found: list[str] = []
    for candidate in (Path(python), Path(os.path.realpath(python))):
        base = candidate.parent.parent
        if home in base.parents and base.name != ".local" and ((base / "pyvenv.cfg").is_file() or (base / "bin").is_dir()):
            rel = str(base.relative_to(home))
            if rel not in found:
                found.append(rel)
        cfg = base / "pyvenv.cfg"
        if cfg.is_file():  # `home = <dir with the base interpreter>` may sit under HOME too
            for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
                key, _, value = line.partition("=")
                parent = Path(value.strip()).parent
                if key.strip() == "home" and home in parent.parents and parent.name != ".local" and str(parent.relative_to(home)) not in found:
                    found.append(str(parent.relative_to(home)))
    return tuple(found)


def make_jail(state_dir: Path, python: str, *, home: Path | None = None) -> Jail:
    """The bwrap jail for the trees of one PR. Raises `sandbox.SandboxUnavailable` when there is none (never runs unsandboxed)."""
    if sandbox.engine() is None:
        raise sandbox.SandboxUnavailable("no sandbox (bwrap) on this host: the gate does not run a PR's code unsandboxed")
    home = Path.home() if home is None else home
    view = sandbox.HomeView(home=home, ro=_python_ro(python, home))

    def wrap_for(root: Path) -> Callable[[list[str]], list[str]]:
        # environ={}: the opt-out of the watcher cannot turn the sandbox off here
        return lambda argv: sandbox.wrap(argv, clone=root, state_dir=state_dir, home=view, environ={})

    wrap_for(state_dir)(["true"])  # fails now (SandboxUnavailable), not in the middle of a run, when HOME cannot be hidden
    return Jail(home, wrap_for)
