"""simplicio.mechanical-edit/v1 — deterministic edit-anchor context (issue #110).

This module provides the mapper-side helpers an LLM planner needs to plan
compact JSON edits without rewriting whole files. It produces:

- snapshot hashes per selected file (full-file content sha256),
- range hashes per selected line range (sha256 of the joined chunk),
- explicit `must_contain` anchors with the first and last line of each
  range, truncated to a short prefix for stability,
- an overall `context_hash` digest over all snapshot + range hashes so the
  consumer can verify the whole context in one comparison.

The schema is the canonical cross-Simplicio contract pinned in
simplicio-runtime issue #69; this module must not introduce a repo-local
variation. Builders raise explicitly when a range cannot be made stable
(out-of-bounds, file missing, file is binary).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable

from .mapper import _language_for, _read_safe

MECHANICAL_EDIT_SCHEMA = "simplicio.mechanical-edit/v1"
MECHANICAL_EDIT_RESULT_SCHEMA = "simplicio.mechanical-edit-result/v1"
MAPPER_INDEX_SCHEMA = "simplicio.mapper-index/v1"

_NUL_PROBE_BYTES = 8192
# Files longer than this trigger compact mode: ranges still carry their hash
# anchors, but `must_contain` is omitted so the JSON envelope stays small.
COMPACT_LINE_THRESHOLD = 2000
_MUST_CONTAIN_PREFIX_CHARS = 120


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_bytes_sample(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(_NUL_PROBE_BYTES)
    except OSError:
        return b""


def is_binary(path: str) -> bool:
    """Return True when the file at `path` looks binary.

    A file with a NUL byte in its first 8 KiB, or that does not decode as
    UTF-8, is treated as binary. The mechanical edit contract refuses binary
    files because line-anchored edits do not apply to them.
    """
    sample = _read_bytes_sample(path)
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def snapshot_hash(text: str) -> str:
    """sha256 of the full text content (UTF-8)."""
    return _sha256_text(text)


def range_hash(text: str, start_line: int, end_line: int) -> str:
    """sha256 of the `start_line..end_line` slice (1-indexed, inclusive)."""
    if start_line < 1 or end_line < start_line:
        raise ValueError(f"invalid range {start_line}-{end_line}")
    lines = text.splitlines()
    if end_line > len(lines):
        raise ValueError(
            f"range {start_line}-{end_line} out of bounds ({len(lines)} lines)"
        )
    chunk = "\n".join(lines[start_line - 1 : end_line])
    return _sha256_text(chunk)


def _must_contain(text: str, start_line: int, end_line: int, compact: bool) -> list[str]:
    if compact:
        return []
    lines = text.splitlines()
    out: list[str] = []
    if 1 <= start_line <= len(lines):
        out.append(lines[start_line - 1].strip()[:_MUST_CONTAIN_PREFIX_CHARS])
    if start_line != end_line and 1 <= end_line <= len(lines):
        out.append(lines[end_line - 1].strip()[:_MUST_CONTAIN_PREFIX_CHARS])
    return [piece for piece in out if piece]


def _absolute(root: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(root, path)


def extract_file_entry(root: str, path: str, ranges: list[tuple[int, int]]) -> dict:
    """Build a single `files[]` entry for `path` and the given line ranges."""
    abs_path = _absolute(root, path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"file not found: {path}")
    if is_binary(abs_path):
        raise ValueError(f"binary file refused: {path}")
    text = _read_safe(abs_path)
    compact = len(text.splitlines()) > COMPACT_LINE_THRESHOLD
    selected = []
    for start, end in ranges:
        selected.append({
            "start_line": start,
            "end_line": end,
            "before_hash": range_hash(text, start, end),
            "must_contain": _must_contain(text, start, end, compact),
        })
    return {
        "path": path.replace(os.sep, "/"),
        "language": _language_for(abs_path),
        "snapshot_hash": snapshot_hash(text),
        "selected_ranges": selected,
    }


def build_context(
    root: str,
    selections: Iterable[tuple[str, int, int]],
) -> dict:
    """Build a `simplicio.mechanical-edit/v1` context envelope.

    `selections` is an iterable of `(path, start_line, end_line)` triples.
    Ranges on the same file are grouped and emitted in input order under
    that file's `selected_ranges`.
    """
    grouped: dict[str, list[tuple[int, int]]] = {}
    for path, start, end in selections:
        grouped.setdefault(path, []).append((start, end))
    files = []
    digest = hashlib.sha256()
    for path in sorted(grouped):
        entry = extract_file_entry(root, path, grouped[path])
        files.append(entry)
        digest.update(entry["snapshot_hash"].encode("utf-8"))
        for selected_range in entry["selected_ranges"]:
            digest.update(selected_range["before_hash"].encode("utf-8"))
    return {
        "schema": MECHANICAL_EDIT_SCHEMA,
        "context": {
            "mapper_schema": MAPPER_INDEX_SCHEMA,
            "context_hash": digest.hexdigest(),
            "files": files,
        },
    }


__all__ = [
    "COMPACT_LINE_THRESHOLD",
    "MAPPER_INDEX_SCHEMA",
    "MECHANICAL_EDIT_RESULT_SCHEMA",
    "MECHANICAL_EDIT_SCHEMA",
    "build_context",
    "extract_file_entry",
    "is_binary",
    "range_hash",
    "snapshot_hash",
]
