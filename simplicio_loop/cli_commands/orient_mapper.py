"""Mapper index for orient: timeouts, locks, and bounded project-map refresh.

Split from cli_impl.py (#1818). The code is moved unchanged; see
cli_commands/_base.py for why some names are read through impl().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import hashlib
import json
import signal
import subprocess
import time

from ._base import impl


ORIENT_SCHEMA = "simplicio.loop-orient/v1"


ORIENT_RECEIPT_SCHEMA = "simplicio.loop-orient-receipt/v1"


_DEFAULT_MAPPER_INDEX_TIMEOUT_S = 300.0


def _mapper_index_timeout_seconds() -> float:
    """Bound for the best-effort ``simplicio-mapper index`` call below.

    issue #1331: the hardcoded 60s timeout this used to carry was too short
    for a real ~3,900-file monorepo (measured at ~280s in
    the #1328 wave; evidence removed in 3.46.0, see git history), so it silently timed out and retried a full
    reindex from scratch on every subsequent ``orient``/``prepare``/``wave``
    call -- the exact "full re-index every call" symptom. Configurable via
    ``SIMPLICIO_LOOP_MAPPER_INDEX_TIMEOUT_S`` for a still-larger repo.
    """
    raw = impl().os.environ.get("SIMPLICIO_LOOP_MAPPER_INDEX_TIMEOUT_S", "").strip()
    if not raw:
        return _DEFAULT_MAPPER_INDEX_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_MAPPER_INDEX_TIMEOUT_S
    return value if value > 0 else _DEFAULT_MAPPER_INDEX_TIMEOUT_S


_DEFAULT_ORIENT_BUDGET_S = 120.0


def _orient_budget_seconds() -> float:
    """Wall-clock budget for the WHOLE ``orient``/``orient --brief`` call
    (issue #1339): a repo whose cold Mapper index would take longer than this
    never blocks past it with empty stdout -- the index is left running
    detached in the background and ``orient`` returns typed JSON instead.
    Configurable via ``SIMPLICIO_LOOP_ORIENT_BUDGET_S``.
    """
    raw = impl().os.environ.get("SIMPLICIO_LOOP_ORIENT_BUDGET_S", "").strip()
    if not raw:
        return _DEFAULT_ORIENT_BUDGET_S
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_ORIENT_BUDGET_S
    return value if value > 0 else _DEFAULT_ORIENT_BUDGET_S


class MapperIndexTimedOut(Exception):
    """Raised when a cold ``simplicio-mapper index`` outlives the orient
    budget; the index keeps running detached in the background (issue #1339)."""

    reason_code = "mapper_index_timeout"


class MapperIndexRunning(Exception):
    """Raised when a previous call's backgrounded ``simplicio-mapper index``
    is still running (issue #1339); never a second concurrent index."""

    reason_code = "mapper_index_running"


class OrientBudgetExceeded(MapperIndexTimedOut):
    """Raised when the whole ``orient``/``orient --brief`` call runs out of its
    single shared deadline (issue #1346) -- e.g. the Mapper ``orient`` survey
    subprocess outlived the budget left after the index step."""

    reason_code = "orient_budget_exceeded"


def _orient_deadline() -> float:
    """One monotonic deadline for the WHOLE orient call (issue #1346)."""
    return time.monotonic() + _orient_budget_seconds()


def _orient_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OrientBudgetExceeded("orient budget exhausted before the Mapper survey finished")
    return remaining


def _current_tree_state(root: Path) -> str | None:
    """A cheap, real fingerprint of "has anything changed since the last
    index" -- the committed tree id plus a hash of the working tree's own
    dirty status, so an uncommitted edit counts as a change too. ``None``
    for a non-git directory (reuse is then never claimed; every call falls
    through to a real index attempt, same as before this issue)."""
    if not (root / ".git").exists():
        return None
    try:
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"], cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            close_fds=True, timeout=10, check=False,
        )
        if tree.returncode != 0:
            return None
        status = subprocess.run(
            # Exclude our OWN state directory regardless of .gitignore: writing
            # project-map.json/mapper-index-state.json must never itself look
            # like a tree change on the very next call.
            ["git", "status", "--porcelain=v1", "--", ".", ":!.simplicio-loop"],
            cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            close_fds=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    dirty = hashlib.sha256((status.stdout or "").encode("utf-8")).hexdigest()
    return f"{tree.stdout.strip()}:{dirty}"


async def _ensure_project_map(root: Path, *, budget: float | None = None) -> None:
    """Guarantee the single artifact ``survey.provenance()`` (and therefore
    ``prepare``) requires as proof of a Mapper survey: `.simplicio-loop/project-map.json`.

    issue #1328 bug 2: the Mapper orient path (`_mapper_orient_fallback`)
    happens to produce this file as a side effect of shelling out to
    ``simplicio-mapper orient``, but an orient that reuses a survey never runs
    Mapper's ``orient``/``handoff`` itself and can leave a fresh repo without
    it -- `orient` reports success and writes `survey.json`, yet `prepare`
    then blocks on `mapper_provenance_missing`. There must be a
    single definition of "surveyed"; this makes `orient` -- whichever internal
    path it took -- respect it explicitly rather than leaving it to chance.
    A failure here (binary missing, timeout, non-git dir) is intentionally
    swallowed: `orient` itself still succeeded, and `survey.provenance()`'s own
    fail-closed check is what enforces the requirement downstream.

    issue #1331: reused by tree state (git tree id + working-tree dirty
    hash) instead of by mere file existence -- a repeat call against an
    UNCHANGED tree does not re-run the index at all, and a real change
    (however small) does trigger one. Mapper's public verbs (``scan``/
    ``inspect``/``handoff``/``ask``/``sync``) do not expose an incremental
    reindex of this artifact, only a full one (see ``simplicio-mapper
    --help``); that is Mapper's own current limitation, not something this
    caller can work around, so a real change still pays a full index --
    it is just never paid twice for the same tree state.

    issue #1339: ``budget`` (seconds) is the NEW, opt-in bounded mode used by
    ``orient``/``orient --brief``. ``budget=None`` (every OTHER caller: this
    function's own pre-#1339 tests, ``prepare``, etc.) keeps the original,
    fully-blocking behavior byte-for-byte. With a budget, a cold index that
    would outlive it is launched detached (its own process group, log under
    ``.simplicio-loop/mapper-index.log``) instead of blocking -- the caller
    gets a typed ``MapperIndexTimedOut``/``MapperIndexRunning`` instead of
    minutes of silence, and the NEXT call reuses the finished index via the
    same tree-state check above.
    """
    project_map = root / ".simplicio-loop" / "project-map.json"
    state_file = root / ".simplicio-loop" / "mapper-index-state.json"
    current_state = _current_tree_state(root)
    if project_map.is_file():
        if current_state is None:
            return
        try:
            recorded_state = json.loads(state_file.read_text(encoding="utf-8")).get("tree_state")
        except (OSError, ValueError):
            recorded_state = None
        if recorded_state == current_state:
            return
    if budget is None:
        try:
            from ..map_service_mapper import run_mapper_map, MapperUnavailableError, materialize_project_map
            envelope = await run_mapper_map(str(root), timeout=_mapper_index_timeout_seconds())
            materialize_project_map(str(root), envelope)
            
            if current_state is not None:
                state_file.parent.mkdir(parents=True, exist_ok=True)
                state_file.write_text(
                    json.dumps({"tree_state": current_state}, ensure_ascii=False), encoding="utf-8"
                )
        except (MapperUnavailableError, FileNotFoundError, OSError):
            # Binary missing or path doesn't exist: swallowed, same policy as before
            pass
        return
    await _ensure_project_map_bounded(root, project_map, state_file, current_state, budget)


_MAPPER_INDEX_LOCK_NAME = "mapper-index.lock"


_MAPPER_INDEX_LOG_NAME = "mapper-index.log"


def _mapper_index_running_info(lock_file: Path) -> dict[str, Any] | None:
    """Read+validate a backgrounded index's lock file; ``None`` when there is
    none, it is unreadable, or its process is gone (a stale lock is cleaned
    up here so the next attempt is never blocked by a crash).

    A lock whose process has outlived ``_mapper_index_timeout_seconds()`` (the
    hard cap on a single index run) is treated as a runaway: its WHOLE process
    group is killed here, lazily, on the next call that looks at it -- issue
    #1339's "kill the process group on timeout", without a separate persistent
    watchdog.
    """
    if not lock_file.is_file():
        return None
    # imported before the pid is read, so no import sits between reading a pid and probing it
    from simplicio_mapper.process_liveness import process_exists

    try:
        info = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = None
    pid = info.get("pid") if isinstance(info, dict) else None
    if not isinstance(pid, int):
        try:
            lock_file.unlink()
        except OSError:
            pass
        return None
    try:
        # Reap the index if it is our own child and has finished: otherwise it stays a zombie, which
        # the existence probe below reports as alive (the Popen that spawned it is long out of scope).
        impl().os.waitpid(pid, impl().os.WNOHANG)
    except OSError:
        pass  # not our child (another process started it)
    if not process_exists(pid):  # alive but not ours to signal (e.g. another uid) still counts as running
        try:
            lock_file.unlink()
        except OSError:
            pass
        return None
    started_at = info.get("started_at")
    if isinstance(started_at, (int, float)) and (time.time() - started_at) > _mapper_index_timeout_seconds():
        try:
            impl().os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            lock_file.unlink()
        except OSError:
            pass
        return None
    return info


def _mapper_index_reconcile_finished(log_path: Path, project_map: Path, state_file: Path,
                                      current_state: str | None) -> bool:
    """``True`` when a PRIOR backgrounded index -- one whose own
    ``_ensure_project_map_bounded`` call already raised ``MapperIndexTimedOut``
    and returned -- has since finished successfully on its own, so THIS call
    can reuse it instead of starting a redundant new one.

    Nothing keeps polling a backgrounded index once its caller has raised and
    returned; without this reconciliation, the NEXT call would only see (via
    ``_mapper_index_running_info``) that the process is gone and start a
    brand new index instead of noticing the old one already succeeded --
    reindexing forever instead of ever reusing (breaking the issue #1331
    tree-state reuse this budget path must preserve).
    """
    if not log_path.is_file() or not project_map.is_file():
        return False
    try:
        envelope = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(envelope, dict) or envelope.get("error"):
        return False
    if current_state is not None:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps({"tree_state": current_state}, ensure_ascii=False), encoding="utf-8"
        )
    return True


async def _wait_for_exit(proc: subprocess.Popen) -> None:
    """Yield to the event loop until ``proc`` exits; callers bound it with ``asyncio.wait_for``."""
    while proc.poll() is None:
        await asyncio.sleep(0.1)


async def _ensure_project_map_bounded(root: Path, project_map: Path, state_file: Path,
                                 current_state: str | None, budget: float) -> None:
    """The ``budget``-bounded branch of ``_ensure_project_map`` (issue #1339).
    Never blocks past ``budget`` seconds: a cold index is started detached
    (``start_new_session`` -> its own process group) and polled; one still
    running past the budget raises ``MapperIndexTimedOut`` and is left running
    for a later call to pick up; one already running (from a PRIOR call) raises
    ``MapperIndexRunning`` immediately, without starting a second one.
    """
    map_dir = root / ".simplicio-loop"
    lock_file = map_dir / _MAPPER_INDEX_LOCK_NAME
    log_path = map_dir / _MAPPER_INDEX_LOG_NAME
    running = _mapper_index_running_info(lock_file)
    if running is not None:
        raise MapperIndexRunning(
            f"simplicio-mapper index is already running in the background "
            f"(pid={running.get('pid')}); log at {log_path}"
        )
    if _mapper_index_reconcile_finished(log_path, project_map, state_file, current_state):
        return
    try:
        from ..map_service_gc import startup_gc
        from ..map_service_mapper import index_argv, mapper_binary_path
        binary = mapper_binary_path()
    except Exception:
        return  # binary missing: swallowed, same policy as the unbounded path above
    startup_gc(str(root))  # stale build scratch and orphan locks (never a base); never raises
    map_dir.mkdir(parents=True, exist_ok=True)
    resolved = str(root.resolve())
    popen_kwargs: dict[str, Any] = {}
    if hasattr(impl().os, "setsid"):
        popen_kwargs["start_new_session"] = True
    # Only the SPAWN is a plain Popen (it returns at once; the wait below is awaited, so the loop stays
    # free). An asyncio subprocess transport kills its child when it is closed or garbage collected, and
    # this index has to outlive the call: that is the detached mode of #1339.
    with open(log_path, "wb") as log_handle:
        proc = subprocess.Popen(
            index_argv(binary, resolved),
            stdout=log_handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            close_fds=True, **popen_kwargs,
        )
    lock_file.write_text(
        json.dumps({"pid": proc.pid, "started_at": time.time()}, ensure_ascii=False), encoding="utf-8",
    )
    try:
        await asyncio.wait_for(_wait_for_exit(proc), timeout=budget)
    except asyncio.TimeoutError:
        raise MapperIndexTimedOut(
            f"simplicio-mapper index exceeded the {budget:.0f}s orient budget "
            f"(pid={proc.pid}); continuing in the background, log at {log_path}"
        )
    try:
        lock_file.unlink()
    except OSError:
        pass
    if proc.returncode == 0 and current_state is not None and project_map.is_file():
        try:
            envelope = json.loads(log_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            envelope = None
        if isinstance(envelope, dict) and not envelope.get("error"):
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(
                json.dumps({"tree_state": current_state}, ensure_ascii=False), encoding="utf-8"
            )
