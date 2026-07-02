"""toon_codec.py — TOON (Token-Oriented Object Notation) encoder/decoder.

TOON losslessly represents JSON in a more token-efficient text form for LLM
prompts: https://github.com/toon-format/toon. Uniform arrays of objects (the
common shape for precedent lists, ranked file entries, skill matches, ...)
collapse into a compact tabular block instead of repeating each key per
element, which is the ~40% token win the format is built for.

This module is a self-contained, dependency-free implementation (no PyPI
package — see repo CLAUDE.md "no new dependency without confirmation").

Public API:
    to_toon(value) -> str      # encode any JSON-compatible Python value
    from_toon(text) -> value   # decode TOON text back into the same value

Encoding rules (see YOOL_TUPLE_HAMT.md-adjacent TOON spec, summarized):
  - Objects: YAML-style 2-space indentation, "key:" then nested "k: v" lines.
  - Arrays of uniform objects (every element a dict with the exact same set
    of scalar-only fields) -> tabular block:
        key[N]{field1,field2}:
          v1,v2
          v3,v4
  - Arrays of scalars -> inline: key[N]: v1,v2,v3
  - Empty arrays, non-uniform arrays (differing key sets, mixed types, or
    elements carrying nested list/dict values) -> fall back to compact JSON
    for that value (key: <compact-json>), logged at DEBUG via `logger`.
  - Scalars: numbers/bools/null unquoted; strings quoted (JSON string
    literal) only when they contain a comma, colon, newline, leading/
    trailing whitespace, structural characters (", {, }, [, ]) or would
    otherwise parse as a number/bool/null.

Both object and array values are supported at the root, matching the spec.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["to_toon", "from_toon", "TOONDecodeError"]


class TOONDecodeError(ValueError):
    """Raised when `from_toon` is given text that isn't valid TOON."""


# --------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------

_STRUCTURAL_PREFIXES = ('"', "{", "}", "[", "]")


def _looks_numeric_bool_null(s: str) -> bool:
    if s in ("true", "false", "null"):
        return True
    if re.fullmatch(r"-?\d+", s):
        return True
    if re.fullmatch(r"-?\d+\.\d+([eE][+-]?\d+)?|-?\d+[eE][+-]?\d+", s):
        return True
    return False


def _needs_quoting(s: str) -> bool:
    if s == "":
        return True
    if s != s.strip():
        return True
    if any(ch in s for ch in (",", ":", "\n", "\r")):
        return True
    if s.startswith(_STRUCTURAL_PREFIXES):
        return True
    if _looks_numeric_bool_null(s):
        return True
    return False


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        if _needs_quoting(value):
            return json.dumps(value, ensure_ascii=False)
        return value
    raise TypeError(f"unsupported TOON scalar type: {type(value)!r}")


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _uniform_object_fields(arr: list) -> "list[str] | None":
    """Return the stable field order if `arr` is a uniform array of
    scalar-only-valued dicts (all sharing the exact same key set), else
    None."""
    if not arr or not all(isinstance(el, dict) for el in arr):
        return None
    fields = list(arr[0].keys())
    field_set = set(fields)
    for el in arr:
        if set(el.keys()) != field_set:
            return None
        if any(isinstance(v, (dict, list)) for v in el.values()):
            return None
    return fields


def _encode_array_body(key: str, arr: list, level: int, out: list, *, root: bool) -> None:
    prefix = "  " * level
    n = len(arr)
    if n == 0:
        out.append(f"{prefix}{key}: []" if not root else "[]")
        return

    fields = _uniform_object_fields(arr)
    if fields is not None:
        header = f"[{n}]{{{','.join(fields)}}}:" if root else f"{key}[{n}]{{{','.join(fields)}}}:"
        out.append(f"{prefix}{header}")
        row_prefix = "  " * (level + 1)
        for el in arr:
            row = ",".join(_format_scalar(el[f]) for f in fields)
            out.append(f"{row_prefix}{row}")
        return

    if all(_is_scalar(el) for el in arr):
        values = ",".join(_format_scalar(el) for el in arr)
        header = f"[{n}]: {values}" if root else f"{key}[{n}]: {values}"
        out.append(f"{prefix}{header}")
        return

    # Non-uniform (mixed element types, differing key sets, or elements with
    # nested list/dict values) — fall back to compact JSON, per spec.
    logger.debug(
        "toon_codec: non-uniform array at key=%r (len=%d) — falling back to compact JSON",
        key,
        n,
    )
    encoded = _compact_json(arr)
    out.append(f"{prefix}{key}: {encoded}" if not root else f"{prefix}{encoded}")


