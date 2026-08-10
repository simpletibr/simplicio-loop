"""Mapper ↔ Simplicio Fast integration status (repo-scoped + global memory SoT).

Contract (always):
- Mapper owns extraction + durable memory SoT (``SIMPLICIO_DATA_DIR/memory.sqlite``).
- Fast owns disposable ``.sfast`` snapshots under ``<repo>/.simplicio/fast/``.
- Handoff path: ``simplicio-mapper fast-handoff`` → ``simplicio-fast build|context``.
- Fast never replaces Mapper memory; memory hub is global, Fast is per-repo derived.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .unify import env_hints, unify_status

FAST_LINK_SCHEMA = "simplicio.mapper-fast-link/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _module_ok(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _version_cmd(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    line = (result.stdout or result.stderr or "").strip().splitlines()
    return line[0] if line else "ok"


def mapper_fast_status(
    *,
    repo: str | Path | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Report whether Mapper+Fast can operate together (standalone or in a repo)."""
    memory = unify_status(data_dir=data_dir)
    hints = env_hints(data_dir=data_dir)

    mapper_mod = {
        "fast_handoff": _module_ok("simplicio_mapper.fast_handoff"),
        "fast_backend": _module_ok("simplicio_mapper.fast_backend"),
        "fast_certification": False,
    }
    # Import certification carefully — must not crash Windows
    try:
        import simplicio_mapper.fast_certification as _fc  # noqa: F401

        mapper_mod["fast_certification"] = True
    except Exception as error:  # noqa: BLE001
        mapper_mod["fast_certification_error"] = str(error)

    fast_pkg = _module_ok("simplicio_fast")
    mapper_bin = _which("simplicio-mapper")
    fast_bin = _which("simplicio-fast")
    mapper_ver = _version_cmd(["simplicio-mapper", "--version"]) if mapper_bin else None
    fast_ver = _version_cmd(["simplicio-fast", "--version"]) if fast_bin else None

    repo_path = Path(repo).expanduser().resolve() if repo else None
    repo_report: dict[str, Any] | None = None
    if repo_path is not None:
        simplicio = repo_path / ".simplicio"
        project_map = simplicio / "project-map.json"
        snapshot = simplicio / "fast" / "project.sfast"
        handoff_dir = simplicio / "fast-handoff"
        repo_report = {
            "repo": str(repo_path),
            "project_map": {
                "path": str(project_map),
                "exists": project_map.is_file(),
                "size": project_map.stat().st_size if project_map.is_file() else None,
            },
            "fast_snapshot": {
                "path": str(snapshot),
                "exists": snapshot.is_file(),
                "size": snapshot.stat().st_size if snapshot.is_file() else None,
            },
            "fast_handoff_dir": {
                "path": str(handoff_dir),
                "exists": handoff_dir.is_dir(),
            },
            "commands": {
                "mapper_scan": f"simplicio-mapper status {repo_path}",
                "fast_build": f"simplicio-fast build {repo_path} -o .simplicio/fast/project.sfast",
                "fast_handoff": "simplicio-mapper fast-handoff .",
                "doctor_fast": "simplicio-mapper doctor --fast",
            },
        }

    core_ok = (
        mapper_mod["fast_handoff"]
        and mapper_mod["fast_backend"]
        and mapper_mod["fast_certification"]
        and bool(mapper_bin)
        and bool(fast_bin or fast_pkg)
        and memory.get("status") in {"ready", "drift"}
    )
    repo_ok = True
    if repo_report is not None:
        # Repo alone: map optional until scan; Fast snapshot optional until build.
        # Integration is "ready" if tools work; "warm" if artifacts exist.
        repo_ok = True

    status = "ready" if core_ok else "degraded"
    if core_ok and repo_report:
        if repo_report["project_map"]["exists"] and repo_report["fast_snapshot"]["exists"]:
            status = "integrated"
        elif repo_report["project_map"]["exists"] or repo_report["fast_snapshot"]["exists"]:
            status = "partial"
        else:
            status = "tools_ready"

    return {
        "schema": FAST_LINK_SCHEMA,
        "status": status,
        "policy": {
            "memory_sot": "SIMPLICIO_DATA_DIR/memory.sqlite (MapperStore+FTS5)",
            "fast_snapshot": "<repo>/.simplicio/fast/project.sfast (derived, disposable)",
            "ownership": (
                "Mapper extracts + owns durable memory; Fast owns mmap/PlanDAG snapshots; "
                "never read .sfast offsets from agents"
            ),
            "handoff": "simplicio-mapper fast-handoff → simplicio-fast build/context",
        },
        "mapper": {
            "binary": mapper_bin,
            "version": mapper_ver,
            "modules": mapper_mod,
        },
        "fast": {
            "binary": fast_bin,
            "package_importable": fast_pkg,
            "version": fast_ver,
            "pyproject_depends_on_mapper": "simplicio-mapper>=0.26.11,<0.27",
        },
        "memory": {
            "status": memory.get("status"),
            "canonical_database": memory.get("canonical_database"),
            "semantic_items": memory.get("semantic_items"),
            "memory_entries": memory.get("memory_entries"),
            "fts5": memory.get("fts5"),
        },
        "repo": repo_report,
        "env_hints": {
            **hints,
            "SIMPLICIO_MAPPER_CONTEXT_BACKEND": "mapper",  # safe default; fast when certified
            "SIMPLICIO_FAST_MODE": "required",
        },
        "occurred_at": _now(),
    }


def ensure_repo_fast_artifacts(
    repo: str | Path,
    *,
    build_if_missing: bool = False,
    timeout: int = 120,
) -> dict[str, Any]:
    """Optionally build Fast snapshot for a repo (mapper remains extraction SoT)."""
    root = Path(repo).expanduser().resolve()
    status_before = mapper_fast_status(repo=root)
    built = None
    if build_if_missing and not (root / ".simplicio" / "fast" / "project.sfast").is_file():
        if not _which("simplicio-fast"):
            return {
                "schema": FAST_LINK_SCHEMA,
                "status": "skipped",
                "reason": "simplicio-fast_not_on_path",
                "before": status_before,
            }
        out = root / ".simplicio" / "fast" / "project.sfast"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(
                ["simplicio-fast", "build", str(root), "-o", str(out)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(root),
                stdin=subprocess.DEVNULL,
            )
            built = {
                "returncode": proc.returncode,
                "stdout": (proc.stdout or "")[:500],
                "stderr": (proc.stderr or "")[:500],
                "snapshot": str(out),
                "exists": out.is_file(),
            }
        except (OSError, subprocess.SubprocessError) as error:
            built = {"error": str(error)}
    status_after = mapper_fast_status(repo=root)
    return {
        "schema": FAST_LINK_SCHEMA,
        "status": status_after.get("status"),
        "build": built,
        "before": status_before,
        "after": status_after,
        "occurred_at": _now(),
    }


__all__ = [
    "FAST_LINK_SCHEMA",
    "ensure_repo_fast_artifacts",
    "mapper_fast_status",
]
