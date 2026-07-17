"""Pure, testable git-identity resolution for the canonical-map design (issue #236).

This module implements *only* migration-plan step 2 from
``.specs/architecture/ADR-008-canonical-map-overlays.md``: resolving the
identity fields needed to construct a
:class:`simplicio_mapper.mapper.canonical.CanonicalMapKey` --

- ``repo_identity`` -- stable hash of the normalized ``origin`` remote URL,
  or (when there is no remote) a hash of the absolute, canonical
  ``git rev-parse --git-common-dir`` path.
- ``default_branch`` -- resolved via
  ``git symbolic-ref refs/remotes/origin/HEAD``, falling back to
  ``git remote show origin`` and then to a ``main`` -> ``master`` -> first
  local branch heuristic. Never hardcoded.
- ``commit_sha`` / ``tree_sha`` -- of the commit the resolved default branch
  currently points to.
- ``common_git_dir`` -- the absolute path from
  ``git rev-parse --git-common-dir``, needed later (a future step, out of
  scope here) for the content-addressed storage location.

Every function here is a pure, read-only wrapper around ``git`` subprocess
calls (mirrors the error-handling shape of
``simplicio_mapper.cli._index_engine._git_signature``) -- nothing performs
writes, and nothing in this module is wired into the existing index/scan
pipeline or into ``mapper.canonical`` construction. No production code path
calls these functions yet; see the ADR's migration plan, steps 3+, for the
follow-up that actually builds a ``CanonicalMapManifest`` from this
identity.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit

_GIT_TIMEOUT_SECONDS = 5.0
_REMOTE_SHOW_TIMEOUT_SECONDS = 10.0
_HEAD_BRANCH_RE = re.compile(r"^\s*HEAD branch:\s*(\S+)\s*$", re.MULTILINE)
_SCP_LIKE_RE = re.compile(r"^(?:[\w.-]+@)?([\w.-]+):(.+)$")


@dataclass(frozen=True)
class ResolvedRepoIdentity:
    """Git-derived identity fields for a ``CanonicalMapKey`` (ADR-008 step 2).

    Every field is resolved by inspecting the repository at ``root`` -- none
    of them is ever hardcoded or silently defaulted, matching the ADR's
    explicit-invalidation requirement for ``CanonicalMapKey``.
    """

    repo_identity: str
    default_branch: str
    commit_sha: str
    tree_sha: str
    common_git_dir: str


def _run_git(
    args: list[str], cwd: str, timeout: float = _GIT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess | None:
    """Run a read-only ``git`` subprocess, or ``None`` if it could not run at all.

    A non-zero exit code is still returned to the caller (callers decide
    whether that means "not found" vs. a real error) -- only OS-level spawn
    failures and timeouts collapse to ``None`` here, mirroring
    ``_index_engine._git_signature``'s error handling.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def is_git_repository(root: str) -> bool:
    """Return whether ``root`` is inside a git working tree."""
    result = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    return bool(result) and result.returncode == 0 and result.stdout.strip() == "true"


def resolve_common_git_dir(root: str) -> str | None:
    """Return the absolute, canonical common git dir shared across worktrees.

    ``git rev-parse --git-common-dir`` already resolves to the shared
    ``.git`` for any worktree of the same repository (including the main
    worktree) -- this just makes the result absolute/canonical so two
    worktrees of the same repo always compare equal.
    """
    result = _run_git(["rev-parse", "--git-common-dir"], root)
    if not result or result.returncode != 0:
        return None
    raw = result.stdout.strip()
    if not raw:
        return None
    if not os.path.isabs(raw):
        raw = os.path.join(root, raw)
    return os.path.realpath(raw)


def resolve_origin_url(root: str) -> str | None:
    """Return the raw ``origin`` remote URL, or ``None`` if there is none."""
    result = _run_git(["remote", "get-url", "origin"], root)
    if not result or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def normalize_remote_url(url: str) -> str:
    """Normalize a git remote URL to a stable, scheme/case-insensitive form.

    Handles the three common shapes: ``https://host/org/repo.git``,
    scp-like ``git@host:org/repo.git``, and ``ssh://git@host/org/repo.git``
    (plus ``file://`` URLs used by local-remote test fixtures), collapsing
    them to ``<lowercased-host><path-without-.git-suffix>`` so equivalent
    remotes hash to the same ``repo_identity``.
    """
    value = url.strip()
    if not value:
        return ""
    if "://" not in value:
        scp_match = _SCP_LIKE_RE.match(value)
        if scp_match:
            host, path = scp_match.groups()
            value = f"ssh://{host}/{path}"
    parsed = urlsplit(value)
    host = parsed.netloc.split("@")[-1].lower()
    path = parsed.path
    if path.endswith(".git"):
        path = path[: -len(".git")]
    path = path.rstrip("/")
    if host:
        if path and not path.startswith("/"):
            path = f"/{path}"
        return f"{host}{path}"
    return path.lstrip("/").lower()


