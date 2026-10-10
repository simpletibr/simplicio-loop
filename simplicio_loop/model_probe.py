"""Probe the model-roles catalog against the real CLIs (issue #1674).

For each (family, role) it calls the family CLI with the catalog model and a
trivial prompt. An accepted id exits 0; a refused id prints its reason_code and
a redacted error excerpt. There is no fallback to another model.

    python -m simplicio_loop.model_probe [--family grok] [--role execution] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

CATALOG = Path(__file__).resolve().parent / "_catalog" / "model_roles.json"
PROMPT = "reply with the single word ok"
TIMEOUT_S = 180

COMMANDS: dict[str, Callable[[str], list[str]]] = {
    "claude": lambda model: ["claude", "-p", "--model", model, PROMPT],
    "codex": lambda model: [
        "codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m", model, PROMPT
    ],
    "gemini": lambda model: ["gemini", "-m", model, "-p", PROMPT],
    "grok": lambda model: ["grok", "-m", model, "-p", PROMPT],
}

_REFUSED = re.compile(
    r"not supported|unknown model|invalid params|model_not_found|does not exist", re.IGNORECASE
)
_SECRET = re.compile(
    r"(?:sk-|xai-|AIza)[A-Za-z0-9_-]{8,}|Bearer\s+\S+|(?:api[_-]?key|token)\s*[:=]\s*\S+",
    re.IGNORECASE,
)
_EXCERPT = 300


def run_cli(argv: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    return proc.returncode, f"{proc.stderr}\n{proc.stdout}".strip()


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


def excerpt(output: str) -> str:
    for line in output.splitlines():
        if _REFUSED.search(line):
            return redact(line.strip())[:_EXCERPT]
    return redact(output.strip())[-_EXCERPT:]


def is_listed(model: str, listing: str) -> bool:
    return re.search(rf"(?<![\w.-]){re.escape(model)}(?![\w.-])", listing) is not None


def probe(
    family: str,
    role: str,
    model: str,
    run: Callable[[list[str]], tuple[int, str]] = run_cli,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "family": family,
        "role": role,
        "model": model,
        "command": None,
        "exit": None,
        "error": "",
    }
    build = COMMANDS.get(family)
    if build is None or model == "default":
        return {**result, "status": "skipped", "reason_code": "not_probeable"}
    argv = build(model)
    result["command"] = shlex.join(argv)
    if which(argv[0]) is None:
        return {**result, "status": "skipped", "reason_code": "cli_missing"}
    code, output = run(argv)
    result["exit"] = code
    if code == 0:
        return {**result, "status": "accepted", "reason_code": "ok"}
    if code == -1 and output == "timeout":
        reason = "timeout"
    elif _REFUSED.search(output):
        reason = "model_refused"
    else:
        reason = "cli_error"
    return {**result, "status": "refused", "reason_code": reason, "error": excerpt(output)}


def probe_catalog(
    catalog: dict[str, Any],
    families: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    run: Callable[[list[str]], tuple[int, str]] = run_cli,
    which: Callable[[str], str | None] = shutil.which,
) -> list[dict[str, Any]]:
    rows = []
    for family, by_role in catalog["families"].items():
        if families and family not in families:
            continue
        for role, spec in by_role.items():
            if roles and role not in roles:
                continue
            rows.append(probe(family, role, spec["model"], run=run, which=which))
    return rows


def main(
    argv: Sequence[str] | None = None,
    run: Callable[[list[str]], tuple[int, str]] = run_cli,
    which: Callable[[str], str | None] = shutil.which,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m simplicio_loop.model_probe",
        description="Probe each (family, role) model id of the model-roles catalog with its CLI.",
    )
    parser.add_argument("--family", action="append", help="probe only this family (repeatable)")
    parser.add_argument("--role", action="append", help="probe only this role (repeatable)")
    parser.add_argument("--catalog", type=Path, default=CATALOG, help="model-roles catalog file")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    args = parser.parse_args(argv)
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    rows = probe_catalog(catalog, args.family, args.role, run=run, which=which)
    if args.json:
        print(json.dumps({"schema": "simplicio.model-probe/v1", "results": rows}, indent=2))
    else:
        for row in rows:
            line = (
                f"{row['family']}/{row['role']} {row['model']}: {row['status']}"
                f" reason_code={row['reason_code']} exit={row['exit']}"
            )
            if row["command"]:
                line += f" command={row['command']}"
            if row["error"]:
                line += f" error={row['error']}"
            print(line)
    return 1 if any(row["status"] == "refused" for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
