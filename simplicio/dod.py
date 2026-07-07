"""Definition-of-done checklist parser and command gate runner."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_CHECK_RE = re.compile(r"^\s*-\s+\[(?P<mark>[ xX])\]\s+(?P<label>.+?)\s*$")
_COMMAND_RE = re.compile(r"`([^`]+)`")


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
        proc = subprocess.run(
            gate.command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        results.append(
            {
                "label": gate.label,
                "passed": proc.returncode == 0,
                "command": gate.command,
                "log": (proc.stdout + proc.stderr)[-1500:],
                "manual": False,
            }
        )
    return results
