"""Project identity + scoped data roots under ``.simplicio-loop/data``.

Layout (no cross-project mixing):

- **Core / Runtime** (global): ``~/.simplicio-loop/data/``
  - ``memory.sqlite`` and other core banks for Runtime/MCP
- **Per project** (inside the git/workspace folder):
  ``<repo>/.simplicio-loop/data/<project_slug>/``
  - project memory, caches, and project-local files

``project_slug`` is derived (first match wins):

1. ``SIMPLICIO_PROJECT`` / ``SIMPLICIO_PROJECT_SLUG``
2. Explicit ``project=`` argument
3. Git remote basename (``origin``) or toplevel directory name
4. Host workspace hints (Codex / Cursor / Claude / Gemini / VS Code env)
5. Directory name of ``repo_root``
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import StoreLocation, StorePathError, reject_network_path, reject_symlink_components

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_project_slug(value: str) -> str:
    text = (value or "").strip().replace("\\", "/").rstrip("/")
    if not text:
        raise StorePathError("project slug cannot be empty")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    if text.endswith(".git"):
        text = text[: -len(".git")]
    text = _UNSAFE.sub("-", text).strip(".-_")
    if not text or not _SLUG_RE.match(text):
        raise StorePathError(f"unsafe project slug: {value!r}")
    return text.lower()


def _git(repo: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=8,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def resolve_project_slug(
    *,
    repo_root: str | Path | None = None,
    project: str | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return ``(slug, source)`` for project isolation."""
    env = os.environ if environ is None else environ
    for key in ("SIMPLICIO_PROJECT_SLUG", "SIMPLICIO_PROJECT", "SIMPLICIO_PROJECT_NAME"):
        raw = (env.get(key) or "").strip()
        if raw:
            return sanitize_project_slug(raw), f"env:{key}"
    if project and str(project).strip():
        return sanitize_project_slug(str(project)), "flag"

    for key in (
        "CURSOR_PROJECT_NAME",
        "CURSOR_WORKSPACE_NAME",
        "CLAUDE_PROJECT_NAME",
        "GEMINI_PROJECT",
        "CODEX_PROJECT",
        "VSCODE_WORKSPACE_NAME",
        "WORKSPACE_NAME",
    ):
        raw = (env.get(key) or "").strip()
        if raw:
            try:
                return sanitize_project_slug(raw), f"host:{key}"
            except StorePathError:
                continue

    if repo_root is not None:
        repo = Path(os.fspath(repo_root)).expanduser().resolve()
        remote = _git(repo, "config", "--get", "remote.origin.url")
        if remote:
            try:
                return sanitize_project_slug(remote), "git-remote"
            except StorePathError:
                pass
        top = _git(repo, "rev-parse", "--show-toplevel")
        if top:
            try:
                return sanitize_project_slug(Path(top).name), "git-toplevel"
            except StorePathError:
                pass
        return sanitize_project_slug(repo.name), "directory"

    raise StorePathError(
        "cannot resolve project slug; pass project=, SIMPLICIO_PROJECT, or repo_root"
    )


def core_data_root(
    *,
    environ: dict[str, str] | None = None,
    home: str | Path | None = None,
) -> Path:
    """Global Runtime/core data root: ``~/.simplicio-loop/data``."""
    env = os.environ if environ is None else environ
    if env.get("SIMPLICIO_CORE_DATA_DIR"):
        path = Path(env["SIMPLICIO_CORE_DATA_DIR"]).expanduser()
        reject_network_path(path)
        return path.resolve()
    if env.get("SIMPLICIO_HOME"):
        base = Path(env["SIMPLICIO_HOME"]).expanduser()
        if base.name == ".simplicio-loop":
            return (base / "data").resolve()
        return (base / ".simplicio-loop" / "data").resolve()
    if home is not None:
        base = Path(os.fspath(home)).expanduser()
    else:
        base = Path.home()
    return (base / ".simplicio-loop" / "data").resolve()


