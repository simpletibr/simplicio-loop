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
    """Resolve ``data_dir > SIMPLICIO_DATA_DIR > home > explicit temp``.

    Resolution never creates a directory. A temporary root is accepted only
    when the caller explicitly opts in, preventing read-only/status calls from
    silently creating state in a shared system temp directory.
    """

    env = os.environ if environ is None else environ

    def location(path: Path, source: str) -> StoreLocation:
        reject_symlink_components(path)
        resolved = path.resolve()
        return StoreLocation(resolved, source, resolved.exists())

    explicit = _candidate(data_dir, "data_dir")
    if explicit is not None:
        return location(explicit, "flag")

    configured = _candidate(env.get("SIMPLICIO_DATA_DIR"), "SIMPLICIO_DATA_DIR")
    if configured is not None:
        return location(configured, "env")

    home_path = _candidate(home, "home")
    if home_path is None and "SIMPLICIO_HOME" in env:
        home_path = _candidate(env["SIMPLICIO_HOME"], "SIMPLICIO_HOME")
    if repo_root is not None and env.get("SIMPLICIO_STORE_SCOPE") == "repo":
        repo = _candidate(repo_root, "repo_root")
        assert repo is not None
        return location(repo / ".simplicio" / "data", "repo")
    if home_path is not None:
        return location(home_path / "data", "home")

    if allow_temp:
        temporary = _candidate(temp_dir, "temp_dir")
        if temporary is None:
            temporary = Path(tempfile.gettempdir()) / "simplicio-mapper-store"
        return location(temporary, "temp")
    raise StorePathError("no store root resolved; pass data_dir, SIMPLICIO_DATA_DIR, or allow_temp=True")


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
