"""Validation of ``simplicio.agent-handoff/v1`` documents and the place they live (#1608).

This module only checks a document and computes a path. Writing, reading and the CLI belong to a later part.
The schema is the packaged copy of ``contracts/agent-handoff/v1/schema.json``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from .input_ceiling import estimate_tokens

MAX_HANDOFF_TOKENS = 6000
SCHEMA_PATH = Path(__file__).resolve().parent / "_contracts" / "agent-handoff" / "v1" / "schema.json"
_RUN_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


class HandoffError(ValueError):
    """A handoff document or location is not acceptable. ``reason_code`` names the rule."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__("%s: %s" % (reason_code, message))
        self.reason_code = reason_code


def _schema_error(doc: Any) -> str | None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    error = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema).iter_errors(doc))
    if error is None:
        return None
    return "%s at /%s" % (error.message, "/".join(str(p) for p in error.absolute_path))


def _bad_path(path: str) -> bool:
    """True unless ``path`` is a clean POSIX path relative to the repository and outside ``.simplicio/``."""
    if "\x00" in path or "\\" in path or path.startswith("/") or re.match(r"[A-Za-z]:", path):
        return True
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return True
    return parts[0].casefold() == ".simplicio"


def validate_handoff(doc: Any) -> None:
    """Raise ``HandoffError`` unless ``doc`` is a valid handoff. Checks run in this order: schema, paths, token total, size."""
    problem = _schema_error(doc)
    if problem:
        raise HandoffError("handoff_schema_invalid", problem)
    for entry in doc["done"]["files"]:
        if _bad_path(entry["path"]):
            raise HandoffError("handoff_path_invalid",
                               "%r must be relative to the repository, without '..', outside .simplicio/" % entry["path"])
    tokens = doc["tokens"]
    if tokens["basis"] == "MEASURED":
        total = tokens["input_tokens"] + tokens["cache_read_input_tokens"] + tokens["cache_creation_input_tokens"]
        if tokens["prompt_tokens"] != total:
            raise HandoffError("handoff_tokens_inconsistent",
                               "prompt_tokens %d is not input + cache read + cache creation = %d"
                               % (tokens["prompt_tokens"], total))
    size = estimate_tokens(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    if size > MAX_HANDOFF_TOKENS:
        raise HandoffError("handoff_too_large", "estimated %d tokens, limit %d" % (size, MAX_HANDOFF_TOKENS))


def handoff_path(root: str | Path, run_id: str, n: int) -> Path:
    """``<root>/.simplicio-loop/orchestrator/handoff/<run_id>/<n>.json``. Nothing is created."""
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id) or run_id in (".", ".."):
        raise HandoffError("handoff_run_id_invalid", "%r does not match [A-Za-z0-9._-]{1,128} or is a dot name" % (run_id,))
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise HandoffError("handoff_continuation_invalid", "%r is not an integer >= 1" % (n,))
    return Path(root) / ".simplicio-loop" / "orchestrator" / "handoff" / run_id / ("%d.json" % n)
