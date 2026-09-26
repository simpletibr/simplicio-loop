#!/usr/bin/env python3
"""Fail-closed stack preflight for the Task-to-Delivery boundary.

The runner can be exercised with local fakes, but a real promotion must prove that
the two core external operators are the expected identities and expose compatible
capabilities. The optional native runtime is reported separately, never promoted to
a core-loop blocker. This command performs those checks without importing an operator
in-process and emits one stable receipt suitable for CI or a run journal.

Usage::

    python scripts/preflight.py --json

The command intentionally returns non-zero when the Runtime contract smoke is
unhealthy.  A warning is not promoted to ``ready`` and callers must not treat a
missing/unknown version as compatible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _emit_progress(status: str, outcome: str | None = None, detail: str = "") -> None:
    """Fail-open progress-feedback hook (#299) — never raises, never blocks preflight itself."""
    try:
        import loop_progress
        loop_progress.emit_event("preflight", status=status, outcome=outcome, detail=detail,
                                 source="preflight.py")
    except Exception:
        pass

SCHEMA = "simplicio.preflight/v1"
MINIMUMS = {
    "simplicio-mapper": (0, 19, 0),
    "simplicio-dev-cli": (0, 11, 0),
    "simplicio-runtime": (3, 5, 0),
}
MAPPER_CAPABILITIES = ("inspect", "handoff", "ask", "sync", "drift")
DEVCLI_CAPABILITIES = (" edit", "--plan", "--apply", "--json")


def _version(value: str) -> tuple[int, int, int]:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value or "")
    if not match:
        return (0, 0, 0)
    return tuple(int(match.group(i) or 0) for i in range(1, 4))  # type: ignore[return-value]


def _version_text(value: Sequence[int]) -> str:
    return ".".join(str(part) for part in value)


def _run(argv: Sequence[str], cwd: Path, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          timeout=timeout, env=dict(os.environ))


def _last_json(text: str) -> Dict[str, Any]:
    """Parse a JSON object from noisy progress output (including Windows hosts)."""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def _tool_report(name: str, command: str, minimum: Sequence[int], result: Mapping[str, Any],
                 required: Iterable[str] = ()) -> Dict[str, Any]:
    raw_version = str(result.get("version_text") or "")
    parsed = _version(raw_version)
    required_list = list(required)
    surface = str(result.get("surface") or "")
    missing = [token for token in required_list if token not in (" " + surface)]
    resolved_path = str(result.get("path") or "")
    # Identity is deliberately based on the resolved executable, not a caller
    # supplied label.  This catches a stale/legacy ``simplicio.exe`` selected in
    # front of the canonical ``simplicio.cmd`` on Windows.
    path_stem = Path(resolved_path).stem.lower() if resolved_path else ""
    expected_stems = {
        "simplicio-runtime": ("simplicio",),
        "simplicio-dev-cli": ("simplicio-dev-cli", "simplicio-py"),
        "simplicio-mapper": ("simplicio-mapper",),
    }.get(name, (name,))
    identity_ok = any(stem in path_stem for stem in expected_stems)
    return {
        "name": name,
        "command": command,
        "identity": str(result.get("identity") or ""),
        "path": resolved_path,
        "identity_ok": identity_ok,
        "version": _version_text(parsed),
        "minimum_version": _version_text(minimum),
        "version_ok": parsed >= tuple(minimum),
        "returncode": int(result.get("returncode", 1)),
        "required_capabilities": required_list,
        "missing_capabilities": missing,
        "capabilities_ok": not missing,
        "error": str(result.get("error") or ""),
    }


