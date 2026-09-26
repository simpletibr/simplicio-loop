"""Token-efficient execution primitives for deterministic Simplicio handoffs."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from .utils.fs import write_text_atomic

LOG_SUMMARY_SCHEMA = "simplicio.log-summary/v1"
DIFF_REVIEW_SCHEMA = "simplicio.diff-review/v1"
CONTEXT_CACHE_SCHEMA = "simplicio.context-cache/v1"
POSTCONDITIONS_SCHEMA = "simplicio.postconditions/v1"
RETRY_SCHEMA = "simplicio.retry/v1"
MODEL_ROUTING_SCHEMA = "simplicio.model-routing/v1"
CODEMOD_PLAN_SCHEMA = "simplicio.codemod-plan/v1"


def sha256_text(text: str | bytes) -> str:
    if isinstance(text, str):
        text = text.encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def summarize_log(log: str, *, max_chars: int = 1200) -> dict[str, Any]:
    """Return a compact, machine-readable log summary.

    The summary keeps head/tail context and lines that look actionable, while
    avoiding a full-log handoff back to an LLM.
    """
    max_chars = max(120, int(max_chars))
    lines = log.splitlines()
    interesting = [
        line
        for line in lines
        if any(
            marker in line.lower()
            for marker in (
                "error",
                "failed",
                "failure",
                "traceback",
                "exception",
                "assert",
                "timeout",
                "warning",
            )
        )
    ]
    parts: list[str] = []
    if lines:
        parts.extend(lines[:8])
    if interesting:
        parts.append("--- actionable lines ---")
        parts.extend(interesting[:20])
    if len(lines) > 12:
        parts.append("--- tail ---")
        parts.extend(lines[-8:])
    summary = _compact_text("\n".join(parts), max_chars=max_chars)
    return {
        "schema": LOG_SUMMARY_SCHEMA,
        "original_chars": len(log),
        "original_lines": len(lines),
        "summary": summary,
        "summary_chars": len(summary),
        "truncated": len(summary) < len(log),
        "hash": sha256_text(log),
    }


def git_diff_review(root: str | Path = ".", *, max_patch_chars: int = 4000) -> dict[str, Any]:
    root_path = Path(root)
    name_proc = _run_git(root_path, ["diff", "--name-only"])
    numstat_proc = _run_git(root_path, ["diff", "--numstat"])
    patch_proc = _run_git(root_path, ["diff", "--no-ext-diff", "--"])
    files = [line for line in name_proc.stdout.splitlines() if line.strip()]
    stats = []
    for line in numstat_proc.stdout.splitlines():
        added, removed, path = (line.split("\t") + ["", "", ""])[:3]
        stats.append(
            {
                "path": path,
                "added": _numstat_int(added),
                "removed": _numstat_int(removed),
            }
        )
    patch = _compact_text(patch_proc.stdout, max_chars=max_patch_chars)
    return {
        "schema": DIFF_REVIEW_SCHEMA,
        "root": str(root_path),
        "files_changed": files,
        "stats": stats,
        "patch": patch,
        "patch_chars": len(patch),
        "full_patch_hash": sha256_text(patch_proc.stdout),
        "truncated": len(patch) < len(patch_proc.stdout),
    }


class ContextCache:
    """Small content-hash cache for mapper/context summaries."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)
        self.path = self.root / ".simplicio-loop" / "context-cache.json"

    def get(self, key: str, content: str) -> dict[str, Any]:
        digest = sha256_text(content)
        store = self._read()
        item = store.get(key)
        if not item:
            return {
                "schema": CONTEXT_CACHE_SCHEMA,
                "key": key,
                "hash": digest,
                "hit": False,
                "reason": "missing",
            }
        if item.get("hash") != digest:
            return {
                "schema": CONTEXT_CACHE_SCHEMA,
                "key": key,
                "hash": digest,
                "hit": False,
                "reason": "hash_mismatch",
            }
        return {
            "schema": CONTEXT_CACHE_SCHEMA,
            "key": key,
            "hash": digest,
            "hit": True,
            "summary": item.get("summary"),
        }

    def put(self, key: str, content: str, summary: Any) -> dict[str, Any]:
        digest = sha256_text(content)
        store = self._read()
        store[key] = {"hash": digest, "summary": summary}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "schema": CONTEXT_CACHE_SCHEMA,
            "key": key,
            "hash": digest,
            "hit": False,
            "stored": True,
            "summary": summary,
        }

    def invalidate(self, key: str | None = None) -> dict[str, Any]:
        store = self._read()
        if key is None:
            removed = len(store)
            store = {}
        else:
            removed = 1 if key in store else 0
            store.pop(key, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(self.path, json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")
        return {"schema": CONTEXT_CACHE_SCHEMA, "removed": removed}

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def evaluate_postconditions(checks: list[dict[str, Any]], *, root: str | Path = ".") -> dict[str, Any]:
    root_path = Path(root)
    rows = [_evaluate_one_postcondition(check, root_path) for check in checks]
    return {
        "schema": POSTCONDITIONS_SCHEMA,
        "root": str(root_path),
        "passed": all(row["passed"] for row in rows),
        "checks": rows,
    }


def build_retry_payload(
    *,
    reason: str,
    failure: dict[str, Any],
    log: str = "",
    max_log_chars: int = 1000,
) -> dict[str, Any]:
    return {
        "schema": RETRY_SCHEMA,
        "reason": reason,
        "failure": failure,
        "log_summary": summarize_log(log, max_chars=max_log_chars),
        "safety": {
            "full_log_included": False,
            "retry_unbounded": False,
            "request_corrected_plan": True,
        },
    }


def model_routing_decision(context: dict[str, Any]) -> dict[str, Any]:
    risk = str(context.get("risk", "medium")).lower()
    work = str(context.get("work", context.get("operation", ""))).lower()
    ambiguous = bool(context.get("ambiguous"))
    repetitive = "repetitive" in work or work in {"formatting", "bulk", "mechanical"}
    if risk == "low" and repetitive and not ambiguous:
        profile = "mass"
        reason = "low-risk repetitive work can use the cheapest deterministic/local lane"
    elif risk == "high" or ambiguous or "architecture" in work:
        profile = "deep"
        reason = "high-risk or ambiguous work benefits from deeper reasoning"
    else:
        profile = "research"
        reason = "bounded implementation or synthesis needs normal repo-aware reasoning"
    return {
        "schema": MODEL_ROUTING_SCHEMA,
        "profile": profile,
        "reason": reason,
        "local_first": True,
        "remote_allowed": bool(context.get("remote_allowed", False)),
        "allow_delegation": profile != "mass",
        "context": {
            "risk": risk,
            "work": work or None,
            "changed_files": context.get("changed_files"),
            "ambiguous": ambiguous,
        },
    }


def codemod_plan(
    *,
    language: str,
    operation: str,
    paths: list[str],
    description: str = "",
) -> dict[str, Any]:
    return {
        "schema": CODEMOD_PLAN_SCHEMA,
        "language": language,
        "operation": operation,
        "paths": paths,
        "description": description,
        "deterministic": True,
        "requires_review": operation not in {"rename_identifier", "json_patch"},
    }


def _evaluate_one_postcondition(check: dict[str, Any], root: Path) -> dict[str, Any]:
    kind = str(check.get("type", ""))
    if kind in {"file_exists", "contains", "not_contains"}:
        rel = str(check.get("path", ""))
        path = root / rel
        if kind == "file_exists":
            return {"type": kind, "path": rel, "passed": path.is_file()}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            return {"type": kind, "path": rel, "passed": False, "error": str(exc)}
        needle = str(check.get("text", ""))
        found = needle in text
        return {
            "type": kind,
            "path": rel,
            "text_hash": sha256_text(needle),
            "passed": found if kind == "contains" else not found,
        }
    if kind == "command":
        cmd = check.get("cmd")
        if not isinstance(cmd, list) or not all(isinstance(item, str) for item in cmd):
            return {"type": kind, "passed": False, "error": "cmd must be list[str]"}
        try:
            proc = subprocess.run(
                cmd,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=int(check.get("timeout", 120)),
            )
        except Exception as exc:
            return {"type": kind, "cmd": cmd, "passed": False, "error": str(exc)}
        log = (proc.stdout or "") + (proc.stderr or "")
        return {
            "type": kind,
            "cmd": cmd,
            "passed": proc.returncode == 0,
            "returncode": proc.returncode,
            "log_summary": summarize_log(log),
        }
    return {"type": kind, "passed": False, "error": "unknown postcondition type"}


def _compact_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    marker = "\n...[truncated]...\n"
    if max_chars <= len(marker) + 20:
        return text[:max_chars]
    head_len = max_chars // 2
    tail_len = max_chars - head_len - len(marker)
    return text[:head_len].rstrip() + marker + text[-tail_len:].lstrip()


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _numstat_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None