def _encode_pair(key: str, value: Any, level: int, out: list) -> None:
    prefix = "  " * level
    if isinstance(value, dict):
        if not value:
            out.append(f"{prefix}{key}: {{}}")
            return
        out.append(f"{prefix}{key}:")
        for sub_key, sub_value in value.items():
            _encode_pair(str(sub_key), sub_value, level + 1, out)
        return
    if isinstance(value, (list, tuple)):
        _encode_array_body(key, list(value), level, out, root=False)
        return
    out.append(f"{prefix}{key}: {_format_scalar(value)}")


def to_toon(value: Any) -> str:
    """Encode a JSON-compatible Python value (dict/list/scalar) as TOON."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: list = []
        for key, val in value.items():
            _encode_pair(str(key), val, 0, lines)
        return "\n".join(lines)
    if isinstance(value, (list, tuple)):
        arr = list(value)
        if not arr:
            return "[]"
        lines = []
        _encode_array_body("", arr, 0, lines, root=True)
        return "\n".join(lines)
    return _format_scalar(value)


# --------------------------------------------------------------------------
# Decoding
# --------------------------------------------------------------------------

_ARRAY_OBJ_RE = re.compile(r"^(?P<key>[^:\[\]]*)\[(?P<n>\d+)\]\{(?P<fields>[^}]*)\}:$")
_ARRAY_SCALAR_RE = re.compile(r"^(?P<key>[^:\[\]]*)\[(?P<n>\d+)\]:(?: (?P<rest>.*))?$")
_KV_RE = re.compile(r"^(?P<key>[^:\[\]]+):(?: (?P<rest>.*))?$")


def _tokenize(text: str) -> "list[tuple[int, str]]":
    raw_lines = text.split("\n")
    # Drop a single trailing blank line produced by a trailing "\n" in the
    # input; interior blank lines are kept (they matter for zero-field rows).
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]
    tokens = []
    for line in raw_lines:
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        level = indent // 2
        tokens.append((level, stripped))
    return tokens


def _split_row(s: str) -> "list[str]":
    if s == "":
        return []
    parts: list = []
    cur: list = []
    in_quotes = False
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if in_quotes:
            cur.append(ch)
            if ch == "\\" and i + 1 < n:
                cur.append(s[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            cur.append(ch)
            i += 1
            continue
        if ch == ",":
            parts.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _parse_scalar(token: str) -> Any:
    if token.startswith('"'):
        try:
            return json.loads(token)
        except ValueError as exc:  # pragma: no cover - malformed input
            raise TOONDecodeError(f"invalid quoted TOON scalar: {token!r}") from exc
    if token == "null":
        return None
    if token == "true":
        return True
    if token == "false":
        return False
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+([eE][+-]?\d+)?|-?\d+[eE][+-]?\d+", token):
        return float(token)
    return token


def _parse_scalar_or_json(rest: str) -> Any:
    if rest.startswith("{") or rest.startswith("["):
        try:
            return json.loads(rest)
        except ValueError as exc:
            raise TOONDecodeError(f"invalid TOON JSON fallback value: {rest!r}") from exc
    return _parse_scalar(rest)


class _Cursor:
    def __init__(self, lines: "list[tuple[int, str]]") -> None:
        self._lines = lines
        self._i = 0

    def peek(self) -> "tuple[int, str] | None":
        if self._i >= len(self._lines):
            return None
        return self._lines[self._i]

    def next(self) -> "tuple[int, str]":
        if self._i >= len(self._lines):
            raise TOONDecodeError("unexpected end of TOON input")
        line = self._lines[self._i]
        self._i += 1
        return line


def _read_array_obj_rows(pos: _Cursor, fields: "list[str]", n: int) -> "list[dict]":
    rows = []
    for _ in range(n):
        _level, content = pos.next()
        values = _split_row(content)
        if len(values) != len(fields):
            raise TOONDecodeError(
                f"TOON row has {len(values)} values but header declares {len(fields)} fields"
            )
        rows.append({field: _parse_scalar(v) for field, v in zip(fields, values)})
    return rows


def _parse_object(pos: _Cursor, level: int) -> dict:
    obj: dict = {}
    while True:
        line = pos.peek()
        if line is None or line[0] != level:
            break
        _lvl, content = pos.next()

        m = _ARRAY_OBJ_RE.match(content)
        if m:
            key = m.group("key")
            n = int(m.group("n"))
            fields = m.group("fields").split(",") if m.group("fields") else []
            obj[key] = _read_array_obj_rows(pos, fields, n)
            continue

        m = _ARRAY_SCALAR_RE.match(content)
        if m:
            key = m.group("key")
            n = int(m.group("n"))
            rest = m.group("rest") or ""
            values = _split_row(rest) if n else []
            obj[key] = [_parse_scalar(v) for v in values]
            continue

        m = _KV_RE.match(content)
        if m:
            key = m.group("key")
            rest = m.group("rest")
            if rest is None:
                nxt = pos.peek()
                if nxt is not None and nxt[0] == level + 1:
                    obj[key] = _parse_object(pos, level + 1)
                else:
                    obj[key] = {}
            else:
                obj[key] = _parse_scalar_or_json(rest)
            continue

        raise TOONDecodeError(f"cannot parse TOON line: {content!r}")
    return obj


def _parse_root_array(pos: _Cursor) -> list:
    _level, content = pos.next()
    m = _ARRAY_OBJ_RE.match(content)
    if m and m.group("key") == "":
        n = int(m.group("n"))
        fields = m.group("fields").split(",") if m.group("fields") else []
        return _read_array_obj_rows(pos, fields, n)
    m = _ARRAY_SCALAR_RE.match(content)
    if m and m.group("key") == "":
        n = int(m.group("n"))
        rest = m.group("rest") or ""
        values = _split_row(rest) if n else []
        return [_parse_scalar(v) for v in values]
    raise TOONDecodeError(f"expected a root array header, got: {content!r}")


def from_toon(text: str) -> Any:
    """Decode TOON text back into the Python value it represents.

    Inverse of `to_toon`: `from_toon(to_toon(x)) == x` for any JSON-
    compatible value `x`.
    """
    stripped = text.strip("\n")
    if stripped == "{}":
        return {}
    if stripped == "[]":
        return []

    lines = _tokenize(text)
    if not lines:
        return {}

    first_level, first_content = lines[0]
    m_obj = _ARRAY_OBJ_RE.match(first_content)
    m_scalar = _ARRAY_SCALAR_RE.match(first_content)
    m_kv = _KV_RE.match(first_content)

    if first_level == 0 and (
        (m_obj and m_obj.group("key") == "") or (m_scalar and m_scalar.group("key") == "")
    ):
        # A keyless "[N]..." header at the root means the root value itself
        # is an array (as opposed to an object whose one field happens to be
        # an array — that case has a non-empty key and is handled below).
        return _parse_root_array(_Cursor(lines))

    if first_level == 0 and (
        m_kv
        or (m_obj and m_obj.group("key") != "")
        or (m_scalar and m_scalar.group("key") != "")
    ):
        return _parse_object(_Cursor(lines), 0)

    if len(lines) == 1:
        # Neither an object/array header nor a "key: value" line — either a
        # bare scalar root (`to_toon(5)` -> "5") or a single-line compact
        # JSON fallback produced for a non-uniform root array/dict.
        return _parse_scalar_or_json(first_content)

    raise TOONDecodeError("cannot determine TOON root type")
