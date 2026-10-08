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

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple


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


def run_mapper_index(path: str, *, timeout: float = 60.0) -> dict:
    """Run the REAL `simplicio-mapper index <path> --json` command and return its
    parsed envelope (schema simplicio.mapper-index/v1) - a real subprocess call, no
    mocking, no fixture-canned JSON."""
    binary = mapper_binary_path()
    resolved = str(Path(path).expanduser().resolve(strict=True))
    result = subprocess.run(
        [binary, "index", resolved, "--json"],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise MapperIndexError(
            "simplicio-mapper index failed (exit %d): %s" % (result.returncode, result.stderr.strip())
        )
    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MapperIndexError("simplicio-mapper index did not emit valid JSON: %s" % exc) from exc
    if envelope.get("error"):
        raise MapperIndexError("simplicio-mapper index reported an error: %s" % envelope["error"])
    return envelope


def materialize_project_map(root: str, envelope: dict) -> Path:
    """Ensure project-map.json is at .simplicio-loop/ from envelope.paths.project_map.
    
    If mapper wrote elsewhere, copy to .simplicio-loop/. Register .simplicio/ in
    git exclude. Returns final path. Raises MapperIndexError if file missing anywhere.
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
    
    # Only copy and register if path differs and source file exists
    if project_map_path != expected_path and project_map_path.is_file():
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(project_map_path), str(expected_path))
        # Only register in git exclude if .git directory exists
        if project_map_path.parent.name == ".simplicio":
            git_dir = Path(resolved) / ".git"
            if git_dir.is_dir():
                try:
                    git_exclude = git_dir / "info" / "exclude"
                    if git_exclude.is_file():
                        content = git_exclude.read_text()
                        if ".simplicio/" not in content:
                            with open(git_exclude, "a") as f:
                                f.write(".simplicio/\n")
                except (OSError, FileNotFoundError):
                    pass
    return expected_path


def mapper_tree_snapshot(path: str, *, timeout: float = 60.0) -> Tuple[str, List[str]]:
    """A REAL tree_hash + file list for `build_canonical`/`build_overlay`, derived from
    the actual `simplicio-mapper` binary's own per-file content hashes (read from the
    real project-map.json it writes) — the bound orient operator's own
    signal, not a git-only shortcut."""
    resolved = str(Path(path).expanduser().resolve(strict=True))
    envelope = run_mapper_index(resolved, timeout=timeout)
    
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
