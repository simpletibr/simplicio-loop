"""Detect stale operators on PATH: simplicio-mapper and simplicio-dev-cli.

This module checks if the operators found on PATH match the bundled versions
by examining their build identity, version numbers, and commit hashes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from simplicio_loop import mapper_doctor

OPERATORS = ("simplicio-mapper", "simplicio-dev-cli")

_PROBE = """import json, sys
try:
    import simplicio_mapper
    from simplicio_mapper.build_identity import build_identity
    print(json.dumps(dict(build_identity())))
except ImportError as e:
    if 'build_identity' in str(e):
        import simplicio_mapper as _sm
        v = getattr(_sm, '__version__', None)
        print(json.dumps({'version': v, 'error': 'no_build_identity'}))
    else:
        print(json.dumps({'error': 'not_importable'}))
except Exception as e:
    print(json.dumps({'error': 'not_importable'}))
"""

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def _run(argv: list[str]) -> tuple[int, str]:
    """Default _run: execute argv with 20s timeout, return (rc, stdout)."""
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=20,
        )
        return (result.returncode, result.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return (127, "")


def check(
    *,
    which: Callable[[str], str | None] | None = None,
    run: Callable[[list[str]], tuple[int, str]] | None = None,
    bundled: dict[str, Any] | None = None,
    frozen_exe: str | None = None,
) -> list[dict[str, Any]]:
    """Check if operators on PATH match the bundled versions.

    Args:
        which: function to find a command on PATH (default: shutil.which).
        run: function to run a command (default: _run with 20s timeout).
        bundled: dict with 'mapper' and 'dev_cli_version' keys (default: auto-detect).
        frozen_exe: path to a multi-call binary; if a PATH entry resolves to this, it's ok.

    Returns:
        List of dicts, one per operator: {name, path, status, reason_code, found, bundled, fix}.
    """
    if which is None:
        which = shutil.which
    if run is None:
        run = _run

    if bundled is None:
        bundled = _compute_bundled()

    frozen_exe_real = None
    if frozen_exe:
        try:
            frozen_exe_real = os.path.realpath(frozen_exe)
        except (OSError, ValueError):
            pass

    findings = []
    for op_name in OPERATORS:
        path = which(op_name)
        if path is None:
            findings.append({
                "name": op_name,
                "path": None,
                "status": "absent",
                "reason_code": None,
                "found": None,
                "bundled": bundled.get("mapper" if op_name == "simplicio-mapper" else "dev_cli_version"),
                "fix": None,
            })
            continue

        # Check if this is the frozen_exe
        if frozen_exe_real:
            try:
                if os.path.realpath(path) == frozen_exe_real:
                    findings.append({
                        "name": op_name,
                        "path": path,
                        "status": "ok",
                        "reason_code": None,
                        "found": {"path": path},
                        "bundled": bundled.get("mapper" if op_name == "simplicio-mapper" else "dev_cli_version"),
                        "fix": None,
                    })
                    continue
            except (OSError, ValueError):
                pass

        if op_name == "simplicio-mapper":
            finding = _check_mapper(path, bundled["mapper"], which, run)
        else:
            finding = _check_devcli(path, bundled["dev_cli_version"], which, run)

        finding["bundled"] = bundled.get(
            "mapper" if op_name == "simplicio-mapper" else "dev_cli_version"
        )
        findings.append(finding)

    return findings


def _compute_bundled() -> dict[str, Any]:
    """Compute the bundled operator versions and identities."""
    mapper_identity = {}
    try:
        from simplicio_mapper import build_identity
        mapper_identity = dict(build_identity())
    except (ImportError, Exception):
        # Fall back to trying to import simplicio_mapper and get version
        try:
            import simplicio_mapper
            mapper_identity = {"version": getattr(simplicio_mapper, "__version__", "unknown")}
        except ImportError:
            mapper_identity = {"version": "unknown"}

    dev_cli_version = "unknown"
    try:
        import simplicio
        dev_cli_version = getattr(simplicio, "__version__", "unknown")
    except ImportError:
        pass

    return {
        "mapper": mapper_identity,
        "dev_cli_version": dev_cli_version,
    }


def _check_mapper(
    path: str,
    bundled_mapper: dict[str, Any],
    which: Callable[[str], str | None],
    run: Callable[[list[str]], tuple[int, str]],
) -> dict[str, Any]:
    """Check a mapper on PATH."""
    # Check if it's a native binary or a script
    try:
        with open(path, "rb") as f:
            header = f.read(200)
    except (OSError, IOError):
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "mapper_not_importable",
            "found": None,
            "fix": _fix_mapper(path, which),
        }

    # Check if it's a shebang script or native binary
    if header.startswith(b"#!"):
        # Script with shebang
        try:
            shebang_line = header.decode("utf-8", errors="ignore").split("\n")[0]
        except Exception:
            shebang_line = ""

        # Parse shebang to find interpreter
        interp = _parse_shebang(shebang_line, which)
        if not interp:
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "mapper_not_importable",
                "found": None,
                "fix": _fix_mapper(path, which),
            }

        # Run the probe
        rc, stdout = run([interp, "-I", "-c", _PROBE])
        return _evaluate_mapper_probe(path, rc, stdout, bundled_mapper, interp, which)
    else:
        # Native binary: just check version
        rc, stdout = run([path, "--version"])
        if rc != 0:
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "mapper_not_importable",
                "found": {"path": path},
                "fix": _fix_mapper(path, which),
            }

        # Extract version from output
        match = _VERSION_RE.search(stdout)
        if not match:
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "mapper_not_importable",
                "found": {"path": path},
                "fix": _fix_mapper(path, which),
            }

        found_version = match.group(1)
        bundled_version = bundled_mapper.get("version", "unknown")

        if found_version != bundled_version:
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "version_mismatch",
                "found": {"version": found_version, "path": path},
                "fix": _fix_mapper(path, which),
            }

        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "ok",
            "reason_code": None,
            "found": {"version": found_version, "path": path},
            "fix": None,
        }


def _check_devcli(
    path: str,
    bundled_version: str,
    which: Callable[[str], str | None],
    run: Callable[[list[str]], tuple[int, str]],
) -> dict[str, Any]:
    """Check a dev-cli on PATH."""
    rc, stdout = run([path, "--version"])
    if rc != 0:
        return {
            "name": "simplicio-dev-cli",
            "path": path,
            "status": "stale",
            "reason_code": "dev_cli_version_unreadable",
            "found": None,
            "fix": _fix_devcli(path, which),
        }

    # Extract version from output (e.g. "simplicio-py 0.26.35")
    match = _VERSION_RE.search(stdout)
    if not match:
        return {
            "name": "simplicio-dev-cli",
            "path": path,
            "status": "stale",
            "reason_code": "dev_cli_version_unreadable",
            "found": {"path": path},
            "fix": _fix_devcli(path, which),
        }

    found_version = match.group(1)
    if found_version != bundled_version:
        return {
            "name": "simplicio-dev-cli",
            "path": path,
            "status": "stale",
            "reason_code": "version_mismatch",
            "found": {"version": found_version, "path": path},
            "fix": _fix_devcli(path, which),
        }

    return {
        "name": "simplicio-dev-cli",
        "path": path,
        "status": "ok",
        "reason_code": None,
        "found": {"version": found_version, "path": path},
        "fix": None,
    }


def _evaluate_mapper_probe(
    path: str,
    rc: int,
    stdout: str,
    bundled_mapper: dict[str, Any],
    interp: str,
    which: Callable[[str], str | None],
) -> dict[str, Any]:
    """Evaluate the mapper probe result."""
    if rc != 0:
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "mapper_not_importable",
            "found": None,
            "fix": _fix_mapper(path, which),
        }

    # Parse the JSON output
    try:
        data = json.loads(stdout.strip())
    except json.JSONDecodeError:
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "mapper_not_importable",
            "found": None,
            "fix": _fix_mapper(path, which),
        }

    # Check for errors
    if "error" in data:
        if data["error"] == "no_build_identity":
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "mapper_identity_missing",
                "found": data,
                "fix": _fix_mapper(path, which),
            }
        else:
            return {
                "name": "simplicio-mapper",
                "path": path,
                "status": "stale",
                "reason_code": "mapper_not_importable",
                "found": data,
                "fix": _fix_mapper(path, which),
            }

    # Compare with bundled
    found_version = data.get("version")
    bundled_version = bundled_mapper.get("version")

    if found_version != bundled_version:
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "version_mismatch",
            "found": data,
            "fix": _fix_mapper(path, which),
        }

    found_origin = data.get("origin")
    bundled_origin = bundled_mapper.get("origin")

    if found_origin != bundled_origin:
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "origin_mismatch",
            "found": data,
            "fix": _fix_mapper(path, which),
        }

    # Check commit
    found_commit = data.get("source_commit")
    bundled_commit = bundled_mapper.get("source_commit")

    if _is_sha(found_commit) and _is_sha(bundled_commit) and found_commit != bundled_commit:
        return {
            "name": "simplicio-mapper",
            "path": path,
            "status": "stale",
            "reason_code": "commit_mismatch",
            "found": data,
            "fix": _fix_mapper(path, which),
        }

    return {
        "name": "simplicio-mapper",
        "path": path,
        "status": "ok",
        "reason_code": None,
        "found": data,
        "fix": None,
    }


def _parse_shebang(shebang_line: str, which: Callable[[str], str | None]) -> str | None:
    """Extract interpreter path from shebang."""
    if not shebang_line.startswith("#!"):
        return None

    shebang = shebang_line[2:].strip()
    parts = shebang.split()
    if not parts:
        return None

    # Handle /usr/bin/env case
    if "env" in parts[0]:
        if len(parts) > 1:
            return which(parts[1])
        return None

    # Direct path
    return parts[0] if parts[0] else None


def _is_sha(value: str | Any) -> bool:
    """Check if a value is a valid 40-char hex SHA."""
    if not isinstance(value, str):
        return False
    return len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def _fix_mapper(path: str, which: Callable[[str], str | None]) -> str:
    """Generate the fix command for a stale mapper."""
    # Try to extract the interpreter from the shebang
    try:
        with open(path, "rb") as f:
            header = f.read(200)
        if header.startswith(b"#!"):
            try:
                shebang_line = header.decode("utf-8", errors="ignore").split("\n")[0]
                interp = _parse_shebang(shebang_line, which)
                if interp:
                    return f"{interp} -m pip uninstall -y simplicio-mapper simplicio-cli && {interp} -m pip install --force-reinstall simplicio-loop"
            except Exception:
                pass
    except (OSError, IOError):
        pass

    return f"remove {path}, then run: python3 -m pip install --force-reinstall simplicio-loop"


def _fix_devcli(path: str, which: Callable[[str], str | None]) -> str:
    """Generate the fix command for a stale dev-cli."""
    # Try to extract the interpreter from the shebang
    try:
        with open(path, "rb") as f:
            header = f.read(200)
        if header.startswith(b"#!"):
            try:
                shebang_line = header.decode("utf-8", errors="ignore").split("\n")[0]
                interp = _parse_shebang(shebang_line, which)
                if interp:
                    return f"{interp} -m pip uninstall -y simplicio-mapper simplicio-cli && {interp} -m pip install --force-reinstall simplicio-loop"
            except Exception:
                pass
    except (OSError, IOError):
        pass

    return f"remove {path}, then run: python3 -m pip install --force-reinstall simplicio-loop"


def stale(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter findings to return only stale operators."""
    return [f for f in findings if f.get("status") == "stale"]


__all__ = ["OPERATORS", "check", "stale"]
