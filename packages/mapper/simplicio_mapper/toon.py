"""TOON (Token-Oriented Object Notation) encoder/decoder for LLM prompt payloads.

TOON is a compact, YAML-adjacent serialization of JSON-compatible values that
trades a small amount of parse complexity for a large reduction in token
count versus JSON — especially on uniform arrays of objects, which collapse
into a tabular block (one header row, one comma-separated data row per
element) instead of repeating every key for every element.

Reference: https://github.com/toon-format/toon

Rules implemented here (see ``TOON-CONTRACT.md`` / issues #144, #148 for the
full spec this mirrors):

- Objects render as YAML-style ``key: value`` lines with 2-space indentation
  per nesting level; nested non-empty objects render as ``key:`` followed by
  an indented block.
- Arrays of uniform objects (every element is a dict with the exact same set
  of keys, and every value is a scalar or a list of scalars — no nested
  dicts, no lists-of-non-scalars) render as a tabular block::

      key[N]{field1,field2}:
        v1,v2
        v3,v4

  A cell whose value is itself a list of scalars renders as a bracketed,
  comma-separated group (``[a,b,c]``) so it still fits one CSV-style row;
  see ``_format_row_cell``/``_parse_row_cell``.
- Arrays of scalars render as an inline list: ``key[N]: v1,v2,v3``.
- Empty arrays/objects, and arrays that are *not* uniform (differing keys,
  mixed dict/scalar elements, or a dict value nested inside an element)
  fall back to compact JSON for that value — this keeps encoding lossless
  without trying to force a tabular shape onto heterogeneous data. Every
  fallback is recorded as ``{"path": ..., "reason": ...}`` and can be
  retrieved via :func:`encode_toon_with_report` (see issue #148) instead of
  being silently swallowed.
- Scalars are unquoted unless quoting is required to keep them unambiguous
  (they contain a comma, colon, newline, leading/trailing whitespace, a
  bracket, or would otherwise be parsed as a number/bool/null/JSON literal).

``encode_toon``/``decode_toon`` are inverses: ``decode_toon(encode_toon(x))
== x`` for any JSON-compatible ``x`` (dict/list/str/int/float/bool/None).
``decode_toon`` never raises a bare ``IndexError``/``KeyError`` on malformed
or truncated input — every parse failure surfaces as ``ValueError`` (or a
subclass), per the TOON-CONTRACT decode error contract.
"""

from __future__ import annotations

import json
import re

__all__ = [
    "TOONDecodeError",
    "decode_toon",
    "encode_toon",
    "encode_toon_with_report",
]

_INDENT_UNIT = "  "
_INT_RE = re.compile(r"[-+]?\d+")
_ROOT_ARRAY_HEADER_RE = re.compile(r"^\[\d*\]")


class TOONDecodeError(ValueError):
    """Raised for any malformed/truncated TOON input.

    Always a ``ValueError`` subclass — decode never lets a bare
    ``IndexError``/``KeyError`` escape to the caller (issue #148).
    """


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode_toon(value: object) -> str:
    """Encode a JSON-compatible ``value`` as a TOON string.

    Fallback events (non-uniform arrays that could not use the tabular/inline
    shape) are computed but discarded; use :func:`encode_toon_with_report`
    to retrieve them.
    """
    text, _fallbacks = encode_toon_with_report(value)
    return text


def encode_toon_with_report(value: object) -> tuple[str, list[dict]]:
    """Encode ``value`` as TOON and also return the fallback report.

    Returns ``(text, toon_fallbacks)`` where ``toon_fallbacks`` is a list of
    ``{"path": <str>, "reason": <str>}`` dicts, one per array that could not
    take the tabular/inline shape and fell back to embedded compact JSON.
    ``path`` uses ``$`` for the root and dotted/bracket segments below it
    (e.g. ``$.files``, ``$.meta.items``). Empty when every array in ``value``
    encoded losslessly via the tabular or inline-scalar shape.
    """
    fallbacks: list[dict] = []
    if isinstance(value, dict):
        if not value:
            return "{}", fallbacks
        lines = _encode_object_lines(value, 0, "$", fallbacks)
        return "\n".join(lines), fallbacks
    if isinstance(value, list):
        lines = _encode_root_array(value, "$", fallbacks)
        return "\n".join(lines), fallbacks
    return _format_scalar(value), fallbacks


def _child_path(path: str, key: object) -> str:
    key_str = key if isinstance(key, str) else str(key)
    return f"{path}.{key_str}" if path else key_str


