"""orjson-backed json helpers. Drop-in for the subset of `json` the project uses.

orjson is 2-3x faster than the stdlib json on encode and decode and emits
bytes, which is exactly what httpx wants in `content=...`. For callers that
expect a `str` (writing to a text file), `dumps_str` decodes once at the
edge.

Falls back to stdlib json automatically if orjson is not installed so the
import chain never breaks; a deployment that wants the speedup just installs
the optional dependency.
"""

from __future__ import annotations

from typing import Any

try:  # optional fast path
    import orjson as _oj

    _HAS_ORJSON = True
except ImportError:  # pragma: no cover - degrades gracefully
    import json as _json

    _HAS_ORJSON = False


def dumps(obj: Any, *, indent: bool = False) -> bytes:
    """Serialize to bytes. Pass `indent=True` to pretty-print (2 spaces)."""
    if _HAS_ORJSON:
        opt = _oj.OPT_INDENT_2 if indent else 0
        return _oj.dumps(obj, option=opt)
    return _json.dumps(obj, indent=2 if indent else None).encode("utf-8")


def dumps_str(obj: Any, *, indent: bool = False) -> str:
    """Serialize to str. Use this when writing to a text file."""
    return dumps(obj, indent=indent).decode("utf-8")


def loads(data: Any) -> Any:
    """Decode JSON from `bytes`, `bytearray`, `str`, or anything readable."""
    if hasattr(data, "read"):
        data = data.read()
    if _HAS_ORJSON:
        return _oj.loads(data)
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8")
    return _json.loads(data)
