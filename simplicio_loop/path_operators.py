"""Stale operators on PATH: a `simplicio-mapper` or `simplicio-dev-cli` that is not the one bundled with this loop (#1575).

An old standalone mapper can share the version number of the bundled one (0.26.35) and still lack the build identity the
loop needs, so a mapper is compared by identity (version, origin, source commit), read by the interpreter of its own
shebang. A dev-cli is compared by version. Read-only: the only things run are `<interpreter> -I -c <probe>` and
`<operator> --version`, each with a timeout. `doctor` shows the findings and the fix command.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any, Callable, Optional

from . import mapper_doctor

OPERATORS = ("simplicio-mapper", "simplicio-dev-cli")
Run = Callable[[list], tuple]

_PROBE = (
    "import json\n"
    "try:\n import simplicio_mapper as m\n"
    "except Exception:\n print(json.dumps({'error': 'not_importable'})); raise SystemExit\n"
    "try:\n from simplicio_mapper.build_identity import build_identity as b\n"
    "except ImportError:\n print(json.dumps({'version': getattr(m, '__version__', None), 'error': 'no_build_identity'}))\n"
    "else:\n print(json.dumps(dict(b())))\n"
)
_VERSION = re.compile(r"(\d+\.\d+\.\d+)")
_SHA = re.compile(r"[0-9a-f]{40}")


def _run(argv: list) -> tuple:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout


def _bundled() -> dict:
    """Identity of the operators this loop ships: the importable mapper and dev-cli."""
    mapper: dict = {}
    try:
        from simplicio_mapper.build_identity import build_identity
        mapper = dict(build_identity())
    except ImportError:
        pass
    dev_cli = ""
    try:
        import simplicio
        dev_cli = str(getattr(simplicio, "__version__", ""))
    except ImportError:
        pass
    return {"mapper": mapper, "dev_cli_version": dev_cli}


def _interpreter(path: str, which: Callable[[str], Optional[str]]) -> Optional[str]:
    """The interpreter named by the `#!` line of `path`, or None for a native binary."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(200)
    except OSError:
        return None
    if not head.startswith(b"#!"):
        return None
    parts = head.decode("utf-8", errors="ignore").splitlines()[0][2:].split()
    if not parts:
        return None
    if os.path.basename(parts[0]) == "env":
        return which(parts[1]) if len(parts) > 1 else None
    return parts[0]


def _mapper(path: str, interpreter: Optional[str], bundled: dict, run: Run) -> tuple:
    """(reason_code or None, what was found)."""
    if interpreter is None:  # a native build: the version is all it tells
        rc, out = run([path, "--version"])
        found = _VERSION.search(out)
        if rc != 0 or not found:
            return "mapper_not_importable", None
        version = found.group(1)
        return (None if version == bundled.get("version") else "version_mismatch"), {"version": version, "path": path}
    rc, out = run([interpreter, "-I", "-c", _PROBE])
    try:
        data = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        data = None
    if rc != 0 or not isinstance(data, dict) or data.get("error") == "not_importable":
        return "mapper_not_importable", data if isinstance(data, dict) else None
    if data.get("error") == "no_build_identity":
        return "mapper_identity_missing", data
    if data.get("version") != bundled.get("version"):
        return "version_mismatch", data
    if data.get("origin") != (bundled.get("origin") or mapper_doctor.EXPECTED_ORIGIN):
        return "origin_mismatch", data
    found, want = data.get("source_commit"), bundled.get("source_commit")
    if all(isinstance(sha, str) and _SHA.fullmatch(sha) for sha in (found, want)) and found != want:
        return "commit_mismatch", data
    return None, data


def _dev_cli(path: str, want: str, run: Run) -> tuple:
    rc, out = run([path, "--version"])
    found = _VERSION.search(out)
    if rc != 0 or not found:
        return "dev_cli_version_unreadable", None
    return (None if found.group(1) == want else "version_mismatch"), {"version": found.group(1), "path": path}


def _fix(path: str, interpreter: Optional[str]) -> str:
    if interpreter:
        return (f"{interpreter} -m pip uninstall -y simplicio-mapper simplicio-cli && "
                f"{interpreter} -m pip install --force-reinstall simplicio-loop  (as the user that owns {path})")
    return f"remove {path}, then run: python3 -m pip install --force-reinstall simplicio-loop"


def check(*, which: Optional[Callable[[str], Optional[str]]] = None, run: Optional[Run] = None,
          bundled: Optional[dict] = None, frozen_exe: Optional[str] = None) -> list:
    """One row per operator: name, path, status (absent|ok|stale), reason_code, found, bundled, fix.

    `frozen_exe`: a PATH entry that resolves to this file is the multi-call binary itself and is ok.
    """
    which, run = which or shutil.which, run or _run
    bundled = bundled if bundled is not None else _bundled()
    own = os.path.realpath(frozen_exe) if frozen_exe else None
    rows = []
    for name in OPERATORS:
        want = bundled["mapper"] if name == "simplicio-mapper" else bundled["dev_cli_version"]
        path = which(name)
        row: dict[str, Any] = {"name": name, "path": path, "status": "absent", "reason_code": None,
                               "found": None, "bundled": want, "fix": None}
        if path is not None:
            interpreter = _interpreter(path, which)
            if own and os.path.realpath(path) == own:
                reason, found = None, {"path": path}
            elif name == "simplicio-mapper":
                reason, found = _mapper(path, interpreter, want, run)
            else:
                reason, found = _dev_cli(path, want, run)
            row.update(status="ok" if reason is None else "stale", reason_code=reason, found=found,
                       fix=None if reason is None else _fix(path, interpreter))
        rows.append(row)
    return rows


def stale(findings: list) -> list:
    return [row for row in findings if row["status"] == "stale"]


__all__ = ["OPERATORS", "check", "stale"]