def _encode_object_lines(obj: dict, indent: int, path: str, fallbacks: list[dict]) -> list[str]:
    lines: list[str] = []
    for key, val in obj.items():
        lines.extend(_encode_entry(key, val, indent, _child_path(path, key), fallbacks))
    return lines


def _encode_entry(key: object, val: object, indent: int, path: str, fallbacks: list[dict]) -> list[str]:
    prefix = _INDENT_UNIT * indent
    key_str = _format_key(key)
    if isinstance(val, dict):
        if not val:
            return [f"{prefix}{key_str}: {{}}"]
        return [f"{prefix}{key_str}:", *_encode_object_lines(val, indent + 1, path, fallbacks)]
    if isinstance(val, list):
        return _encode_array_entry(prefix, key_str, val, indent, path, fallbacks)
    return [f"{prefix}{key_str}: {_format_scalar(val)}"]


def _encode_array_entry(
    prefix: str, key_str: str, arr: list, indent: int, path: str, fallbacks: list[dict]
) -> list[str]:
    if not arr:
        return [f"{prefix}{key_str}: []"]
    if _is_uniform_object_array(arr):
        fields = list(arr[0].keys())
        header = f"{prefix}{key_str}[{len(arr)}]{{{','.join(_format_key(f) for f in fields)}}}:"
        row_prefix = _INDENT_UNIT * (indent + 1)
        rows = [row_prefix + _encode_row(item, fields) for item in arr]
        return [header, *rows]
    if _is_scalar_array(arr):
        row = ",".join(_format_scalar(v) for v in arr)
        return [f"{prefix}{key_str}[{len(arr)}]: {row}"]
    # Non-uniform array (differing keys, mixed dict/scalar elements, or a
    # nested dict/list-of-non-scalars inside an element): fall back to
    # compact JSON rather than force a lossy tabular shape. Recorded so the
    # caller can see how much of the payload actually took the token-lean
    # path (issue #148).
    fallbacks.append({"path": path, "reason": _classify_fallback(arr)})
    return [f"{prefix}{key_str}: {json.dumps(arr, separators=(',', ':'))}"]


def _encode_root_array(arr: list, path: str, fallbacks: list[dict]) -> list[str]:
    if not arr:
        return ["[]"]
    if _is_uniform_object_array(arr):
        fields = list(arr[0].keys())
        header = f"[{len(arr)}]{{{','.join(_format_key(f) for f in fields)}}}:"
        rows = [_INDENT_UNIT + _encode_row(item, fields) for item in arr]
        return [header, *rows]
    if _is_scalar_array(arr):
        row = ",".join(_format_scalar(v) for v in arr)
        return [f"[{len(arr)}]: {row}"]
    fallbacks.append({"path": path, "reason": _classify_fallback(arr)})
    return [json.dumps(arr, separators=(",", ":"))]


def _classify_fallback(arr: list) -> str:
    """Best-effort reason string for why ``arr`` could not go tabular."""
    if not all(isinstance(item, dict) for item in arr):
        return "mixed_types"
    first_keyset = set(arr[0].keys())
    for item in arr:
        if set(item.keys()) != first_keyset:
            return "differing_keys"
    return "nested_containers"


def _encode_row(item: dict, fields: list) -> str:
    return ",".join(_format_row_cell(item[field]) for field in fields)


def _format_row_cell(value: object) -> str:
    if isinstance(value, list):
        return "[" + ",".join(_format_scalar(v) for v in value) + "]"
    return _format_scalar(value)


def _is_uniform_object_array(arr: list) -> bool:
    if not arr or not all(isinstance(item, dict) for item in arr):
        return False
    first_keys = list(arr[0].keys())
    first_keyset = set(first_keys)
    for item in arr:
        if set(item.keys()) != first_keyset:
            return False
        for v in item.values():
            if isinstance(v, dict):
                return False
            if isinstance(v, list) and not _is_scalar_list(v):
                return False
    return True


def _is_scalar_list(values: list) -> bool:
    return all(not isinstance(v, (dict, list)) for v in values)


def _is_scalar_array(arr: list) -> bool:
    return all(not isinstance(v, (dict, list)) for v in arr)


def _format_key(key: object) -> str:
    key_str = key if isinstance(key, str) else str(key)
    return _quote(key_str) if _needs_quotes(key_str) else key_str


def _format_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return _quote(value) if _needs_quotes(value) else value
    # Anything else (should not happen for JSON-compatible input) falls back
    # to its compact JSON representation so encoding never raises.
    return json.dumps(value, separators=(",", ":"))


def _quote(text: str) -> str:
    return json.dumps(text)


