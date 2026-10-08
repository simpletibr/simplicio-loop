"""Turn REAL check output into ``simplicio.dashboard-event/v1`` payloads (test, lint, coverage, apply).

Pure producers: ``parse_*`` read the text a check printed and return a payload dict, or ``None``
when the output is not a recognised summary. Nothing is inferred or invented: a count the output
does not state is reported as 0 only when the parser saw the line that states it, and an
unrecognised output yields no event at all.

``emit_check`` / ``emit_diff`` append those payloads to the active run's ``events.jsonl`` through
the package-side emitter (``simplicio_loop.dashboard_events``). They are fail-open and never raise.
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from . import dashboard_events as _dashboard_events

COMMAND_MAX = 500
RULES_MAX = 20
COVERAGE_FILES_MAX = 50
DIFF_FILES_MAX = 200

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_COUNT = re.compile(r"(\d+) ([a-z]+)")

# pytest: "==== 3 failed, 10 passed in 1.23s ====" and the -q form "3 failed, 10 passed in 1.2s".
_PYTEST_KIND = r"(?:passed|failed|skipped|errors?|xfailed|xpassed|warnings?|deselected|rerun)"
_PYTEST_SUMMARY = re.compile(
    r"^[ \t]*(?:=+[ \t]*)?"
    r"(?P<body>\d+ " + _PYTEST_KIND + r"(?:, \d+ " + _PYTEST_KIND + r")*)"
    r"[ \t]+in (?P<secs>\d+(?:\.\d+)?)s(?: \(\d+:\d{2}:\d{2}\))?"
    r"[ \t]*(?:=+[ \t]*)?$",
    re.MULTILINE,
)

# unittest: "Ran 5 tests in 0.010s" then "OK (skipped=1)" or "FAILED (failures=1, errors=2)".
_UT_RAN = re.compile(r"^Ran (\d+) tests? in (\d+(?:\.\d+)?)s[ \t]*$", re.MULTILINE)
_UT_STATUS = re.compile(r"^(?:OK|FAILED)(?: \((?P<inner>.*)\))?[ \t]*$", re.MULTILINE)

# jest: "Tests:       1 failed, 4 passed, 5 total", "Time:        1.234 s".
# vitest: "      Tests  1 failed | 4 passed (5)", "   Duration  850ms".
_JEST_TESTS = re.compile(r"^[ \t]*Tests:[ \t]+(\d+ .*)$", re.MULTILINE)
_VITEST_TESTS = re.compile(r"^[ \t]*Tests[ \t]+(\d+ .*)$", re.MULTILINE)
_JEST_TIME = re.compile(r"^[ \t]*Time:[ \t]+(\d+(?:\.\d+)?)[ \t]*s\b", re.MULTILINE)
_VITEST_DURATION = re.compile(r"^[ \t]*Duration[ \t]+(\d+(?:\.\d+)?)(ms|s)\b", re.MULTILINE)

# go test: one line per package: "ok  \tpkg\t0.012s", "FAIL\tpkg\t0.034s", "FAIL\tpkg [build failed]".
_GO_OK = re.compile(r"^ok[ \t]+\S+[ \t]+(?:\(cached\)|\d+(?:\.\d+)?s)", re.MULTILINE)
_GO_FAIL = re.compile(r"^FAIL[ \t]+\S+[ \t]+\d+(?:\.\d+)?s", re.MULTILINE)
_GO_BUILD = re.compile(r"^FAIL[ \t]+\S+[ \t]+\[(?:build|setup) failed\]", re.MULTILINE)

# ruff / flake8 concise lines: "path:12:5: E501 message".
_LINT_LINE = re.compile(
    r"^(?P<path>[^\s:][^:\n]*):\d+:\d+: (?P<code>[A-Z]{1,5}\d{1,4})(?=\s|$)", re.MULTILINE)
_RUFF_FOUND = re.compile(
    r"^Found (\d+) errors?(?: \(\d+ fixed, (\d+) remaining\))?\.?[ \t]*$", re.MULTILINE)
_RUFF_OK = re.compile(r"^All checks passed!", re.MULTILINE)

# mypy: "path:3: error: message  [code]", "Found 2 errors in 1 file (checked 2 source files)".
_MYPY_LINE = re.compile(
    r"^(?P<path>[^\s:][^:\n]*):\d+(?::\d+)?: (?P<sev>error|warning): (?P<msg>.*?)"
    r"(?:\s+\[(?P<code>[\w.-]+)\])?[ \t]*$",
    re.MULTILINE,
)
_MYPY_FOUND = re.compile(r"^Found (\d+) errors? in \d+ files?", re.MULTILINE)
_MYPY_OK = re.compile(r"^Success: no issues found in \d+ source files?", re.MULTILINE)

# coverage.py / pytest-cov: "TOTAL   123   10   90%" (branch columns allowed) and per-file rows.
_COV_TOTAL = re.compile(r"^TOTAL(?:[ \t]+\d+)+[ \t]+(\d+(?:\.\d+)?)%", re.MULTILINE)
_COV_ROW = re.compile(
    r"^(?P<path>\S+)[ \t]+(?:\d+[ \t]+)+(?P<pct>\d+(?:\.\d+)?)%", re.MULTILINE)
_JEST_COV = re.compile(r"^[ \t]*All files[ \t]*\|[ \t]*(\d+(?:\.\d+)?)[ \t]*\|", re.MULTILINE)


# ---------------------------------------------------------------- helpers

def _text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return ""
    return _ANSI.sub("", value)


def _command(command: Any) -> str:
    return ("" if command is None else str(command))[:COMMAND_MAX]


def _returncode(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _seconds(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return round(number, 3)


def _failing(returncode: int | None, *counts: int) -> bool:
    return any(counts) or returncode not in (None, 0)


def _kv(inner: str, key: str) -> int:
    match = re.search(r"(?:^|, )%s=(\d+)" % key, inner)
    return int(match.group(1)) if match else 0


# ---------------------------------------------------------------- test_result

def _pytest(text: str) -> dict[str, Any] | None:
    matches = list(_PYTEST_SUMMARY.finditer(text))
    if not matches:
        return None
    last = matches[-1]
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for number, word in _COUNT.findall(last.group("body")):
        key = "errors" if word.startswith("error") else word
        if key in counts:
            counts[key] += int(number)
    return {"tool": "pytest", **counts, "duration": float(last.group("secs"))}


def _unittest(text: str) -> dict[str, Any] | None:
    ran = list(_UT_RAN.finditer(text))
    if not ran:
        return None
    last = ran[-1]
    status = _UT_STATUS.search(text, last.end())
    if status is None:
        return None
    inner = status.group("inner") or ""
    total = int(last.group(1))
    failed = _kv(inner, "failures")
    errors = _kv(inner, "errors")
    skipped = _kv(inner, "skipped")
    passed = max(0, total - failed - errors - skipped)
    return {"tool": "unittest", "passed": passed, "failed": failed, "skipped": skipped,
            "errors": errors, "total": total, "duration": float(last.group(2))}


def _jest_like(text: str) -> dict[str, Any] | None:
    tool = "jest"
    matches = list(_JEST_TESTS.finditer(text))
    if not matches:
        tool = "vitest"
        matches = list(_VITEST_TESTS.finditer(text))
    if not matches:
        return None
    body = matches[-1].group(1)
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    total: int | None = None
    for number, word in _COUNT.findall(body):
        if word in counts:
            counts[word] += int(number)
        elif word == "total":
            total = int(number)
    if tool == "vitest":
        paren = re.search(r"\((\d+)\)", body)
        total = int(paren.group(1)) if paren else None
    if total is None:
        total = sum(counts.values())
    duration = _jest_duration(text)
    return {"tool": tool, **counts, "errors": 0, "total": total, "duration": duration}


def _jest_duration(text: str) -> float | None:
    times = list(_JEST_TIME.finditer(text))
    if times:
        return float(times[-1].group(1))
    durations = list(_VITEST_DURATION.finditer(text))
    if durations:
        value = float(durations[-1].group(1))
        return value / 1000.0 if durations[-1].group(2) == "ms" else value
    return None


def _go(text: str) -> dict[str, Any] | None:
    passed = len(_GO_OK.findall(text))
    failed = len(_GO_FAIL.findall(text))
    errors = len(_GO_BUILD.findall(text))
    if not (passed or failed or errors):
        return None
    return {"tool": "go", "passed": passed, "failed": failed, "skipped": 0, "errors": errors,
            "total": passed + failed + errors, "duration": None}


def parse_tests(command: Any, text: Any, returncode: Any, duration_s: Any) -> dict[str, Any] | None:
    """Payload for a recognised pytest / unittest / jest / vitest / go test summary, else None.

    ``duration_s`` is the tool's own reported duration when the output states one, otherwise the
    caller's measured duration. ``status`` is ``fail`` on any failure, error or non-zero exit.
    """
    body = _text(text)
    found = _pytest(body) or _unittest(body) or _jest_like(body) or _go(body)
    if found is None:
        return None
    rc = _returncode(returncode)
    reported = found.get("duration")
    duration = round(float(reported), 3) if reported is not None else _seconds(duration_s)
    failed, errors = found["failed"], found["errors"]
    return {
        "tool": found["tool"],
        "command": _command(command),
        "passed": found["passed"],
        "failed": failed,
        "skipped": found["skipped"],
        "errors": errors,
        "total": found.get("total", found["passed"] + failed + found["skipped"] + errors),
        "duration_s": duration,
        "status": "fail" if _failing(rc, failed, errors) else "pass",
    }


# ---------------------------------------------------------------- lint_result

def _mypy(text: str) -> dict[str, Any] | None:
    lines = list(_MYPY_LINE.finditer(text))
    found = _MYPY_FOUND.findall(text)
    if not (lines or found or _MYPY_OK.search(text)):
        return None
    line_errors = sum(1 for m in lines if m.group("sev") == "error")
    warnings = sum(1 for m in lines if m.group("sev") == "warning")
    errors = int(found[-1]) if found else line_errors
    codes = [m.group("code") for m in lines if m.group("code")]
    return {"tool": "mypy", "errors": errors, "warnings": warnings, "codes": codes}


def _ruff_or_flake8(command: Any, text: str) -> dict[str, Any] | None:
    lines = list(_LINT_LINE.finditer(text))
    summaries = list(_RUFF_FOUND.finditer(text))
    ruff_ok = bool(_RUFF_OK.search(text))
    if not (lines or summaries or ruff_ok):
        return None
    codes = [m.group("code") for m in lines]
    warnings = sum(1 for code in codes if code.startswith("W"))
    if summaries:
        last = summaries[-1]
        errors = int(last.group(2)) if last.group(2) is not None else int(last.group(1))
    else:
        errors = len(codes) - warnings
    cmd = _command(command).lower()
    if re.search(r"\bflake8\b", cmd):
        tool = "flake8"
    elif re.search(r"\bruff\b", cmd) or summaries or ruff_ok:
        tool = "ruff"
    else:
        tool = "flake8"
    return {"tool": tool, "errors": errors, "warnings": warnings, "codes": codes}


def parse_lint(command: Any, text: Any, returncode: Any) -> dict[str, Any] | None:
    """Payload for recognised ruff / mypy / flake8 output, else None.

    ``errors`` comes from the tool's own summary when it prints one, otherwise it counts the
    diagnostic lines. ``by_rule`` counts coded diagnostics only, keeping the 20 most frequent.
    """
    body = _text(text)
    found = _mypy(body) or _ruff_or_flake8(command, body)
    if found is None:
        return None
    counts = Counter(found["codes"])
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:RULES_MAX]
    rc = _returncode(returncode)
    errors = found["errors"]
    return {
        "tool": found["tool"],
        "command": _command(command),
        "errors": errors,
        "warnings": found["warnings"],
        "by_rule": dict(ranked),
        "status": "fail" if _failing(rc, errors) else "pass",
    }


# ---------------------------------------------------------------- coverage_result

def parse_coverage(command: Any, text: Any) -> dict[str, Any] | None:
    """Payload for a coverage.py ``TOTAL`` row or a jest ``All files`` row, else None."""
    body = _text(text)
    totals = list(_COV_TOTAL.finditer(body))
    if totals:
        payload: dict[str, Any] = {
            "tool": "coverage",
            "command": _command(command),
            "percent": float(totals[-1].group(1)),
            "scope": "total",
        }
        files: list[dict[str, Any]] = []
        for row in _COV_ROW.finditer(body):
            if row.group("path") == "TOTAL":
                continue
            files.append({"path": row.group("path"), "percent": float(row.group("pct"))})
            if len(files) == COVERAGE_FILES_MAX:
                break
        if files:
            payload["files"] = files
        return payload
    jest = list(_JEST_COV.finditer(body))
    if jest:
        return {"tool": "jest", "command": _command(command),
                "percent": float(jest[-1].group(1)), "scope": "total"}
    return None


# ---------------------------------------------------------------- check + diff

def parse_check(command: Any, stdout: Any, stderr: Any, returncode: Any,
                duration_s: Any) -> list[tuple[str, dict[str, Any]]]:
    """Run every parser over stdout and stderr; return ``(kind, payload)`` for recognised output."""
    text = _text(stdout) + "\n" + _text(stderr)
    found: list[tuple[str, dict[str, Any]]] = []
    tests = parse_tests(command, text, returncode, duration_s)
    if tests is not None:
        found.append(("test_result", tests))
    lint = parse_lint(command, text, returncode)
    if lint is not None:
        found.append(("lint_result", lint))
    coverage = parse_coverage(command, text)
    if coverage is not None:
        found.append(("coverage_result", coverage))
    return found


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def diff_payload(measurement: Any) -> dict[str, Any] | None:
    """Payload for a measured diff from ``scripts/diff_escalation.evaluate``, else None."""
    if not isinstance(measurement, Mapping) or measurement.get("measured") is False:
        return None
    measurements = measurement.get("measurements")
    if not isinstance(measurements, Mapping):
        return None
    files = measurements.get("changed_files")
    added = measurements.get("added_lines")
    deleted = measurements.get("deleted_lines")
    if not isinstance(files, (list, tuple)) or not (_is_count(added) and _is_count(deleted)):
        return None
    paths = [str(path) for path in files]
    return {"step": "diff", "files": paths[:DIFF_FILES_MAX], "files_total": len(paths),
            "added": added, "deleted": deleted}


# ---------------------------------------------------------------- emitters (fail-open)

def _iteration(explicit: Any, env: Mapping[str, Any]) -> int | None:
    value = explicit if explicit is not None else env.get("SIMPLICIO_ITERATION")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _emit(task_id: Any, specs: Sequence[tuple[str, dict[str, Any], str]], iteration: Any,
          env: Any) -> list[dict[str, Any]]:
    module = _dashboard_events.load()
    if module is None:
        return []
    env_map: Mapping[str, Any] = os.environ if env is None else env
    if not module.enabled(env_map):
        return []
    run_dir = module.resolve_run_dir(env=env_map)
    if not run_dir:
        return []
    value = _iteration(iteration, env_map)
    written: list[dict[str, Any]] = []
    for kind, payload, severity in specs:
        evt = module.emit(run_dir, kind, source="worker", task_id=task_id, scope="task",
                          iteration=value, severity=severity, payload=payload)
        if evt:
            written.append(evt)
    return written


def _severity(payload: Mapping[str, Any]) -> str:
    return "warning" if payload.get("status") == "fail" else "info"


def emit_check(task_id: Any, command: Any, stdout: Any, stderr: Any, returncode: Any,
               duration_s: Any, iteration: Any = None,
               env: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Append one dashboard event per recognised check summary. Returns the written events.

    Returns ``[]`` when nothing is recognised, the kill switch is off, or no run directory or
    emitter is available. Never raises.
    """
    try:
        found = parse_check(command, stdout, stderr, returncode, duration_s)
        if not found:
            return []
        specs = [(kind, payload, _severity(payload)) for kind, payload in found]
        return _emit(task_id, specs, iteration, env)
    except Exception:
        return []


def emit_diff(task_id: Any, measurement: Any, iteration: Any = None,
              env: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Append one ``apply_result`` diff event for a measured diff. Never raises."""
    try:
        payload = diff_payload(measurement)
        if payload is None:
            return []
        return _emit(task_id, [("apply_result", payload, "info")], iteration, env)
    except Exception:
        return []