def _probe_component(name: str, command: str, cwd: Path, version_args: Sequence[str],
                     help_args: Sequence[str], required: Iterable[str]) -> Dict[str, Any]:
    path = shutil.which(command)
    base: Dict[str, Any] = {"identity": name, "path": path or "", "returncode": 1}
    if not path:
        base["error"] = "command not found"
        return _tool_report(name, command, MINIMUMS[name], base, required)
    try:
        # Use the resolved path, not the bare name.  Windows may have both a
        # ``simplicio.exe`` (legacy Python shim) and the canonical ``simplicio.cmd``
        # runtime on PATH; resolving once prevents PATH/PATHEXT from silently
        # probing the wrong identity.
        executable = path or command
        version = _run([executable, *version_args], cwd)
        help_result = _run([executable, *help_args], cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        base["error"] = f"probe failed: {exc}"
        return _tool_report(name, command, MINIMUMS[name], base, required)
    base.update({
        "version_text": version.stdout.strip() or version.stderr.strip(),
        "surface": (help_result.stdout or "") + "\n" + (help_result.stderr or ""),
        "returncode": 0 if version.returncode == 0 and help_result.returncode == 0 else 1,
        "error": (version.stderr or help_result.stderr or "").strip(),
    })
    return _tool_report(name, command, MINIMUMS[name], base, required)


def _probe_runtime(cwd: Path) -> Dict[str, Any]:
    command = "simplicio"
    path = shutil.which(command)
    base: Dict[str, Any] = {"identity": "simplicio-runtime", "path": path or "", "returncode": 1}
    if not path:
        base["error"] = "command not found"
        return _tool_report("simplicio-runtime", command, MINIMUMS["simplicio-runtime"], base)
    try:
        result = _run([path, "contracts", "smoke", "--json"], cwd, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        base["error"] = f"probe failed: {exc}"
        return _tool_report("simplicio-runtime", command, MINIMUMS["simplicio-runtime"], base)
    payload = _last_json(result.stdout)
    base.update({
        "version_text": str(payload.get("version") or ""),
        "returncode": result.returncode,
        "runtime_status": payload.get("status", "unknown"),
        "schema": payload.get("standard_io", ""),
        "error": (result.stderr or "").strip(),
    })
    report = _tool_report("simplicio-runtime", command, MINIMUMS["simplicio-runtime"], base)
    report["runtime_contract_ok"] = payload.get("standard_io") == "simplicio.io/v1" and payload.get("status") == "passed"
    report["version_ok"] = report["version_ok"] and bool(payload.get("version"))
    return report


def build_report(cwd: Path) -> Dict[str, Any]:
    _emit_progress("begin", detail="operadores: verificação/atualização")
    mapper = _probe_component("simplicio-mapper", "simplicio-mapper", cwd,
                              ("--version", "--json"), ("--help",), MAPPER_CAPABILITIES)
    devcli = _probe_component("simplicio-dev-cli", "simplicio-dev-cli", cwd,
                              ("--version", "--json"), ("edit", "--help"), DEVCLI_CAPABILITIES)
    runtime = _probe_runtime(cwd)
    runtime_available = (
        bool(runtime.get("identity_ok"))
        and bool(runtime.get("version_ok"))
        and bool(runtime.get("runtime_contract_ok"))
        and int(runtime.get("returncode", 1)) == 0
    )
    runtime["required"] = False
    components = [mapper, devcli, runtime]
    ready = all(
        bool(item.get("identity_ok")) and bool(item.get("version_ok")) and bool(item.get("capabilities_ok", True))
        and int(item.get("returncode", 1)) == 0
        for item in (mapper, devcli)
    )
    degraded = []
    if not runtime_available:
        degraded.append("runtime-integration")
    if ready:
        detail = "; ".join("%s %s" % (item["name"], item["version"]) for item in components)
        if not runtime_available:
            detail += "; simplicio-runtime unavailable (runtime integrations skipped)"
        _emit_progress("end", outcome="pass", detail=detail)
    else:
        missing = [item["name"] for item in components
                  if not (item.get("identity_ok") and item.get("version_ok"))]
        _emit_progress("blocked", outcome="blocked",
                       detail="missing operator %s" % (", ".join(missing) or "unknown"))
    return {
        "schema": SCHEMA,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repo": str(cwd),
        "ready": ready,
        "status": "READY" if ready else "BLOCKED",
        "components": components,
        "runtime_available": runtime_available,
        "degraded_features": degraded,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simplicio-preflight")
    parser.add_argument("--repo", default=".", help="repository to probe")
    parser.add_argument("--json", action="store_true", help="emit the machine-readable receipt")
    args = parser.parse_args(argv)
    report = build_report(Path(args.repo).resolve())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"simplicio preflight: {report['status']}")
        for item in report["components"]:
            print(f"- {item['name']}: {item['version']} (min {item['minimum_version']})")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