def _stable_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=24).hexdigest()


def resolve_repo_identity(root: str) -> str | None:
    """Resolve ``CanonicalMapKey.repo_identity`` for the repo at ``root``.

    Prefers a hash of the normalized ``origin`` remote URL (shared by every
    clone/worktree pointing at the same remote); falls back to a hash of the
    absolute common git dir when there is no ``origin`` remote configured.
    """
    origin_url = resolve_origin_url(root)
    if origin_url:
        normalized = normalize_remote_url(origin_url)
        if normalized:
            return _stable_hash(f"origin-url:{normalized}")
    common_git_dir = resolve_common_git_dir(root)
    if not common_git_dir:
        return None
    return _stable_hash(f"common-git-dir:{common_git_dir}")


def _list_local_branches(root: str) -> list[str]:
    result = _run_git(
        ["for-each-ref", "--format=%(refname:short)", "--sort=refname", "refs/heads/"],
        root,
    )
    if not result or result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def resolve_default_branch(root: str) -> str | None:
    """Resolve the default branch name -- never hardcoded.

    Order: ``git symbolic-ref refs/remotes/origin/HEAD`` (the canonical
    signal once a remote has been fetched/cloned with a HEAD ref), then
    ``git remote show origin`` (works against a live remote without a local
    ``refs/remotes/origin/HEAD``), then a local heuristic (``main`` ->
    ``master`` -> first local branch alphabetically) for repositories with no
    remote at all.
    """
    symbolic = _run_git(["symbolic-ref", "refs/remotes/origin/HEAD"], root)
    if symbolic and symbolic.returncode == 0:
        ref = symbolic.stdout.strip()
        if ref:
            return ref.rsplit("/", 1)[-1]

    remote_show = _run_git(
        ["remote", "show", "origin"], root, timeout=_REMOTE_SHOW_TIMEOUT_SECONDS
    )
    if remote_show and remote_show.returncode == 0:
        match = _HEAD_BRANCH_RE.search(remote_show.stdout)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate != "(unknown)":
                return candidate

    local_branches = _list_local_branches(root)
    if "main" in local_branches:
        return "main"
    if "master" in local_branches:
        return "master"
    if local_branches:
        return local_branches[0]
    return None


def resolve_branch_commit_sha(root: str, branch: str) -> str | None:
    """Resolve the commit SHA the given branch name currently points to.

    Tries the remote-tracking ref first (``refs/remotes/origin/<branch>``),
    then the local branch ref (``refs/heads/<branch>``), then falls back to
    a bare revision lookup -- covers both "cloned repo with a remote" and
    "local-only repo" shapes without guessing which one applies.
    """
    for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}", branch):
        result = _run_git(["rev-parse", "--verify", ref], root)
        if result and result.returncode == 0:
            sha = result.stdout.strip()
            if sha:
                return sha
    return None


def resolve_commit_tree_sha(root: str, commit_sha: str) -> str | None:
    """Resolve the root tree SHA for the given commit SHA."""
    result = _run_git(["rev-parse", "--verify", f"{commit_sha}^{{tree}}"], root)
    if not result or result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def resolve_repo_identity_bundle(root: str) -> ResolvedRepoIdentity | None:
    """Resolve every ``CanonicalMapKey`` identity field for the repo at ``root``.

    Returns ``None`` (never a partially-populated result) when ``root`` is
    not a git repository or any required field fails to resolve -- callers
    must treat a ``None`` result as "no canonical identity available", not
    silently proceed with defaults.
    """
    if not is_git_repository(root):
        return None
    common_git_dir = resolve_common_git_dir(root)
    if not common_git_dir:
        return None
    default_branch = resolve_default_branch(root)
    if not default_branch:
        return None
    commit_sha = resolve_branch_commit_sha(root, default_branch)
    if not commit_sha:
        return None
    tree_sha = resolve_commit_tree_sha(root, commit_sha)
    if not tree_sha:
        return None
    repo_identity = resolve_repo_identity(root)
    if not repo_identity:
        return None
    return ResolvedRepoIdentity(
        repo_identity=repo_identity,
        default_branch=default_branch,
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        common_git_dir=common_git_dir,
    )
