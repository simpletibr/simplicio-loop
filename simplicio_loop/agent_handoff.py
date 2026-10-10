"""Validation and secret redaction of ``simplicio.agent-handoff/v1`` documents, and the place they live (#1608).

This module checks a document, masks secrets in its free text and computes a path. It does no file I/O: writing and
reading are in ``handoff_cli``. The schema is the packaged copy of ``contracts/agent-handoff/v1/schema.json``.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from .dashboard.runs import redact_command
from .input_ceiling import estimate_tokens

MAX_HANDOFF_TOKENS = 6000
SCHEMA_PATH = Path(__file__).resolve().parent / "_contracts" / "agent-handoff" / "v1" / "schema.json"
_RUN_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z")


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
    if "\x00" in path or "\\" in path or re.match(r"[A-Za-z]:", path):
        return True
    parts = path.split("/")  # an absolute path or a double slash gives an empty part
    if any(part in ("", ".", "..") for part in parts):
        return True
    return parts[0].casefold() == ".simplicio"


def validate_handoff(doc: Any) -> None:
    """Raise ``HandoffError`` unless ``doc`` is a valid handoff. Checks run in this order: schema, paths, token total, size."""
    problem = _schema_error(doc)
    if problem:
        raise HandoffError("handoff_schema_invalid", problem)
    # `$` in a JSON Schema pattern also matches before a trailing newline; these fields must match whole.
    for value, rule in ((doc["run_id"], _RUN_ID), (doc["created_at"], _TIMESTAMP)):
        if not rule.fullmatch(value) or value in (".", ".."):
            raise HandoffError("handoff_schema_invalid", "%r does not match its pattern" % value)
    for entry in doc["done"]["files"]:
        if not _SHA256.fullmatch(entry["sha256"]):
            raise HandoffError("handoff_schema_invalid", "sha256 %r does not match its pattern" % entry["sha256"])
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


def _mask(holder: Any, key: Any, pointer: str, changed: list[str]) -> None:
    value = holder[key]
    if isinstance(value, str):
        masked = redact_command(value)
        if masked != value:
            holder[key] = masked
            changed.append(pointer)


def redact_handoff(doc: Any) -> tuple[dict, list[str]]:
    """A deep copy of ``doc`` with secrets masked in its free text, and the JSON pointers that changed.

    Free text is ``objective``, ``acceptance_criteria``, the ``command`` and ``summary`` of ``done.commands``,
    ``next_steps`` and ``open_questions``, in that order. Identifiers, hashes, paths, token counts and the lease are never
    touched. A field of the wrong shape is left alone: ``validate_handoff`` rejects it. Run this before
    ``validate_handoff``, because a mask can be longer than the text it replaces.
    """
    if not isinstance(doc, dict):
        raise HandoffError("handoff_schema_invalid", "a handoff is a JSON object, got %s" % type(doc).__name__)
    clean = copy.deepcopy(doc)
    changed: list[str] = []
    if "objective" in clean:
        _mask(clean, "objective", "/objective", changed)
    if isinstance(clean.get("acceptance_criteria"), list):
        for i in range(len(clean["acceptance_criteria"])):
            _mask(clean["acceptance_criteria"], i, "/acceptance_criteria/%d" % i, changed)
    done = clean.get("done")
    commands = done.get("commands") if isinstance(done, dict) else None
    for i, entry in enumerate(commands if isinstance(commands, list) else ()):
        if isinstance(entry, dict):
            for name in ("command", "summary"):
                if name in entry:
                    _mask(entry, name, "/done/commands/%d/%s" % (i, name), changed)
    for field in ("next_steps", "open_questions"):
        if isinstance(clean.get(field), list):
            for i in range(len(clean[field])):
                _mask(clean[field], i, "/%s/%d" % (field, i), changed)
    return clean, changed
