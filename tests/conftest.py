from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _local_module_root in (_REPO_ROOT / "scripts", _REPO_ROOT / "hooks"):
    _local_module_root = str(_local_module_root)
    if _local_module_root not in sys.path:
        sys.path.insert(0, _local_module_root)

from simplicio_loop.core_network_guard import install as install_core_network_guard


@pytest.fixture(autouse=True)
def disable_operator_bootstrap_network_by_default(monkeypatch) -> None:
    """Hermetic tests opt into the real bootstrap explicitly at their test seam."""
    monkeypatch.setenv("SIMPLICIO_LOOP_AUTO_BOOTSTRAP_OPERATORS", "0")


@pytest.fixture(autouse=True)
def exec_auth_spawn_guard(request, monkeypatch):
    """exec_auth tests must only ever spawn fake binaries living in a temp dir (#1467).

    Spies on asyncio.create_subprocess_exec and subprocess.Popen: a spawn whose resolved
    executable is outside the temp dir (e.g. the real /root/.local/bin/claude) is refused
    and fails the test at teardown, even if production code swallows the exception.
    """
    if not Path(str(request.node.fspath)).name.startswith("test_exec_auth"):
        yield []
        return

    import asyncio
    import shutil
    import subprocess
    import tempfile

    tmp_root = os.path.realpath(tempfile.gettempdir())
    spawned: list[str] = []
    violations: list[str] = []

    def vet(argv0) -> None:
        resolved = shutil.which(os.fspath(argv0)) or os.fspath(argv0)
        resolved = os.path.realpath(resolved)
        spawned.append(resolved)
        if not resolved.startswith(tmp_root + os.sep):
            violations.append(resolved)
            raise AssertionError(f"test spawned a binary outside the tmp dir: {resolved}")

    real_exec = asyncio.create_subprocess_exec
    real_popen = subprocess.Popen

    async def spy_exec(program, *args, **kwargs):
        vet(program)
        return await real_exec(program, *args, **kwargs)

    class SpyPopen(real_popen):
        def __init__(self, args, *a, **kw):
            vet(args if isinstance(args, (str, bytes, os.PathLike)) else args[0])
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy_exec)
    monkeypatch.setattr(subprocess, "Popen", SpyPopen)
    yield spawned
    assert not violations, f"real binaries spawned: {violations}"


def _protected_checkout_roots() -> tuple[str, ...]:
    """This checkout and the main worktree of its repository: both share one `<git-common-dir>/simplicio`."""
    roots = {os.path.realpath(str(_REPO_ROOT))}
    git_entry = _REPO_ROOT / ".git"
    try:
        if git_entry.is_file():  # a linked worktree: ".git" is "gitdir: <common>/worktrees/<name>"
            gitdir = git_entry.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip()
            roots.add(os.path.realpath(os.path.dirname(os.path.dirname(os.path.dirname(gitdir)))))
    except (OSError, IndexError):
        pass
    return tuple(sorted(roots))


@pytest.fixture(autouse=True)
def runtime_never_targets_the_real_repo(monkeypatch):
    """No test may run the Simplicio Runtime against this repository (#1574).

    The Runtime keeps its baseline map and a full-tree `baseline-build-*` scratch under
    `<git-common-dir>/simplicio/map`, shared by every worktree; a run cut short by a timeout leaves
    them behind (102 directories, 6.8 GB measured). A spawn of the `simplicio` binary whose cwd or
    an argument is inside this checkout is refused, even if the code under test swallows the error.
    """
    import asyncio
    import subprocess

    roots = _protected_checkout_roots()
    violations: list[str] = []

    def inside(value) -> bool:
        try:
            resolved = os.path.realpath(os.fspath(value))
        except (TypeError, ValueError):
            return False
        return any(resolved == root or resolved.startswith(root + os.sep) for root in roots)

    def target_of(argv, cwd):
        """The repository a Runtime call acts on: its ``--repo`` value, else the cwd and path arguments."""
        for index, item in enumerate(argv):
            if item == "--repo" and index + 1 < len(argv):
                return [argv[index + 1]]
            if item.startswith("--repo="):
                return [item.split("=", 1)[1]]
        return [cwd or os.getcwd(), *[item for item in argv[1:] if os.sep in item]]

    def vet(argv, cwd) -> None:
        if isinstance(argv, (str, bytes, os.PathLike)):
            argv = [argv]
        argv = [os.fsdecode(item) for item in argv]
        if not argv or os.path.basename(argv[0]) not in ("simplicio", "simplicio.exe"):
            return
        if any(inside(target) for target in target_of(argv, cwd)):
            violations.append(" ".join(argv))
            raise AssertionError(
                "a test ran the Simplicio Runtime against the real repository "
                f"(it writes into the shared .git/simplicio): {' '.join(argv)}"
            )

    real_exec = asyncio.create_subprocess_exec
    real_popen = subprocess.Popen

    async def guarded_exec(program, *args, **kwargs):
        vet([program, *args], kwargs.get("cwd"))
        return await real_exec(program, *args, **kwargs)

    class GuardedPopen(real_popen):
        def __init__(self, args, *a, **kw):
            vet(args, kw.get("cwd"))
            super().__init__(args, *a, **kw)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", guarded_exec)
    monkeypatch.setattr(subprocess, "Popen", GuardedPopen)
    yield violations  # the guard's own tests clear it after asserting the refusal
    assert not violations, f"Runtime spawned against the real repository: {violations}"


@pytest.fixture
def admitting_capacity(monkeypatch) -> None:
    """Pin the documented physical-admission profile so host disk or memory pressure cannot block a dispatch test.

    The thresholds stay ascending but sit just under 100 and the disk reserve is zero, so a host is refused
    only at 99.9% pressure instead of the 88% default. Subprocesses inherit it through the environment.
    """
    for name, value in (
        ("TARGET_PRESSURE_PERCENT", "99.1"), ("NO_NEW_PRESSURE_PERCENT", "99.3"),
        ("CHECKPOINT_PRESSURE_PERCENT", "99.5"), ("TERMINATE_PRESSURE_PERCENT", "99.9"),
        ("DISK_SUSPEND_PERCENT", "100"), ("DISK_SUSPEND_FLOOR_BYTES", "0"), ("DISK_RESERVE_BYTES", "0"),
    ):
        monkeypatch.setenv("SIMPLICIO_LOOP_" + name, value)


def pytest_configure(config) -> None:
    """Make `check.py --core-gate` unable to reach the real network.

    This is deliberately opt-in so normal pytest runs and tests which exercise
    local AF_UNIX IPC retain their native socket behaviour.
    """
    if os.environ.get("SIMPLICIO_CORE_NO_NETWORK") != "1":
        return
    install_core_network_guard()