def _needs_quotes(text: str) -> bool:
    if text == "":
        return True
    if text != text.strip():
        return True
    if any(ch in text for ch in (",", ":", "\n", "{", "[", "]")):
        return True
    if text.startswith('"'):
        return True
    if text in ("true", "false", "null"):
        return True
    return _looks_like_number(text)


def _looks_like_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_toon(text: str) -> object:
    """Decode a TOON string produced by :func:`encode_toon` back to a value.

    Raises :class:`TOONDecodeError` (a ``ValueError``) on any malformed or
    truncated input — never a bare ``IndexError``/``KeyError`` (issue #148).
    """
    lines = text.split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return {}

    first_stripped = lines[0].strip()
    if _ROOT_ARRAY_HEADER_RE.match(first_stripped):
        return _decode_root_array(lines, first_stripped)
    if first_stripped.startswith("[") or first_stripped.startswith("{"):
        # Whole document is a compact-JSON fallback (non-uniform root array,
        # or an empty/fallback root object such as "{}").
        try:
            return json.loads(text)
        except ValueError as error:
            raise TOONDecodeError(f"Malformed TOON/JSON fallback document: {error}") from error
    if len(lines) == 1 and not _has_top_level_colon(lines[0]):
        return _parse_scalar_token(first_stripped)

    obj, _next_idx = _parse_object(lines, 0, 0)
    return obj


def _require_line(lines: list[str], idx: int, context: str) -> str:
    if idx >= len(lines):
        raise TOONDecodeError(f"Truncated TOON input: expected {context} at line {idx + 1}, found end of input")
    return lines[idx]


def _decode_root_array(lines: list[str], first_stripped: str) -> list:
    if first_stripped == "[]":
        return []
    if "]" not in first_stripped:
        raise TOONDecodeError(f"Malformed TOON array header: {first_stripped!r}")
    close = first_stripped.index("]")
    try:
        count = int(first_stripped[1:close])
    except ValueError as error:
        raise TOONDecodeError(f"Malformed TOON array header: {first_stripped!r}") from error
    pos = close + 1
    fields = None
    if pos < len(first_stripped) and first_stripped[pos] == "{":
        if "}" not in first_stripped[pos:]:
            raise TOONDecodeError(f"Malformed TOON array header (unterminated field list): {first_stripped!r}")
        end = first_stripped.index("}", pos)
        fields_str = first_stripped[pos + 1 : end]
        fields = [] if fields_str == "" else _split_top_level(fields_str)
        pos = end + 1
    if pos >= len(first_stripped) or first_stripped[pos] != ":":
        raise TOONDecodeError(f"Malformed TOON array header: {first_stripped!r}")
    rest = first_stripped[pos + 1 :].strip()

    if fields is not None:
        rows = []
        for offset in range(count):
            row_line = _require_line(lines, 1 + offset, f"row {offset + 1}/{count} of root array")
            row_content = row_line.strip()
            values = _split_top_level(row_content)
            rows.append(_zip_row(fields, values, first_stripped))
        return rows
    if rest == "":
        return []
    return [_parse_scalar_token(v) for v in _split_top_level(rest)]


def _zip_row(fields: list[str], values: list[str], context: str) -> dict:
    if len(values) != len(fields):
        raise TOONDecodeError(
            f"TOON row/field count mismatch under {context!r}: expected {len(fields)} field(s), got {len(values)}"
        )
    return {field: _parse_row_cell(v) for field, v in zip(fields, values, strict=True)}


def _parse_object(lines: list[str], idx: int, indent: int) -> tuple[dict, int]:
    result: dict = {}
    prefix_len = len(_INDENT_UNIT) * indent
    while idx < len(lines):
        line = lines[idx]
        if line.strip() == "":
            idx += 1
            continue
        if _indent_of(line) < prefix_len:
            break
        content = line[prefix_len:]
        key, count, fields, rest = _parse_entry_header(content)
        rest_stripped = rest.strip()

        if count is not None and fields is not None:
            rows = []
            idx += 1
            row_prefix_len = len(_INDENT_UNIT) * (indent + 1)
            for offset in range(count):
                row_line = _require_line(lines, idx, f"row {offset + 1}/{count} of {key!r}")
                if len(row_line) < row_prefix_len:
                    raise TOONDecodeError(f"Truncated/under-indented TOON row for {key!r} at line {idx + 1}")
                row_content = row_line[row_prefix_len:].strip()
                values = _split_top_level(row_content)
                rows.append(_zip_row(fields, values, key))
                idx += 1
            result[key] = rows
            continue

        if count is not None:
            result[key] = [] if rest_stripped == "" else [
                _parse_scalar_token(v) for v in _split_top_level(rest_stripped)
            ]
            idx += 1
            continue

        if rest_stripped == "":
            idx += 1
            child, idx = _parse_object(lines, idx, indent + 1)
            result[key] = child
            continue

        if rest_stripped[0] in "{[":
            try:
                result[key] = json.loads(rest_stripped)
            except ValueError as error:
                raise TOONDecodeError(f"Malformed TOON/JSON fallback value for {key!r}: {error}") from error
            idx += 1
            continue

        result[key] = _parse_scalar_token(rest_stripped)
        idx += 1
    return result, idx


