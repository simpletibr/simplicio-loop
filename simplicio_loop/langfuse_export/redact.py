"""Redaction applied to every string leaf before anything leaves the machine.

Two layers: the loop's own secret patterns (``telemetry.SENSITIVE_VALUE``, bearer and token-query
forms) and the exact secret values the exporter was given. Content keys (prompts, responses) are
replaced by a size and hash unless ``langfuse_capture_content`` is on.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..telemetry import SENSITIVE_VALUE

REDACTED = "[REDACTED]"
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_TOKEN_QUERY = re.compile(r"(?i)([?&](?:token|api[_-]?key|secret|password)=)[^&#\s]+")
SECRET_KEY = re.compile(
    r"(secret|token|password|passwd|authorization|auth|cookie|api[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)
CONTENT_KEY = re.compile(
    r"^(prompt|response|completion|input|output|content|text|message|messages|body)$"
)


def _scrub_str(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        text = text.replace(secret, REDACTED)
    text = SENSITIVE_VALUE.sub(REDACTED, text)
    text = _BEARER.sub("Bearer " + REDACTED, text)
    return _TOKEN_QUERY.sub(r"\1" + REDACTED, text)


def scrub(value: Any, secrets: Iterable[str] = ()) -> Any:
    """Recursively redact; dataclasses become plain dicts so every payload is JSON-shaped."""
    known = tuple(sorted({s for s in secrets if s}, key=len, reverse=True))
    return _scrub(value, known)


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY.search(str(key)) and isinstance(item, str):
                out[str(key)] = REDACTED
            else:
                out[str(key)] = _scrub(item, secrets)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, str):
        return _scrub_str(value, secrets)
    return value


def digest_of(value: Any) -> dict[str, Any]:
    """Size and hash that stand in for content when capture is off."""
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, default=str)
    )
    return {
        "bytes": len(text.encode("utf-8")),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def export_payload(payload: Mapping[str, Any], capture_content: bool) -> dict[str, Any]:
    """The dashboard payload as it may leave: content keys become digests unless capture is on."""
    if capture_content:
        return dict(payload)
    return {
        key: (digest_of(val) if CONTENT_KEY.match(str(key)) else val)
        for key, val in payload.items()
    }
