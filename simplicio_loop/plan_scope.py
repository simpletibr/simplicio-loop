"""Closed model answers and the task scope (issue #1612).

Every answer a model gives the loop is parsed against a closed JSON Schema (``contracts/structured-output/v1``) and an
edit plan must stay inside the ``TaskScope`` of the task of that moment. The check is deterministic and is the only
validator: a provider ``response_format`` or a CLI flag narrows what the model emits, it never replaces this.

A violation is the text ``<code>:<detail>``. A rejected answer goes back to the planner once with the list; the second
rejection is ``needs_human`` with the cause. The scope grows only by the rules in ``_widening`` and each use is recorded
in ``CheckResult.widenings``; the model has no way to add to it (``TaskScope`` is frozen).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

from . import plan_paths

MAX_FILE_LINES = 9000
MAX_RETRIES = 1
MAX_REPORTED = 20
NEAR_LIMIT = 0.9  # a file at 90% of the line limit makes a new sibling module a forced split

_SOURCE_DIR = Path(__file__).resolve().parent.parent / "contracts" / "structured-output" / "v1"
_PACKAGED_DIR = Path(__file__).resolve().parent / "_contracts" / "structured-output" / "v1"
CONTRACT_DIR = _PACKAGED_DIR if (_PACKAGED_DIR / "plan.schema.json").is_file() else _SOURCE_DIR

RESPONSE_SCHEMAS: dict[str, dict[str, Any]] = {
    name: json.loads((CONTRACT_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))
    for name in ("plan", "verdict")
}
_VALIDATORS = {name: Draft202012Validator(schema) for name, schema in RESPONSE_SCHEMAS.items()}
_FENCE = re.compile(r"\A```(?:json)?[ \t]*\n(.*)\n```\Z", re.S)
_TEST_NAME = re.compile(r"^(?:test_(?P<a>.+)|(?P<b>.+)_test|(?P<c>.+)\.(?:test|spec))$")


@dataclass(frozen=True)
class TaskScope:
    """What this task may touch: exact files, directory prefixes (end with ``/``), its criteria and the line limit."""

    paths: frozenset[str]
    dirs: tuple[str, ...] = ()
    criteria: tuple[str, ...] = ()
    max_lines: int = MAX_FILE_LINES

    def contains(self, path: str) -> bool:
        return path in self.paths or any(path.startswith(d) for d in self.dirs)


@dataclass
class CheckResult:
    violations: list[str] = field(default_factory=list)
    operations: list[dict] = field(default_factory=list)
    widenings: list[dict[str, str]] = field(default_factory=list)
    prose_chars: int = 0

    @property
    def ok(self) -> bool:
        return not self.violations


def scope_from_tasks(tasks: Sequence[Mapping[str, Any]], *, named_paths: Iterable[str] = (),
                     criteria: Iterable[str] = (), max_lines: int = MAX_FILE_LINES) -> TaskScope:
    """Scope of these tasks: their target and context (the Mapper focus), the paths the issue names, the criteria."""
    paths: set[str] = set(named_paths)
    for task in tasks:
        for name in (task.get("target"), *(task.get("context") or [])):
            if name:
                paths.add(str(name))
    dirs = tuple(sorted(p for p in paths if p.endswith("/")))
    return TaskScope(frozenset(p for p in paths if not p.endswith("/")), dirs, tuple(criteria), max_lines)


def _unframe(text: str) -> tuple[str, int]:
    """(JSON text, prose chars): one enclosing code fence is framing; any other text around the object is prose."""
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    start = body.find("{")
    if start < 0:
        return body, 0
    try:
        _obj, end = json.JSONDecoder().raw_decode(body, start)
    except ValueError:
        return body, 0
    return body[start:end], len(body[:start].strip()) + len(body[end:].strip())


def _describe(error: Any) -> str:
    pointer = "/" + "/".join(str(p) for p in error.absolute_path) if error.absolute_path else ""
    kind = error.validator
    if kind == "additionalProperties":
        extra = sorted(set(error.instance) - set(error.schema.get("properties", {})))
        return ",".join(f"extra_field:{pointer}/{name}" for name in extra)
    if kind == "required":
        return f"missing_field:{pointer}/{error.message.split(chr(39))[1]}"
    return {
        "maxLength": f"too_long:{pointer}", "maxItems": f"too_long:{pointer}", "minItems": f"empty:{pointer}",
        "minLength": f"empty:{pointer}", "type": f"wrong_type:{pointer}", "enum": f"bad_value:{pointer}",
    }.get(kind, f"schema:{pointer}:{kind}")


def validate_response(text: str, kind: str) -> list[str]:
    """Violations of the closed ``kind`` schema, prose around the JSON included. Empty list = valid."""
    body, prose = _unframe(text)
    violations = [f"extra_prose:{prose}"] if prose else []
    try:
        payload = json.loads(body)
    except ValueError:
        return [*violations, "not_json:the answer is not one JSON object"]
    errors = sorted(_VALIDATORS[kind].iter_errors(payload), key=lambda e: ([str(p) for p in e.absolute_path], e.message))
    for error in errors:
        violations.extend(_describe(error).split(","))
    return violations


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _is_companion_test(path: str, scope: TaskScope) -> bool:
    p = PurePosixPath(path)
    m = _TEST_NAME.match(p.stem)
    if not m:
        return False
    stem = next(g for g in m.groups() if g)
    in_test_dir = any(part in {"tests", "test", "__tests__"} for part in p.parts[:-1])
    for known in scope.paths:
        k = PurePosixPath(known)
        if k.stem == stem and k.suffix == p.suffix and (in_test_dir or k.parent == p.parent):
            return True
    return False


def _widening(path: str, find: str, scope: TaskScope, root: Path) -> str | None:
    """The explicit rule that lets the plan touch ``path`` beyond the scope, or None. Never chosen by the model."""
    if _is_companion_test(path, scope):
        return "companion_test"
    parent = str(PurePosixPath(path).parent)
    if not find and not (root / path).exists():
        for known in scope.paths:
            file = root / known
            if str(PurePosixPath(known).parent) == parent and file.is_file():
                if _line_count(file.read_text(encoding="utf-8", errors="replace")) >= scope.max_lines * NEAR_LIMIT:
                    return "split_for_line_limit"
    return None


def _resulting_lines(op: Mapping[str, Any], root: Path) -> int:
    find, replace = op.get("find") or "", op["replace"]
    target = root / op["path"]
    if not find or not target.is_file():
        return _line_count(replace)
    return _line_count(target.read_text(encoding="utf-8", errors="replace").replace(find, replace, 1))


def check_response(text: str, scope: TaskScope, root: str | os.PathLike[str]) -> CheckResult:
    """Parse an edit plan strictly and hold every operation to the scope and to the line limit."""
    root = Path(root)
    body, prose = _unframe(text)
    result = CheckResult(violations=validate_response(text, "plan"), prose_chars=prose)
    try:
        payload = json.loads(body)
    except ValueError:
        return result
    if result.violations and any(v.split(":", 1)[0] not in {"extra_prose"} for v in result.violations):
        return result
    operations = payload.get("operations") or []
    for op in operations:
        path = op["path"]
        if reason := plan_paths.refusal(path, root):
            result.violations.append(f"out_of_scope:{path}")
            continue
        if not scope.contains(path):
            rule = _widening(path, op.get("find") or "", scope, root)
            if rule is None:
                result.violations.append(f"out_of_scope:{path}")
                continue
            result.widenings.append({"path": path, "rule": rule})
        lines = _resulting_lines(op, root)
        if lines > scope.max_lines:
            result.violations.append(f"lines_over_limit:{path}:{lines}")
    if result.ok:
        result.operations = operations
    return result


def next_action(rejections: int) -> str:
    """``retry`` while the planner has a retry left, then ``needs_human``. ``rejections`` counts this one."""
    return "retry" if rejections <= MAX_RETRIES else "needs_human"


def retry_message(violations: Sequence[str]) -> str:
    """The text that goes back to the planner: the violations, in order, bounded, nothing else."""
    shown = list(violations[:MAX_REPORTED])
    more = len(violations) - len(shown)
    lines = ["The answer was rejected. Reply with one JSON object only, inside the task scope:", *shown]
    if more > 0:
        lines.append(f"(+{more} more)")
    return "\n".join(lines)


def counters(violations: Iterable[str]) -> dict[str, int]:
    """MEASURED rejection counts by kind (counted from the violations, never estimated)."""
    out = {"out_of_scope": 0, "extra_field": 0, "extra_prose": 0, "other": 0}
    for violation in violations:
        code = violation.split(":", 1)[0]
        out[code if code in out else "other"] += 1
    return out
