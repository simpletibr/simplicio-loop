"""Git-backed repository and worktree discovery for the Map Service.

The registry key is repository-scoped, while each worktree keeps its own HEAD, branch,
and dirty state. All discovery is local and read-only; no remote or mapper invocation is
performed here.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from simplicio_loop.map_service import RepositoryIdentity


class GitDiscoveryError(RuntimeError):
    """Raised when a path is not a usable Git worktree."""


class GitIdentityError(GitDiscoveryError):
    """Raised when a path cannot be converted to a Map Service identity."""


def _git(root: Path, args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(root), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise GitDiscoveryError("git is unavailable: %s" % exc) from exc
    if result.returncode:
        raise GitDiscoveryError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _git_identity(path: str, *args: str, strip: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        raise GitIdentityError(
            "git %s failed in %s: %s" % (" ".join(args), path, result.stderr.strip())
        )
    return result.stdout.strip() if strip else result.stdout


def _ref_exists(path: str, ref: str) -> bool:
    try:
        _git_identity(path, "rev-parse", "--verify", "-q", ref + "^{commit}")
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        return False
    return True


def default_branch_ref(path: str) -> Optional[Tuple[str, str]]:
    """Return ``(branch, full_ref)`` of the repository default branch, or ``None``.

    Order: the target of ``refs/remotes/origin/HEAD``, then ``main``, then ``master``; each prefers
    its ``refs/remotes/origin/`` remote-tracking ref over the local branch. A worktree's own
    branch is never a candidate: the central base is the same for every worktree.
    """
    try:
        target = _git_identity(path, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        target = ""
    if target.startswith("refs/remotes/origin/"):
        branch = target[len("refs/remotes/origin/"):]
        if _ref_exists(path, target):
            return branch, target
    for branch in ("main", "master"):
        for ref in ("refs/remotes/origin/" + branch, "refs/heads/" + branch):
            if _ref_exists(path, ref):
                return branch, ref
    return None


def _default_branch(path: str) -> str:
    found = default_branch_ref(path)
    if found is not None:
        return found[0]
    try:
        return _git_identity(path, "symbolic-ref", "--short", "HEAD")
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        return "main"


def git_common_dir(path: str) -> Path:
    """Absolute, resolved ``--git-common-dir``: the same directory for every linked worktree."""
    raw = _git_identity(path, "rev-parse", "--git-common-dir")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path(path) / candidate
    return candidate.resolve()


@dataclass(frozen=True)
class DefaultBase:
    """The default-branch commit every worktree of a repository is mapped against."""

    branch: str
    ref: str
    commit: str
    tree: str


def resolve_default_base(path: str) -> Optional[DefaultBase]:
    """The central base of ``path``'s repository (``None`` when no default branch exists)."""
    found = default_branch_ref(path)
    if found is None:
        return None
    branch, ref = found
    try:
        commit = _git_identity(path, "rev-parse", ref + "^{commit}")
        tree = _git_identity(path, "rev-parse", ref + "^{tree}")
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        return None
    return DefaultBase(branch=branch, ref=ref, commit=commit, tree=tree)


def merge_base_tree(path: str, ref: str) -> Optional[str]:
    """Tree sha of ``merge-base(HEAD, ref)`` for the worktree at ``path`` (its fork point)."""
    try:
        commit = _git_identity(path, "merge-base", "HEAD", ref)
        return _git_identity(path, "rev-parse", commit + "^{tree}")
    except (GitIdentityError, OSError, subprocess.SubprocessError):
        return None


