"""``file read`` — read raw file contents with optional line-range slicing.

Delegates to the native Rust ``simplicio file read`` binary when available
(via :mod:`simplicio.runtime_bridge`), falling back to a pure-Python
implementation otherwise. Mirrors the Rust CLI contract exactly so either
implementation is interchangeable from the caller's point of view::

    simplicio-dev-cli file read <path> [--json] [--start N] [--end N]
                                 [--max-bytes N] [--repo <path>]

JSON output shape (schema ``simplicio.file-read/v1``)::

    {"schema": "simplicio.file-read/v1", "path": "...", "bytes": N,
     "lines": N, "truncated": bool, "content": "..."}
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..runtime_bridge import discover_simplicio, record_delegation

SCHEMA = "simplicio.file-read/v1"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB
# A file read should be near-instant; this is just a safety net against a
# hung/misbehaving Rust binary, not a tunable (unlike test run's --timeout).
RUNTIME_DELEGATION_TIMEOUT_S = 30.0


def _build_runtime_args(a: argparse.Namespace) -> list[str]:
    cmd = ["file", "read", a.path, "--json"]
    if a.start is not None:
        cmd += ["--start", str(a.start)]
    if a.end is not None:
        cmd += ["--end", str(a.end)]
    if a.max_bytes is not None:
        cmd += ["--max-bytes", str(a.max_bytes)]
    if a.repo:
        cmd += ["--repo", a.repo]
    return cmd


def _run_via_runtime(a: argparse.Namespace) -> tuple[int | None, str | None]:
    """Attempt delegation to the Rust ``simplicio`` binary.

    Returns ``(exit_code, reason)``: ``exit_code`` is the runtime binary's
    exit code on success, or ``None`` so the caller falls back to the
    Python implementation (binary missing, delegation errored, or the
    binary didn't return the expected JSON contract). ``reason`` is a short
    telemetry tag for `runtime_bridge.record_delegation`, always populated
    when ``exit_code`` is ``None``.
    """
    binary = discover_simplicio()
    if binary is None:
        return None, "binary-not-found"
    cmd = [binary, *_build_runtime_args(a)]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=RUNTIME_DELEGATION_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, f"delegation-error: {exc}"

    # Only trust the Rust binary's result if it actually produced the
    # expected JSON envelope — an unimplemented/erroring subcommand prints
    # a plain-text message and exits non-zero, which is indistinguishable
    # from a legitimate error by exit code alone.
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, "invalid-json"
    if payload.get("schema") != SCHEMA:
        return None, "schema-mismatch"

    if a.json:
        print(completed.stdout, end="")
    else:
        print(payload.get("content", ""), end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode, None


def _read_fallback(a: argparse.Namespace) -> tuple[dict | None, str | None]:
    """Read the file per Python fallback rules.

    Returns ``(payload, error_message)`` — exactly one is non-``None``.
    """
    repo_root = Path(a.repo or ".").resolve()
    target = (repo_root / a.path).resolve() if not Path(a.path).is_absolute() else Path(a.path)

    if not target.exists():
        return None, f"file not found: {a.path}"
    if target.is_dir():
        return None, f"path is a directory, not a file: {a.path}"

    max_bytes = a.max_bytes if a.max_bytes is not None else DEFAULT_MAX_BYTES
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return None, f"cannot read {a.path}: {exc}"

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]

    # Decode strictly: this CLI is a direct, local, single-user invocation
    # (not the MCP-exposed path) — a non-UTF8 file is a real error the user
    # should see rather than a silently mangled read.
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"file is not valid UTF-8: {a.path} ({exc})"

    lines = text.splitlines(keepends=True)
    if a.start is not None or a.end is not None:
        start = max(a.start or 1, 1)
        end = a.end if a.end is not None else len(lines)
        # 1-indexed inclusive slice
        text = "".join(lines[start - 1 : end])
        line_count = len(text.splitlines())
    else:
        line_count = len(lines)

    payload = {
        "schema": SCHEMA,
        "path": a.path,
        "bytes": len(text.encode("utf-8")),
        "lines": line_count,
        "truncated": truncated,
        "content": text,
    }
    return payload, None


def _run_fallback(a: argparse.Namespace) -> int:
    payload, error = _read_fallback(a)
    if error is not None:
        print(f"simplicio-dev-cli file read: {error}", file=sys.stderr)
        return 2

    assert payload is not None
    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(payload["content"], end="")
    return 0


def run(a: argparse.Namespace) -> int:
    """Entry point wired from ``cli.py`` for ``simplicio-dev-cli file read``."""
    result, reason = _run_via_runtime(a)
    root = a.repo or "."
    if result is not None:
        record_delegation("file", "native", root=root)
        return result
    record_delegation("file", "python-fallback", root=root, reason=reason)
    return _run_fallback(a)
