"""Real `simplicio-mapper` process integration for the map service (#512/#513).

`map_service_git.py` derives tree_hash/files straight from `git` — a real, but
git-only, signal. This module closes the specific remaining AC ("integração
Git/mapper real") by shelling out to the actual `simplicio-mapper` binary (this
repo's bound `orient` operator, per AGENTS.md), reading its real
`.simplicio-loop/project-map.json` output, and deriving tree_hash/files from the
mapper's own per-file content hashes — not git blob shas, the mapper's own
signal, so a real multi-worktree scenario is driven by the actual tool this
ecosystem uses for orientation, not a git shortcut standing in for it.

Deliberately additive: does not modify map_service.py/map_service_git.py/
map_service_single_flight.py's existing tested behavior. If the `simplicio-
mapper` binary is not installed, MapperUnavailableError is raised — fail
closed, never a fake/simulated result.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple


class MapperUnavailableError(RuntimeError):
    """Raised when the `simplicio-mapper` binary is not installed/reachable."""


class MapperIndexError(RuntimeError):
    """Raised when `simplicio-mapper index` fails or its output is unusable."""


def mapper_binary_path() -> str:
    path = shutil.which("simplicio-mapper")
    if not path:
        raise MapperUnavailableError(
            "the simplicio-mapper binary is not installed/on PATH - this repo's bound "
            "orient operator (AGENTS.md) is required for real mapper integration"
        )
    return path


async def _run_mapper(argv: list, timeout: float) -> tuple:
    """Run one mapper command in its own process group; kill the whole group on timeout/cancel.

    The child runs under ``asyncio.wait_for``: the event loop stays free while it works, and on
    ``timeout`` the group is killed and ``subprocess.TimeoutExpired`` is raised."""
    from .exec_planner import _kill_process_tree

    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _kill_process_tree(proc)
        raise subprocess.TimeoutExpired(argv, timeout) from None
    except BaseException:
        await _kill_process_tree(proc)
        raise
    return (
        proc.returncode,
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
    )


async def run_mapper_index(path: str, *, timeout: float = 60.0) -> dict:
    """Run the REAL `simplicio-mapper index <path> --json` command and return its
    parsed envelope (schema simplicio.mapper-index/v1) - a real subprocess call, no
    mocking, no fixture-canned JSON."""
    from .map_service_gc import startup_gc

    resolved = str(Path(path).expanduser().resolve(strict=True))
    # Housekeeping first (#1574): stale build scratch and orphan locks never accumulate.
    await asyncio.to_thread(startup_gc, resolved)
    binary = mapper_binary_path()
    returncode, stdout, stderr = await _run_mapper([binary, "index", resolved, "--json"], timeout)
    if returncode != 0:
        raise MapperIndexError(
            "simplicio-mapper index failed (exit %d): %s" % (returncode, stderr.strip()[-500:])
        )
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MapperIndexError("simplicio-mapper index did not emit valid JSON: %s" % exc) from exc
    if envelope.get("error"):
        raise MapperIndexError("simplicio-mapper index reported an error: %s" % envelope["error"])
    return envelope


def _served_overlay(stdout: str) -> Optional[dict]:
    """The overlay receipt when it really served this worktree, else ``None``.

    "Served" means ``status: ok`` AND the project map it names exists on disk: a mapper that
    answers the verb without writing anything must not stop the full index from running.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(envelope, dict) or envelope.get("status") != "ok" or envelope.get("error"):
        return None
    project_map = (envelope.get("paths") or {}).get("project_map")
    if not project_map or not Path(project_map).is_file():
        return None
    return envelope


