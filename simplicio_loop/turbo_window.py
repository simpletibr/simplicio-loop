"""The file text of a turbo plan request: windows around what the task names, not the start of the file (#1643).

A file that fits its per-file limit stays one string (exactly as before). A bigger file becomes an object::

    {"total_lines": N, "total_chars": C, "windows": [{"start": L1, "end": L2, "text": "..."}],
     "omitted": [{"start": L1, "end": L2}], "more": "how to ask for other lines"}

``text`` is the exact text of lines L1..L2 (line endings kept, no numbering, no marker), so a ``find`` copied from it
matches the file. The windows come from anchors in the task text: ``path:LINE`` / ``path:L1-L2``, and identifiers that
exist in the file as whole words (a definition first). A Python ``def``/``class`` window covers its whole body. Windows
the caller asked for (``turbo --window path:START-END``, or ``need`` in a plan) are shown first and exactly. The files
object stays under ``BUDGET_PERCENT`` of the input-token ceiling of ``input_ceiling`` (#1608).

Known limit: the Mapper map has no line numbers (path, roles, imports, exports), so Mapper exports are not anchors; the
task text and ``focus_paths`` choose the files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import plan_paths
from .input_ceiling import estimate_tokens, resolve_ceiling

FILE_CHARS_MAX = 16_000  # per-file ceiling, before the fair share of the total budget
MIN_FILE_CHARS = 800
BUDGET_PERCENT = 40  # of the input-token ceiling, for the whole files object
CONTEXT_LINES = 8
HEADER_LINES = 12
MAX_ANCHORS = 8
MAX_OCCURRENCES = 3
BODY_CAP_LINES = 150
MAX_NEED = 8
MORE = 'other lines: plan {"operations":[],"need":[{"path":P,"start":N,"end":M}]}'

_LINE = re.compile(r"[^\n]*\n|[^\n]+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PY_DEF = re.compile(r"^(\s*)(?:async\s+def|def|class)\s")
_SPEC = re.compile(r"(.+):(\d+)(?:-(\d+))?")
_SPECIFIC = re.compile(r"_|\d|[a-z][A-Z]|^[A-Z]{4,}$")
_HEADER_PRIORITY = 10_000


class TooManyFilesError(ValueError):
    """The files of the request do not fit the budget even without any text."""

    reason_code = "turbo_files_over_budget"


def parse_window_spec(spec: str) -> dict[str, Any]:
    """``path:START-END`` (or ``path:LINE``) as ``{"path", "start", "end"}``; a bad one raises ValueError."""
    match = _SPEC.fullmatch(spec.strip())
    if not match:
        raise ValueError(f"--window needs path:START-END, got {spec!r}")
    start = int(match.group(2))
    return _window(match.group(1), start, int(match.group(3) or start))


def _window(path: Any, start: Any, end: Any) -> dict[str, Any]:
    if not isinstance(path, str) or not path.strip() or isinstance(start, bool) or isinstance(end, bool) \
            or not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end:
        raise ValueError(f"a window needs a path and 1 <= start <= end, got {path!r} {start!r} {end!r}")
    if reason := plan_paths.refusal(path):
        raise ValueError(reason)
    return {"path": path, "start": start, "end": end}


def parse_need(value: Any) -> list[dict[str, Any]]:
    """The ``need`` of a plan: a list of ``{"path", "start", "end"}`` (at most MAX_NEED); None is no need."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_NEED or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"need is a list of at most {MAX_NEED} objects with path, start and end")
    return [_window(item.get("path"), item.get("start"), item.get("end")) for item in value]


def truncated(files: Mapping[str, Any]) -> list[str]:
    """The files of a request that have lines the planner did not get."""
    return [name for name, entry in files.items() if isinstance(entry, dict) and entry.get("omitted")]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _def_range(lines: list[str], at: int) -> tuple[int, int]:
    """First and last line (1-based) of the Python def/class on line ``at``: decorators to the end of its indented block."""
    indent, first, last = _indent(lines[at - 1]), at, at
    while first > 1 and lines[first - 2].lstrip().startswith("@") and _indent(lines[first - 2]) == indent:
        first -= 1
    for number in range(at + 1, len(lines) + 1):
        text = lines[number - 1]
        if not text.strip():
            continue
        if _indent(text) > indent or text.lstrip()[0] in ")]}":
            last = number
        else:
            break
    return first, last


