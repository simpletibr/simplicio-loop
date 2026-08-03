"""Canonical, side-effect-free MapperStore path resolution."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class StorePathError(ValueError):
    """Raised when a store path is empty, unsafe, or outside its root."""


def reject_network_path(value: str | os.PathLike[str]) -> None:
    """Reject UNC/network-style paths before platform normalization."""

    text = os.fspath(value).replace("\\", "/")
    if text.startswith("//"):
        raise StorePathError("network store paths are not allowed")


def reject_symlink_components(value: str | os.PathLike[str]) -> None:
    """Reject user-controlled symlink components while allowing OS temp aliases."""

    path = Path(os.fspath(value)).expanduser()
    current = Path(path.anchor) if path.anchor else Path(".")
    trusted_aliases = {
        Path(tempfile.gettempdir()),
        Path(os.sep) / "tmp",
        Path(tempfile.gettempdir()).resolve(),
        Path("/var"),
        Path("/var").resolve(),
    }
    for component in path.parts[1:] if path.anchor else path.parts:
        current /= component
        if current.is_symlink() and current not in trusted_aliases:
            raise StorePathError(f"symlink path component is not allowed: {current}")


@dataclass(frozen=True)
class StoreLocation:
    """Resolved data root and the source that won precedence."""

    root: Path
    source: str
    exists: bool

    def database(self, name: str) -> Path:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise StorePathError("database name must be a single non-empty filename")
        reject_symlink_components(self.root)
        candidate = self.root / name
        if candidate.is_symlink():
            raise StorePathError(f"database symlink is not allowed: {candidate}")
        return candidate

    def ensure_root(self) -> Path:
        """Create the canonical root with private permissions when requested."""

        reject_symlink_components(self.root)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass
        return self.root


def _candidate(value: str | os.PathLike[str] | None, label: str) -> Path | None:
    if value is None:
        return None
    text = os.fspath(value).strip()
    if not text:
        raise StorePathError(f"{label} cannot be empty")
    reject_network_path(text)
    path = Path(text).expanduser()
    if path == Path("/"):
        raise StorePathError("store root cannot be filesystem root")
    return path


def resolve_store_location(
    *,
    data_dir: str | os.PathLike[str] | None = None,
    environ: dict[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    repo_root: str | os.PathLike[str] | None = None,
    temp_dir: str | os.PathLike[str] | None = None,
    allow_temp: bool = False,
) -> StoreLocation:
    """Resolve store root with scoped ``.simplicio/data`` policy.

    Precedence:

    1. ``data_dir`` flag
    2. ``SIMPLICIO_DATA_DIR`` / ``SIMPLICIO_CORE_DATA_DIR``
    3. Project scope when ``repo_root`` is set (or ``SIMPLICIO_STORE_SCOPE=repo``):
       ``<repo>/.simplicio/data/<project_slug>``
    4. Core/runtime default: ``~/.simplicio/data`` (or ``$SIMPLICIO_HOME/.../data``)
    5. Explicit temp only when ``allow_temp=True``

    Resolution never creates a directory unless callers use ``ensure_root``.
    """

    env = os.environ if environ is None else environ

    def location(path: Path, source: str) -> StoreLocation:
        reject_symlink_components(path)
        resolved = path.resolve()
        return StoreLocation(resolved, source, resolved.exists())

    explicit = _candidate(data_dir, "data_dir")
    if explicit is not None:
        return location(explicit, "flag")

    core_env = env.get("SIMPLICIO_CORE_DATA_DIR") or env.get("SIMPLICIO_DATA_DIR")
    configured = _candidate(core_env, "SIMPLICIO_DATA_DIR")
    # Only use env as global root when not resolving a project-scoped path.
    project_scope = repo_root is not None or env.get("SIMPLICIO_STORE_SCOPE") == "repo"
    if configured is not None and not project_scope:
        return location(configured, "env")

    if project_scope and repo_root is not None:
        from .project_scope import project_data_root

        root, slug, slug_source = project_data_root(repo_root, environ=env)
        return location(root, f"project:{slug}:{slug_source}")

    if repo_root is not None and env.get("SIMPLICIO_STORE_SCOPE") == "repo":
        repo = _candidate(repo_root, "repo_root")
        assert repo is not None
        return location(repo / ".simplicio" / "data", "repo")

    # Core / Runtime default: ~/.simplicio/data (never bare ~/data)
    from .project_scope import core_data_root

    home_path = _candidate(home, "home")
    if home_path is None and "SIMPLICIO_HOME" not in env and "USERPROFILE" not in env and "HOME" not in env:
        if allow_temp:
            temporary = _candidate(temp_dir, "temp_dir")
            if temporary is None:
                temporary = Path(tempfile.gettempdir()) / "simplicio-mapper-store"
            return location(temporary, "temp")
        raise StorePathError(
            "no store root resolved; pass data_dir, SIMPLICIO_DATA_DIR, or allow_temp=True"
        )
    try:
        return location(core_data_root(environ=env, home=home_path), "core:.simplicio/data")
    except Exception:
        if allow_temp:
            temporary = _candidate(temp_dir, "temp_dir")
            if temporary is None:
                temporary = Path(tempfile.gettempdir()) / "simplicio-mapper-store"
            return location(temporary, "temp")
        raise


def assert_within_root(root: Path, candidate: Path) -> Path:
    """Return a resolved candidate only when it remains below ``root``."""

    reject_network_path(root)
    reject_network_path(candidate)
    reject_symlink_components(root)
    reject_symlink_components(candidate)
    root_resolved = root.resolve()
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as error:
        raise StorePathError(f"path escapes authorized store root: {candidate}") from error
    if candidate.is_symlink():
        raise StorePathError(f"symlink escape is not allowed: {candidate}")
    return candidate_resolved
