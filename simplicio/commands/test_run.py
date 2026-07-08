"""``test run`` — run a test command and report structured pass/fail results.

Delegates to the native Rust ``simplicio test run`` binary when available
(via :mod:`simplicio.runtime_bridge`), falling back to a pure-Python
implementation otherwise. Mirrors the Rust CLI contract exactly::

    simplicio-dev-cli test run [--cmd <program>] [--json] [--repo <path>]
                                [-- <extra-args...>]

``--cmd`` is passed as ``argv[0]`` directly — never through a shell — with
anything after a literal ``--`` forwarded as additional argv elements.

JSON output shape (schema ``simplicio.test-run/v1``)::

    {"schema": "simplicio.test-run/v1", "cmd": "pytest", "args": [...],
     "exit_code": N, "passed": N|null, "failed": N|null, "errors": N|null,
     "duration_s": F|null, "summary": "...", "output_tail": "...",
     "output_truncated": bool}
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from ..runtime_bridge import discover_simplicio

SCHEMA = "simplicio.test-run/v1"
DEFAULT_CMD = "pytest"
OUTPUT_TAIL_CHARS = 4000
DEFAULT_TIMEOUT_S = 120.0
# Extra budget on top of the user's --timeout when delegating to the Rust
# binary, so the binary's own internal timeout gets a chance to fire and
# return a clean JSON payload before Python gives up on the subprocess call.
RUNTIME_DELEGATION_TIMEOUT_SLACK_S = 15.0

# Matches pytest's final summary line, e.g.:
#   "3 passed, 1 failed in 0.42s"
#   "1 passed, 1 error in 0.02s"
#   "24 deselected in 0.02s"
_PYTEST_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error(?:s)?)\b")
_PYTEST_DURATION_RE = re.compile(r"\bin\s+([\d.]+)s\b")
_PYTEST_SUMMARY_LINE_RE = re.compile(
    r"^=+ .* (?:passed|failed|error|deselected|no tests ran).* =+\s*$",
    re.MULTILINE,
)


def _build_runtime_args(a: argparse.Namespace, extra_args: list[str]) -> list[str]:
    cmd = ["test", "run", "--cmd", a.cmd, "--json"]
    if a.repo:
        cmd += ["--repo", a.repo]
    if extra_args:
        cmd += ["--", *extra_args]
    return cmd


def _run_via_runtime(a: argparse.Namespace, extra_args: list[str]) -> int | None:
    """Attempt delegation to the Rust ``simplicio`` binary.

    Returns the exit code on success, or ``None`` so the caller falls back
    to the Python implementation (binary missing, or the call errored in a
    way that suggests the subcommand isn't implemented there yet).
    """
    binary = discover_simplicio()
    if binary is None:
        return None
    binary_path = Path(binary)
    if sys.platform == "win32" and binary_path.suffix.lower() not in {".exe", ".bat", ".cmd", ".ps1", ".py"}:
        cmd = [sys.executable, binary, *_build_runtime_args(a, extra_args)]
    else:
        cmd = [binary, *_build_runtime_args(a, extra_args)]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=a.timeout + RUNTIME_DELEGATION_TIMEOUT_SLACK_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if payload.get("schema") != SCHEMA:
        return None

    if a.json:
        print(completed.stdout, end="")
    else:
        _print_human(payload)
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return int(payload.get("exit_code", completed.returncode))


def _parse_pytest_summary(output: str) -> tuple[int | None, int | None, int | None, float | None, str | None]:
    """Parse pytest's summary line for pass/fail/error counts and duration.

    Returns ``(passed, failed, errors, duration_s, summary_line)``. Any
    field that cannot be determined is ``None``.
    """
    lines = output.splitlines()
    summary_line = None
    for line in reversed(lines):
        if _PYTEST_COUNT_RE.search(line) or "no tests ran" in line.lower():
            summary_line = line.strip().strip("=").strip()
            break

    if summary_line is None:
        return None, None, None, None, None

    counts = {"passed": 0, "failed": 0, "error": 0, "errors": 0}
    for match in _PYTEST_COUNT_RE.finditer(summary_line):
        count, label = match.groups()
        counts[label] = int(count)

    duration_match = _PYTEST_DURATION_RE.search(summary_line)
    duration = float(duration_match.group(1)) if duration_match else None

    passed = counts["passed"]
    failed = counts["failed"]
    errors = counts["error"] + counts["errors"]

    return passed, failed, errors, duration, summary_line


def _run_fallback(a: argparse.Namespace, extra_args: list[str]) -> int:
    repo_root = Path(a.repo or ".").resolve()
    argv = [a.cmd, *extra_args]

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=repo_root,
            timeout=a.timeout,
        )
    except FileNotFoundError:
        print(
            f"simplicio-dev-cli test run: command not found: {a.cmd!r}",
            file=sys.stderr,
        )
        return 1
    except subprocess.TimeoutExpired as exc:
        combined = (exc.stdout or "") + (exc.stderr or "")
        output_truncated = len(combined) > OUTPUT_TAIL_CHARS
        output_tail = combined[-OUTPUT_TAIL_CHARS:] if output_truncated else combined
        payload = {
            "schema": SCHEMA,
            "cmd": a.cmd,
            "args": extra_args,
            "exit_code": None,
            "passed": None,
            "failed": None,
            "errors": None,
            "duration_s": None,
            "summary": f"{a.cmd}: timed out after {a.timeout}s",
            "output_tail": output_tail,
            "output_truncated": output_truncated,
        }
        if a.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            _print_human(payload)
        return 124  # shell convention for "command timed out"
    except OSError as exc:
        print(f"simplicio-dev-cli test run: failed to launch {a.cmd!r}: {exc}", file=sys.stderr)
        return 1

    combined_output = completed.stdout + completed.stderr

    passed = failed = errors = None
    duration_s = None
    summary = None
    is_pytest = a.cmd == "pytest" or "pytest" in a.cmd or "= test session starts =" in combined_output
    if is_pytest:
        passed, failed, errors, duration_s, summary = _parse_pytest_summary(combined_output)

    if summary is None:
        summary = (
            f"{a.cmd} exited {completed.returncode}" if completed.returncode != 0 else f"{a.cmd} exited 0"
        )

    output_truncated = len(combined_output) > OUTPUT_TAIL_CHARS
    output_tail = combined_output[-OUTPUT_TAIL_CHARS:] if output_truncated else combined_output

    payload = {
        "schema": SCHEMA,
        "cmd": a.cmd,
        "args": extra_args,
        "exit_code": completed.returncode,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "duration_s": duration_s,
        "summary": summary,
        "output_tail": output_tail,
        "output_truncated": output_truncated,
    }

    if a.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        _print_human(payload)

    return completed.returncode


def _print_human(payload: dict) -> None:
    print(f"{payload['cmd']}: {payload['summary']}")
    if payload.get("passed") is not None or payload.get("failed") is not None:
        print(
            f"  passed={payload.get('passed')} failed={payload.get('failed')} errors={payload.get('errors')}"
        )
    print(f"  exit_code={payload['exit_code']}")
    if payload.get("output_tail"):
        print("--- output tail ---")
        print(payload["output_tail"], end="" if payload["output_tail"].endswith("\n") else "\n")
        if payload.get("output_truncated"):
            print("(output truncated)")


def run(a: argparse.Namespace, extra_args: list[str]) -> int:
    """Entry point wired from ``cli.py`` for ``simplicio-dev-cli test run``."""
    result = _run_via_runtime(a, extra_args)
    if result is not None:
        return result
    return _run_fallback(a, extra_args)