def _around(lines: list[str], at: int, end: int | None = None) -> tuple[int, int]:
    """The interval of one anchor: the def body (when short) or the line(s), with CONTEXT_LINES around."""
    first, last = (at, end or at)
    if end is None and _PY_DEF.match(lines[at - 1]):
        body = _def_range(lines, at)
        first, last = body if body[1] - body[0] < BODY_CAP_LINES else (at, at)
    return max(1, first - CONTEXT_LINES), min(len(lines), last + CONTEXT_LINES)


def _definition(name: str, specific: bool) -> re.Pattern[str]:
    word = re.escape(name)
    keyword = rf"^\s*(?:(?:export|public|private|static|async|pub)\s+)*(?:def|class|function|const|let|var|fn|func|interface|type|enum|struct)\s+{word}\b"
    return re.compile(keyword + (rf"|^\s*{word}\s*(?::[^=\n]+)?=(?!=)" if specific else ""))


def _anchors(name: str, lines: list[str], texts: Sequence[str]) -> list[tuple[int, int, int, int]]:
    """Intervals (priority, focus, start, end) for one file from the task texts. Lower priority is shown first."""
    found: list[tuple[int, int, int, int]] = []
    for text in texts:
        for ref in re.finditer(re.escape(name) + r":(\d+)(?:-(\d+))?", text):
            first = int(ref.group(1))
            if 1 <= first <= len(lines):
                last = min(len(lines), int(ref.group(2) or first))
                found.append((0, first, *_around(lines, first, last if last > first else None)))
    stripped = " ".join(texts)
    for blank in {name, name.rsplit("/", 1)[-1]}:  # the path itself is not an identifier
        stripped = stripped.replace(blank, " ")
    seen: dict[str, None] = {}
    for token in _IDENT.findall(stripped):
        seen.setdefault(token)
    for order, token in enumerate(seen):
        specific = bool(_SPECIFIC.search(token))
        word, definition = re.compile(rf"\b{re.escape(token)}\b"), _definition(token, specific)
        hits = [number for number, line in enumerate(lines, start=1) if word.search(line)]
        defs = [number for number in hits if definition.match(lines[number - 1])]
        picked = defs[:MAX_OCCURRENCES] or (hits[:MAX_OCCURRENCES] if specific else [])
        found += [(1 + order if defs else 100 + order, number, *_around(lines, number)) for number in picked]
    found.sort(key=lambda item: item[0])
    return found[:MAX_ANCHORS]