async def run_mapper_map(path: str, *, timeout: float = 60.0) -> dict:
    """Map ``path`` as the repository's central default-branch base plus this worktree's delta.

    ``simplicio-mapper canonical overlay`` builds the base once for every worktree (single-flight,
    under the git common dir) and writes only this worktree's own state. When it cannot serve --
    no git repository, no default branch, C#/Razor sources, an older mapper without the verb --
    this falls back to a full ``index``, so the caller always ends with a project map or an error.
    """
    from .map_service_gc import startup_gc

    resolved = str(Path(path).expanduser().resolve(strict=True))
    await asyncio.to_thread(startup_gc, resolved)
    binary = mapper_binary_path()
    started = time.monotonic()
    returncode, stdout, _stderr = await _run_mapper(
        [binary, "canonical", "overlay", resolved, "--json"], timeout
    )
    envelope = _served_overlay(stdout) if returncode == 0 else None
    if envelope is not None:
        return envelope
    return await run_mapper_index(resolved, timeout=max(1.0, timeout - (time.monotonic() - started)))


def index_argv(binary: str, resolved: str) -> list:
    """One command line that maps ``resolved`` overlay-first and indexes only as a fallback.

    The detached orient path (`cli_impl._ensure_project_map_bounded`) needs a single process it can
    poll and kill as a group, so the fallback lives in a tiny module run with ``python -m``. A frozen
    or compiled build cannot ``-m`` itself: there the detached path keeps the plain full index.
    """
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [binary, "index", resolved, "--json"]
    # -P: do not put the cwd (the mapped repository) first on sys.path; a repo file named like a
    # stdlib module (hashlib.py, asyncio.py) would otherwise run inside the helper. Python >= 3.11.
    return [sys.executable, "-P", "-m", "simplicio_loop.map_service_mapper", binary, resolved]


def _main(argv: list) -> int:
    binary, resolved = argv
    overlay = subprocess.run(
        [binary, "canonical", "overlay", resolved, "--json"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True,
    )
    if overlay.returncode == 0 and _served_overlay(overlay.stdout) is not None:
        sys.stdout.write(overlay.stdout)
        return 0
    return subprocess.call([binary, "index", resolved, "--json"], stdin=subprocess.DEVNULL)


def materialize_project_map(root: str, envelope: dict) -> Path:
    """Ensure project-map.json is at .simplicio-loop/ from envelope.paths.project_map.
    
    If mapper wrote elsewhere, copy to .simplicio-loop/. Returns final path. Raises MapperIndexError if file missing anywhere.
    """
    resolved = str(Path(root).expanduser().resolve(strict=True))
    expected_path = Path(resolved) / ".simplicio-loop" / "project-map.json"
    
    project_map_path_str = envelope.get("paths", {}).get("project_map")
    if project_map_path_str:
        project_map_path = Path(project_map_path_str)
    else:
        project_map_path = expected_path
    
    if not project_map_path.is_file() and not expected_path.is_file():
        raise MapperIndexError(
            "simplicio-mapper index reported success but %s does not exist" % project_map_path
        )
    
    # Only copy if path differs and source file exists
    if project_map_path != expected_path and project_map_path.is_file():
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(project_map_path), str(expected_path))
    return expected_path


async def mapper_tree_snapshot(path: str, *, timeout: float = 60.0) -> Tuple[str, List[str]]:
    """A REAL tree_hash + file list for `build_canonical`/`build_overlay`, derived from
    the actual `simplicio-mapper` binary's own per-file content hashes (read from the
    real project-map.json it writes) — the bound orient operator's own
    signal, not a git-only shortcut."""
    resolved = str(Path(path).expanduser().resolve(strict=True))
    envelope = await run_mapper_index(resolved, timeout=timeout)
    
    # Use the helper to materialize project-map at the expected location
    project_map_path = materialize_project_map(resolved, envelope)
    project_map = json.loads(project_map_path.read_text(encoding="utf-8"))
    files = project_map.get("files") or []
    if not files:
        return hashlib.sha256(b"empty-mapper-index").hexdigest(), []
    file_hashes = sorted(str(entry["file_hash"]) for entry in files if entry.get("file_hash"))
    tree_hash = hashlib.sha256("".join(file_hashes).encode("utf-8")).hexdigest()
    paths = [str(Path(resolved) / entry["path"]) for entry in files if entry.get("path")]
    return tree_hash, sorted(paths)


if __name__ == "__main__":  # pragma: no cover - exercised through index_argv in a subprocess
    raise SystemExit(_main(sys.argv[1:]))