def _parse_entry_header(content: str) -> tuple[str, int | None, list | None, str]:
    n = len(content)
    if content.startswith('"'):
        j = 1
        while j < n and content[j] != '"':
            if content[j] == "\\":
                j += 1
            j += 1
        if j >= n:
            raise TOONDecodeError(f"Unterminated quoted key: {content!r}")
        try:
            key = json.loads(content[: j + 1])
        except ValueError as error:
            raise TOONDecodeError(f"Malformed quoted key: {content!r}") from error
        pos = j + 1
    else:
        j = 0
        while j < n and content[j] not in "[:":
            j += 1
        key = content[:j]
        pos = j

    count = None
    fields = None
    if pos < n and content[pos] == "[":
        if "]" not in content[pos:]:
            raise TOONDecodeError(f"Malformed TOON entry (unterminated count): {content!r}")
        close = content.index("]", pos)
        try:
            count = int(content[pos + 1 : close])
        except ValueError as error:
            raise TOONDecodeError(f"Malformed TOON entry count: {content!r}") from error
        pos = close + 1
    if pos < n and content[pos] == "{":
        if "}" not in content[pos:]:
            raise TOONDecodeError(f"Malformed TOON entry (unterminated field list): {content!r}")
        end = content.index("}", pos)
        fields_str = content[pos + 1 : end]
        fields = [] if fields_str == "" else _split_top_level(fields_str)
        pos = end + 1

    if pos >= n or content[pos] != ":":
        raise TOONDecodeError(f"Malformed TOON entry: {content!r}")
    rest = content[pos + 1 :]
    return key, count, fields, rest


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _has_top_level_colon(line: str) -> bool:
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quotes:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            i += 1
            continue
        if ch == ":":
            return True
        i += 1
    return False


def _split_top_level(text: str, sep: str = ",") -> list[str]:
    """Split ``text`` on top-level ``sep`` occurrences.

    Respects quoted strings (``"..."``, sep-chars inside are not split
    points) and bracketed groups (``[...]``, used to encode a list-of-
    scalars cell inline in a tabular row — see ``_format_row_cell``); a
    ``sep`` inside either does not count as a split point.
    """
    parts: list[str] = []
    current: list[str] = []
    in_quotes = False
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            current.append(ch)
            if ch == "\\" and i + 1 < n:
                current.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_quotes = False
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            current.append(ch)
            i += 1
            continue
        if ch == "[":
            depth += 1
            current.append(ch)
            i += 1
            continue
        if ch == "]":
            depth = max(0, depth - 1)
            current.append(ch)
            i += 1
            continue
        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def _parse_row_cell(token: str) -> object:
    """Parse one tabular-row cell: either a plain scalar or a ``[a,b]`` list.

    A bracketed cell is unambiguous here: any scalar string that happened to
    *contain* ``[``/``]`` would have been quoted by ``_needs_quotes`` at
    encode time, so an unquoted leading ``[`` only ever comes from
    ``_format_row_cell``'s list-of-scalars encoding (issue #148).
    """
    token = token.strip()
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1]
        if inner == "":
            return []
        return [_parse_scalar_token(v) for v in _split_top_level(inner)]
    return _parse_scalar_token(token)


def _parse_scalar_token(token: str) -> object:
    token = token.strip()
    if token.startswith('"'):
        try:
            return json.loads(token)
        except ValueError as error:
            raise TOONDecodeError(f"Malformed quoted TOON scalar: {token!r}") from error
    if token == "null":  # noqa: S105 - TOON literal, not a credential
        return None
    if token == "true":  # noqa: S105 - TOON literal, not a credential
        return True
    if token == "false":  # noqa: S105 - TOON literal, not a credential
        return False
    if _INT_RE.fullmatch(token):
        return int(token)
    try:
        return float(token)
    except ValueError:
        return token