def _merge(intervals: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Overlapping, adjacent or one-line-apart intervals become one; it keeps the best priority and its focus."""
    merged: list[tuple[int, int, int, int]] = []
    for item in sorted(intervals, key=lambda item: (item[2], item[3])):
        if merged and item[2] <= merged[-1][3] + 2:
            prio, focus, start, end = merged[-1]
            merged[-1] = (min(prio, item[0]), focus if prio <= item[0] else item[1], start, max(end, item[3]))
        else:
            merged.append(item)
    return merged


def _runs(lines: list[str], intervals: list[tuple[int, int, int, int]], limit: int) -> list[tuple[int, int]]:
    """The lines to show, best intervals first, each from its focus forward then back, whole lines, within ``limit`` chars."""
    chosen: set[int] = set()
    used = 0
    for _prio, focus, start, end in sorted(intervals, key=lambda item: item[0]):
        for direction in (range(focus, end + 1), range(focus - 1, start - 1, -1)):
            for number in direction:
                cost = len(lines[number - 1])
                if used + cost > limit:
                    break
                chosen.add(number)
                used += cost
    runs: list[list[int]] = []
    for number in sorted(chosen):
        if runs and runs[-1][1] == number - 1:
            runs[-1][1] = number
        else:
            runs.append([number, number])
    return [(a, b) for a, b in runs]


class _Source:
    """One file of the request: its text, its lines, and the intervals the task asks for."""

    def __init__(self, name: str, body: str, intervals: list[tuple[int, int, int, int]]) -> None:
        self.name, self.body, self.lines = name, body, _LINE.findall(body)
        self.intervals = intervals or [(0, 1, 1, len(self.lines))]  # no anchor: the beginning of the file

    def render(self, limit: int) -> Any:
        if len(self.body) <= limit:
            return self.body
        runs = _runs(self.lines, self.intervals, limit)
        omitted, next_line = [], 1
        for start, end in runs:
            if start > next_line:
                omitted.append({"start": next_line, "end": start - 1})
            next_line = end + 1
        if next_line <= len(self.lines):
            omitted.append({"start": next_line, "end": len(self.lines)})
        entry = {"total_lines": len(self.lines), "total_chars": len(self.body),
                 "windows": [{"start": a, "end": b, "text": "".join(self.lines[a - 1:b])} for a, b in runs],
                 "omitted": omitted}
        if limit:  # an outline (limit 0) is the cheapest form: the request rules say how to ask for lines
            entry["more"] = MORE
        return entry


def _tokens(files: Mapping[str, Any]) -> int:
    return estimate_tokens(json.dumps(files, ensure_ascii=False))


def build_files(root: Path, tasks: Sequence[Mapping[str, Any]], windows: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The current text of every existing target and context file, each once, in task order, within the total budget.

    ``windows`` are lines the caller asked for (``parse_window_spec`` / ``parse_need``): shown exactly, before anything
    else; a file no task names joins the request when it is asked for.
    """
    texts: dict[str, list[str]] = {}
    for task in tasks:
        for name in [task.get("target"), *(task.get("context") or [])]:
            if name and (root / str(name)).is_file():
                texts.setdefault(str(name), []).append(str(task.get("text") or ""))
    for window in windows:
        if (root / window["path"]).is_file():
            texts.setdefault(window["path"], [])
    sources = []
    for name, task_texts in texts.items():
        body = (root / name).read_bytes().decode("utf-8", errors="replace")
        lines = _LINE.findall(body)
        asked = [(-1, w["start"], w["start"], min(w["end"], len(lines))) for w in windows
                 if w["path"] == name and w["start"] <= len(lines)]
        intervals = asked + _anchors(name, lines, task_texts)
        if intervals:
            intervals.append((_HEADER_PRIORITY, 1, 1, min(len(lines), HEADER_LINES)))
        sources.append(_Source(name, body, _merge(intervals)))
    budget = resolve_ceiling(root) * BUDGET_PERCENT // 100
    limit = FILE_CHARS_MAX
    while True:
        files = {s.name: s.render(limit) for s in sources}
        used = _tokens(files)
        if used <= budget or limit <= MIN_FILE_CHARS:
            break
        limit = max(MIN_FILE_CHARS, int(limit * budget / used * 0.9))
    # Still over at the smallest limit: the files last in task order lose their windows (the omitted range stays).
    low, high, best = 1, len(sources), None
    while used > budget and low <= high:
        middle = (low + high) // 2
        candidate = {s.name: s.render(limit if i < len(sources) - middle else 0) for i, s in enumerate(sources)}
        if _tokens(candidate) <= budget:
            best, high = candidate, middle - 1
        else:
            low = middle + 1
    if used > budget:
        files = best if best is not None else {s.name: s.render(0) for s in sources}
        if _tokens(files) > budget:
            raise TooManyFilesError(f"{len(sources)} files do not fit {budget} tokens even as outlines: name fewer files")
    return files


def provider_text(name: str, entry: Mapping[str, Any]) -> str:
    """A window object as text for the provider message: ``[lines A-B]`` marker lines stand outside the file text."""
    shown = "".join(f"[lines {w['start']}-{w['end']}]\n{w['text']}" + ("" if w["text"].endswith("\n") else "\n")
                    for w in entry["windows"])
    ranges = ", ".join(f"{o['start']}-{o['end']}" for o in entry["omitted"])
    return f"Current {name} ({entry['total_lines']} lines):\n{shown}[not shown: lines {ranges}]"
