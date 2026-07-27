"""Bounded, privacy-safe Git history handles for ContextGraph consumers."""

from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
import subprocess
from typing import Any, Sequence

HISTORY_SCHEMA = "simplicio.context-history/v1"
_MAX_COMMITS = 1000
_MAX_FILES_PER_COMMIT = 200


class HistoryError(ValueError):
    """Fail-closed error raised when the history boundary is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _canonical(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _relative_path(value: str, *, field: str = "path") -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise HistoryError("HISTORY_PATH_INVALID", f"{field} is invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise HistoryError("HISTORY_PATH_ESCAPE", f"{field} escapes the repository root")
    return path.as_posix()


def _git(root: Path, args: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        close_fds=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or "git command failed"
        raise HistoryError("HISTORY_GIT_FAILED", detail)
    return result.stdout


def _repo_root(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise HistoryError("HISTORY_ROOT_INVALID", "root must be an existing directory")
    actual = Path(_git(resolved, ["rev-parse", "--show-toplevel"]).strip()).resolve()
    if actual != resolved:
        raise HistoryError("HISTORY_ROOT_MISMATCH", "root must be the authorized Git repository root")
    return resolved


def _parse_log(raw: str, *, max_files: int) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in raw.splitlines():
        if line.startswith("commit:"):
            if current is not None:
                commits.append(current)
            fields = line[7:].split("\t", 2)
            if len(fields) != 3 or len(fields[0]) != 40:
                raise HistoryError("HISTORY_LOG_INVALID", "Git log commit header is malformed")
            parents = [item for item in fields[2].split() if item]
            current = {"commit": fields[0], "timestamp": int(fields[1]), "parents": parents, "changes": []}
            continue
        if current is None or not line or "\t" not in line:
            continue
        status, *paths = line.split("\t")
        if len(current["changes"]) >= max_files:
            continue
        if status.startswith(("R", "C")) and len(paths) >= 2:
            previous = _relative_path(paths[0], field="previous_path")
            path = _relative_path(paths[1])
            kind = "renamed" if status.startswith("R") else "copied"
        elif paths:
            previous = None
            path = _relative_path(paths[-1])
            kind = {"A": "added", "M": "modified", "D": "deleted"}.get(status[:1], "changed")
        else:
            continue
        current["changes"].append({"path": path, "previous_path": previous, "kind": kind})
    if current is not None:
        commits.append(current)
    return commits


def _history_command(
    *,
    max_commits: int,
    max_files_per_commit: int,
    paths: Sequence[str] | None,
    after_commit: str | None,
) -> list[str]:
    command = [
        "log",
        "--reverse",
        "--topo-order",
        f"--max-count={max_commits}",
        "--format=commit:%H%x09%ct%x09%P",
        "--name-status",
        "-M",
        f"--max-count={max_commits}",
    ]
    if after_commit:
        command.append(f"{after_commit}..HEAD")
    if paths:
        command.extend(["--", *paths])
    return command


def _validate_limit(value: int, *, field: str, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise HistoryError("HISTORY_BUDGET_INVALID", f"{field} must be between 1 and {maximum}")
    return value


def _validate_commit(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise HistoryError("HISTORY_COMMIT_INVALID", "after_commit must be a full hexadecimal commit id")
    return value


def build_git_history(
    root: str | Path,
    *,
    max_commits: int = 50,
    max_files_per_commit: int = 200,
    paths: Sequence[str] | None = None,
    after_commit: str | None = None,
) -> dict[str, Any]:
    """Return bounded commit/file/change handles without diff or author content."""
    max_commits = _validate_limit(max_commits, field="max_commits", maximum=_MAX_COMMITS)
    max_files_per_commit = _validate_limit(
        max_files_per_commit, field="max_files_per_commit", maximum=_MAX_FILES_PER_COMMIT
    )
    after_commit = _validate_commit(after_commit)
    normalized_paths = tuple(_relative_path(path) for path in (paths or ()))
    repo = _repo_root(Path(root))
    raw = _git(
        repo,
        _history_command(
            max_commits=max_commits,
            max_files_per_commit=max_files_per_commit,
            paths=normalized_paths,
            after_commit=after_commit,
        ),
    )
    parsed = _parse_log(raw, max_files=max_files_per_commit)
    head_result = _git(repo, ["rev-parse", "HEAD"]).strip()
    shallow = _git(repo, ["rev-parse", "--is-shallow-repository"]).strip().lower() == "true"
    root_id = hashlib.sha256(str(repo).casefold().encode("utf-8")).hexdigest()[:16]
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    handles: list[dict[str, Any]] = []

    def add_node(node_id: str, kind: str, **payload: Any) -> None:
        nodes.setdefault(node_id, {"id": node_id, "kind": kind, **payload})

    def add_edge(kind: str, source: str, target: str, **payload: Any) -> None:
        edge_id = f"edge:{_canonical({'kind': kind, 'source': source, 'target': target})}"
        edges.setdefault(edge_id, {"id": edge_id, "kind": kind, "source": source, "target": target, **payload})

    for commit in parsed:
        commit_id = f"commit:{commit['commit']}"
        changes = []
        add_node(commit_id, "commit", commit=commit["commit"], timestamp=commit["timestamp"], parents=commit["parents"])
        handles.append({"handle": f"history:{commit_id}", "kind": "commit", "expand": {"commit": commit["commit"]}})
        file_ids: list[str] = []
        for change in commit["changes"]:
            path = change["path"]
            file_id = f"file:{path}"
            change_id = f"change:{_canonical({'commit': commit['commit'], **change})}"
            file_ids.append(file_id)
            add_node(file_id, "file", path=path)
            add_node(change_id, "change", commit=commit["commit"], path=path, change_kind=change["kind"])
            add_edge("introduced_by", change_id, commit_id)
            add_edge("last_touched_by", file_id, commit_id)
            if change["previous_path"]:
                previous_id = f"file:{change['previous_path']}"
                add_node(previous_id, "file", path=change["previous_path"])
                add_edge("renamed_from", change_id, previous_id)
            changes.append({"id": change_id, **change})
            handles.append({"handle": f"history:{change_id}", "kind": "change", "expand": {"commit": commit["commit"], "path": path}})
        for left, right in itertools.combinations(sorted(set(file_ids)), 2):
            add_edge("changed_with", left, right, commit=commit["commit"])
        commit["id"] = commit_id
        commit["changes"] = sorted(changes, key=lambda item: item["id"])

    return {
        "schema": HISTORY_SCHEMA,
        "version": 1,
        "repository_root_id": root_id,
        "head": head_result,
        "base_commit": after_commit,
        "commits": parsed,
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": [edges[key] for key in sorted(edges)],
        "handles": sorted(handles, key=lambda item: item["handle"]),
        "budget": {"max_commits": max_commits, "max_files_per_commit": max_files_per_commit},
        "provenance": {
            "redacted_fields": ["author", "author_email", "committer", "committer_email", "subject", "diff"],
            "shallow_repository": shallow,
            "diffs_included": False,
            "deterministic_ids": True,
        },
    }
