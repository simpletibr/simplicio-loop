"""Definition-of-done checklist parser and command gate runner."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

_CHECK_RE = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s+(?P<label>.+?)\s*$")
_COMMAND_RE = re.compile(r"`([^`]+)`")
_SHELL_META_RE = re.compile(r"[|;&><$`]")


@dataclass
class DodGate:
    label: str
    command: str | None = None
    checked: bool = False


def parse_dod(text: str) -> list[DodGate]:
    gates = []
    for line in text.splitlines():
        match = _CHECK_RE.match(line)
        if not match:
            continue
        label = match.group("label").strip()
        cmd_match = _COMMAND_RE.search(label)
        gates.append(
            DodGate(
                label=label,
                command=cmd_match.group(1) if cmd_match else None,
                checked=match.group("mark").lower() == "x",
            )
        )
    return gates


def load_dod(root: str | Path, path: str = ".specs/workflow/DOD.md") -> list[DodGate]:
    dod_path = Path(root) / path
    if not dod_path.is_file():
        return []
    return parse_dod(dod_path.read_text(encoding="utf-8"))


def load_sprint_dod(sprint_root: str | Path) -> list[DodGate]:
    root = Path(sprint_root)
    gates: list[DodGate] = []
    for path in [root / "SPRINT.md", *sorted(root.glob("*.task.md"))]:
        if path.is_file():
            gates.extend(parse_dod(path.read_text(encoding="utf-8")))
    return gates


def run_dod_gates(root: str | Path, gates: list[DodGate]) -> list[dict]:
    results = []
    allow_shell = os.environ.get("SIMPLICIO_DOD_ALLOW_SHELL", "").strip().lower() in {"1", "true", "yes"}
    for gate in gates:
        if not gate.command:
            results.append(
                {
                    "label": gate.label,
                    "passed": gate.checked,
                    "command": None,
                    "log": "manual DoD item is not checked" if not gate.checked else "",
                    "manual": True,
                }
            )
            continue
        try:
            if allow_shell:
                proc = subprocess.run(
                    gate.command,
                    shell=True,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
            else:
                if _SHELL_META_RE.search(gate.command):
                    raise ValueError(
                        "shell metacharacters are blocked by default; rerun with SIMPLICIO_DOD_ALLOW_SHELL=1"
                    )
                proc = subprocess.run(
                    shlex.split(gate.command),
                    shell=False,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    check=False,
                )
            passed = proc.returncode == 0
            log = (proc.stdout + proc.stderr)[-1500:]
        except subprocess.TimeoutExpired as exc:
            passed = False
            log = f"command timed out after {exc.timeout}s"
        except ValueError as exc:
            passed = False
            log = str(exc)
        results.append(
            {
                "label": gate.label,
                "passed": passed,
                "command": gate.command,
                "log": log,
                "manual": False,
            }
        )
    return results