def project_data_root(
    repo_root: str | Path,
    *,
    project: str | None = None,
    environ: dict[str, str] | None = None,
    flat: bool = False,
) -> tuple[Path, str, str]:
    """Return ``(root, slug, source)`` for project-local data.

    Default: ``<repo>/.simplicio-loop/data/<slug>/``
    If ``flat=True`` or ``SIMPLICIO_PROJECT_DATA_FLAT=1``: ``<repo>/.simplicio-loop/data/``
    """
    env = os.environ if environ is None else environ
    if env.get("SIMPLICIO_PROJECT_DATA_DIR"):
        path = Path(env["SIMPLICIO_PROJECT_DATA_DIR"]).expanduser().resolve()
        reject_network_path(path)
        reject_symlink_components(path)
        slug, source = resolve_project_slug(repo_root=repo_root, project=project, environ=environ)
        return path, slug, f"env:SIMPLICIO_PROJECT_DATA_DIR+{source}"

    repo = Path(os.fspath(repo_root)).expanduser().resolve()
    reject_network_path(repo)
    reject_symlink_components(repo)
    slug, source = resolve_project_slug(repo_root=repo, project=project, environ=environ)
    use_flat = flat or env.get("SIMPLICIO_PROJECT_DATA_FLAT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if use_flat:
        root = (repo / ".simplicio-loop" / "data").resolve()
    else:
        root = (repo / ".simplicio-loop" / "data" / slug).resolve()
    return root, slug, source


@dataclass(frozen=True)
class ScopedDataLayout:
    """Resolved core + optional project data roots."""

    core: StoreLocation
    project: StoreLocation | None
    project_slug: str | None
    project_source: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "simplicio.mapper-store.scoped-data/v1",
            "core": {
                "root": str(self.core.root),
                "source": self.core.source,
                "exists": self.core.exists,
                "memory": str(self.core.database("memory.sqlite")),
            },
            "project": None
            if self.project is None
            else {
                "root": str(self.project.root),
                "source": self.project.source,
                "exists": self.project.exists,
                "slug": self.project_slug,
                "slug_source": self.project_source,
                "memory": str(self.project.database("memory.sqlite")),
            },
            "policy": {
                "core": "~/.simplicio-loop/data (Runtime/MCP global)",
                "project": "<repo>/.simplicio-loop/data/<slug> (isolated per git/host project)",
                "no_mix": "project memories never share a DB file with core or other projects",
            },
        }


def resolve_scoped_layout(
    *,
    repo_root: str | Path | None = None,
    project: str | None = None,
    data_dir: str | Path | None = None,
    environ: dict[str, str] | None = None,
    home: str | Path | None = None,
    include_project: bool = True,
) -> ScopedDataLayout:
    """Resolve core always; project when ``repo_root`` or project env is available."""
    env = os.environ if environ is None else environ

    if data_dir is not None:
        root = Path(os.fspath(data_dir)).expanduser().resolve()
        reject_network_path(root)
        reject_symlink_components(root)
        core = StoreLocation(root, "flag", root.exists())
    elif env.get("SIMPLICIO_CORE_DATA_DIR"):
        root = Path(env["SIMPLICIO_CORE_DATA_DIR"]).expanduser().resolve()
        reject_network_path(root)
        reject_symlink_components(root)
        core = StoreLocation(root, "env:SIMPLICIO_CORE_DATA_DIR", root.exists())
    elif env.get("SIMPLICIO_DATA_DIR"):
        root = Path(env["SIMPLICIO_DATA_DIR"]).expanduser().resolve()
        reject_network_path(root)
        reject_symlink_components(root)
        core = StoreLocation(root, "env:SIMPLICIO_DATA_DIR", root.exists())
    else:
        root = core_data_root(environ=env, home=home)
        reject_symlink_components(root)
        core = StoreLocation(root, "core:.simplicio-loop/data", root.exists())

    project_loc = None
    slug = None
    slug_source = None
    if include_project and (
        repo_root is not None
        or any(env.get(k) for k in ("SIMPLICIO_PROJECT", "SIMPLICIO_PROJECT_SLUG", "SIMPLICIO_PROJECT_NAME"))
    ):
        if repo_root is None:
            slug, slug_source = resolve_project_slug(project=project, environ=env)
            p_root = (core.root / "projects" / slug).resolve()
            project_loc = StoreLocation(p_root, "core-projects", p_root.exists())
        else:
            p_root, slug, slug_source = project_data_root(
                repo_root, project=project, environ=env
            )
            project_loc = StoreLocation(p_root, f"project:{slug_source}", p_root.exists())

    return ScopedDataLayout(
        core=core,
        project=project_loc,
        project_slug=slug,
        project_source=slug_source,
    )


__all__ = [
    "ScopedDataLayout",
    "core_data_root",
    "project_data_root",
    "resolve_project_slug",
    "resolve_scoped_layout",
    "sanitize_project_slug",
]