def _dirty_fingerprint(path: str, status_output: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(_git_identity(path, "diff", "HEAD").encode("utf-8"))
    for line in status_output.splitlines():
        if line.startswith("??"):
            try:
                hasher.update((Path(path) / line[3:].strip()).read_bytes())
            except OSError:
                pass
    return hasher.hexdigest()


def _repository_label(canonical_root: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", canonical_root, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except OSError:
        pass
    return canonical_root


def resolve_repository_identity(path: str, *, mapper_config: str = "") -> RepositoryIdentity:
    """Resolve the content/branch identity used by the original Map Service adapter."""
    resolved = str(Path(path).expanduser().resolve(strict=True))
    try:
        this_root = _git_identity(resolved, "rev-parse", "--show-toplevel")
    except GitIdentityError as exc:
        raise GitIdentityError("%s is not inside a Git working tree" % path) from exc
    listing = _git_identity(resolved, "worktree", "list", "--porcelain")
    roots = [line[9:].strip() for line in listing.splitlines() if line.startswith("worktree ")]
    if not roots:
        raise GitIdentityError("git worktree list returned no entries for %s" % path)
    canonical_root = roots[0]
    worktree_root = None if Path(this_root).resolve() == Path(canonical_root).resolve() else this_root
    base_sha = _git_identity(resolved, "rev-parse", "HEAD")
    status = _git_identity(resolved, "status", "--porcelain")
    return RepositoryIdentity(
        repository=_repository_label(canonical_root), canonical_root=canonical_root,
        default_branch=_default_branch(resolved), worktree_root=worktree_root,
        base_sha=base_sha, dirty=bool(status),
        dirty_fingerprint=_dirty_fingerprint(resolved, status) if status else "",
        mapper_config=mapper_config,
    )


def real_tree_snapshot(path: str) -> Tuple[str, List[str]]:
    """Return a content-derived tree hash and the real tracked file paths.

    ``-z``: git prints names with a quote, backslash, TAB or newline C-quoted otherwise, and the
    returned paths would not exist on disk.
    """
    resolved = str(Path(path).expanduser().resolve(strict=True))
    listing = _git_identity(resolved, "ls-files", "-s", "-z", strip=False)
    entries = [item for item in listing.split("\0") if item]
    if not entries:
        return hashlib.sha256(b"empty-tree").hexdigest(), []
    blob_shas = sorted(item.split("\t", 1)[0].split()[1] for item in entries)
    files = [item.split("\t", 1)[1] for item in entries]
    return hashlib.sha256("".join(blob_shas).encode("utf-8")).hexdigest(), [
        str(Path(resolved) / file) for file in sorted(set(files))
    ]


def _normalize_remote(remote: str) -> str:
    value = str(remote).strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@") and ":" in value:
        value = "https://" + value.split(":", 1)[1]
    return value.rstrip("/").lower()


@dataclass(frozen=True)
class GitWorktree:
    path: str
    head: str
    branch: str = ""
    detached: bool = False


@dataclass(frozen=True)
class RepositoryRecord:
    repository_key: str
    common_dir: str
    remote: str
    first_commit: str
    worktrees: tuple[GitWorktree, ...]


def list_worktrees(root: str) -> List[GitWorktree]:
    """Return every worktree Git associates with ``root`` using porcelain output."""
    base = Path(root).expanduser().resolve()
    output = _git(base, ["worktree", "list", "--porcelain"])
    records: List[GitWorktree] = []
    current: Dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current.get("worktree") and current.get("HEAD"):
            branch = current.get("branch", "")
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
            records.append(GitWorktree(
                path=str(Path(current["worktree"]).resolve()),
                head=current["HEAD"],
                branch=branch,
                detached="detached" in current,
            ))
        current = {}

    for line in output.splitlines() + [""]:
        if not line:
            flush()
        elif line.startswith("worktree "):
            current["worktree"] = line[9:]
        elif line.startswith("HEAD "):
            current["HEAD"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line == "detached":
            current["detached"] = "1"
    return records


def discover(root: str) -> RepositoryRecord:
    """Discover one repository identity and all currently attached worktrees."""
    base = Path(_git(Path(root), ["rev-parse", "--show-toplevel"])).resolve()
    common_raw = Path(_git(base, ["rev-parse", "--git-common-dir"]))
    common = (base / common_raw).resolve() if not common_raw.is_absolute() else common_raw.resolve()
    try:
        remote_raw = _git(base, ["config", "--get", "remote.origin.url"])
    except GitDiscoveryError:
        remote_raw = ""
    remote = _normalize_remote(remote_raw)
    first_commit = _git(base, ["rev-list", "--max-parents=0", "HEAD"]).splitlines()[0]
    identity_source = "\n".join((remote, str(common), first_commit)).encode("utf-8")
    repository_key = hashlib.sha256(identity_source).hexdigest()
    return RepositoryRecord(repository_key, str(common), remote, first_commit, tuple(list_worktrees(str(base))))


class RepositoryWorktreeRegistry:
    """Refreshable repository-keyed registry that handles worktree add/remove."""

    def __init__(self) -> None:
        self._records: Dict[str, RepositoryRecord] = {}

    def refresh(self, root: str) -> RepositoryRecord:
        record = discover(root)
        self._records[record.repository_key] = record
        return record

    def get(self, repository_key: str) -> RepositoryRecord:
        try:
            return self._records[str(repository_key)]
        except KeyError as exc:
            raise GitDiscoveryError("unknown repository key") from exc

    def remove_missing_worktrees(self, repository_key: str, root: str) -> RepositoryRecord:
        return self.refresh(root)

    def status(self) -> Dict[str, object]:
        return {
            "schema": "simplicio.map-service-git-registry/v1",
            "repositories": len(self._records),
            "worktrees": sum(len(record.worktrees) for record in self._records.values()),
            "repository_keys": sorted(self._records),
        }


__all__ = [
    "DefaultBase", "GitDiscoveryError", "GitIdentityError", "GitWorktree", "RepositoryRecord",
    "RepositoryWorktreeRegistry", "default_branch_ref", "discover", "git_common_dir",
    "list_worktrees", "merge_base_tree", "real_tree_snapshot", "resolve_default_base",
    "resolve_repository_identity",
]
