#!/usr/bin/env python3
"""Guard: a claimed Runtime/Agent integration needs real E2E evidence (#167).

Heuristic, local, deterministic policy check — mirrors the "loud,
deterministic, --check exits nonzero" pattern already used by
`scripts/gen_package_interdependence.py --check`. It does **not** call the
GitHub API and does **not** replace human review; it just catches the common
case where a commit/PR claims an integration is "complete"/"done"/"funcional"
without the diff touching this repo's E2E-test surface
(`tests/contracts/*.py`, `tests/python/test_*e2e*.py`,
`tests/python/test_*integration*.py` — see `tests/contracts/test_end_to_end_flow.py`
and `tests/python/test_mapper_handoff_integration.py` for the convention
already in place).

Usage:
    # message from a file, changed files from args
    python3 scripts/check_integration_claims.py --message-file msg.txt \\
        --files simplicio/pipeline.py tests/contracts/test_end_to_end_flow.py

    # message from stdin (e.g. `git log -1 --format=%B`), changed files from
    # `git diff --name-only` piped into a file
    git log -1 --format=%B > /tmp/msg.txt
    git diff --name-only origin/master... > /tmp/files.txt
    python3 scripts/check_integration_claims.py --message-file /tmp/msg.txt \\
        --files-file /tmp/files.txt

Exit codes: 0 = no integration claim, or claim backed by an E2E test file in
the diff. 1 = integration claim detected with no matching E2E file changed.

This is a heuristic guard, not a perfect gate: it can miss claims phrased
unusually, and it can be satisfied by touching an E2E file unrelated to the
actual claim. It exists to catch the common, unambiguous case cheaply and
locally — not to replace the "Verificação independente/adversarial pós-verde"
DoD step or human review.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Three keyword groups; a message is treated as an "integration claim" only
# when it hits at least one term from *each* group (case-insensitive). This
# keeps the heuristic from firing on routine mentions of "integration" or
# "Runtime" alone.
_INTEGRATION_WORDS = re.compile(r"integra(c|ç)[aã]o|integration", re.IGNORECASE)
_SUBJECT_WORDS = re.compile(r"\bruntime\b|\bagent\b", re.IGNORECASE)
_COMPLETION_WORDS = re.compile(
    r"\bcomplet[ao]?s?\b|\bcomplete[ds]?\b|\bdone\b|\bfuncional\b|\bfinalizad[ao]s?\b",
    re.IGNORECASE,
)

# E2E-test naming convention already in place in this repo (see
# tests/contracts/test_end_to_end_flow.py and
# tests/python/test_mapper_handoff_integration.py /
# tests/python/test_plan_compiler_golden_e2e.py).
_E2E_FILE_PATTERNS = (
    re.compile(r"^tests/contracts/.*\.py$"),
    re.compile(r"^tests/python/test_.*e2e.*\.py$", re.IGNORECASE),
    re.compile(r"^tests/python/test_.*integration.*\.py$", re.IGNORECASE),
)


def is_integration_claim(message: str) -> bool:
    """True when *message* claims a Runtime/Agent integration is done."""
    return bool(
        _INTEGRATION_WORDS.search(message)
        and _SUBJECT_WORDS.search(message)
        and _COMPLETION_WORDS.search(message)
    )


def touches_e2e_evidence(changed_files: list[str]) -> bool:
    """True when at least one changed file matches the E2E-test convention."""
    return any(
        pattern.match(path.replace("\\", "/")) for path in changed_files for pattern in _E2E_FILE_PATTERNS
    )


def check(message: str, changed_files: list[str]) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for *message* claimed against *changed_files*."""
    if not is_integration_claim(message):
        return True, "no Runtime/Agent integration claim detected"
    if touches_e2e_evidence(changed_files):
        return True, "integration claim backed by an E2E test file in the diff"
    return False, (
        "integration claim detected (Runtime/Agent + integration + "
        "complete/done/funcional) but no E2E test file changed "
        "(expected tests/contracts/*.py, tests/python/test_*e2e*.py, "
        "or tests/python/test_*integration*.py)"
    )


def _read_text_arg(value: str | None, file_value: str | None, *, allow_stdin: bool) -> str:
    if value is not None:
        return value
    if file_value is not None:
        return Path(file_value).read_text(encoding="utf-8")
    if allow_stdin:
        return sys.stdin.read()
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--message", help="commit/PR message text (inline)")
    parser.add_argument("--message-file", help="path to a file containing the commit/PR message")
    parser.add_argument("--files", nargs="*", default=None, help="changed file paths (space-separated)")
    parser.add_argument("--files-file", help="path to a newline-separated list of changed file paths")
    args = parser.parse_args(argv)

    message = _read_text_arg(args.message, args.message_file, allow_stdin=True)

    if args.files is not None:
        changed_files = args.files
    elif args.files_file is not None:
        raw_lines = Path(args.files_file).read_text(encoding="utf-8").splitlines()
        changed_files = [line.strip() for line in raw_lines if line.strip()]
    else:
        changed_files = []

    ok, reason = check(message, changed_files)
    if ok:
        print(f"OK: {reason}")
        return 0
    print(f"BLOCKED: {reason}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
