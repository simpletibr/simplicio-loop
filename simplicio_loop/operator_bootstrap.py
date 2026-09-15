"""Bounded recovery for missing/incompatible Simplicio operators.

The loop is allowed to repair only its two required operator binaries.  Their
two distributions are requested directly: ``simplicio-cli`` exposes
``simplicio-dev-cli`` and ``simplicio-mapper`` exposes the survey binary.
Every attempt is persisted in the run directory and a run may perform at most
one networked install.
"""
from __future__ import annotations

import json
import os
import shutil
import site
import subprocess
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

SCHEMA = "simplicio.operator-bootstrap/v1"
# Unpinned + --upgrade in _pip_commands → always the latest published release.
# Floors live only in pyproject for install-time resolution; bootstrap upgrades freely.
PACKAGE_SPECS = (
    "simplicio-cli",
    "simplicio-mapper",
    "simplicio-fast",
    "simplicio-loop",
)
REQUIRED_BINARIES = ("simplicio-mapper", "simplicio-dev-cli", "simplicio-fast")
RECEIPT_NAME = "operator-bootstrap.json"
AUTO_BOOTSTRAP_ENV = "SIMPLICIO_LOOP_AUTO_BOOTSTRAP_OPERATORS"
FALSE_VALUES = frozenset(("0", "false", "no", "off", "disabled"))


class OperatorBootstrapError(RuntimeError):
    """Raised after the bounded bootstrap cannot make both operators available."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_bootstrap_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(AUTO_BOOTSTRAP_ENV, "")).strip().lower()
    return raw not in FALSE_VALUES


def _missing_binaries(binaries: Sequence[str] = REQUIRED_BINARIES) -> List[str]:
    return [name for name in binaries if shutil.which(name) is None]


def _candidate_script_dirs() -> List[str]:
    candidates = [
        str(Path(sys.executable).resolve().parent),
        str(sysconfig.get_path("scripts") or ""),
        str(Path(site.USER_BASE) / ("Scripts" if os.name == "nt" else "bin")),
    ]
    out: List[str] = []
    for candidate in candidates:
        if candidate and candidate not in out and Path(candidate).is_dir():
            out.append(candidate)
    return out


def _refresh_process_path() -> None:
    current = os.environ.get("PATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    additions = [path for path in _candidate_script_dirs() if path not in parts]
    if additions:
        os.environ["PATH"] = os.pathsep.join(additions + parts)


def _redact(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    for marker in ("pypi-", "ghp_", "github_pat_"):
        start = 0
        while True:
            index = value.find(marker, start)
            if index < 0:
                break
            end = index
            while end < len(value) and not value[end].isspace():
                end += 1
            value = value[:index] + "[REDACTED]" + value[end:]
            start = index + len("[REDACTED]")
    return value[-limit:]


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)


def _load_receipt(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _pip_commands(package_specs: Sequence[str]) -> Iterable[List[str]]:
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
    ]
    yield base + list(package_specs)
    yield base + ["--user"] + list(package_specs)


def ensure_operators(
    run_dir: str | Path,
    *,
    force: bool = False,
    env: Optional[Mapping[str, str]] = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Dict[str, Any]:
    """Install/upgrade the supported operator package once, then verify both bins.

    A prior receipt makes repeated calls deterministic.  Successful receipts are
    reusable; failed attempts are not retried within the same run.
    """
    root = Path(run_dir)
    receipt_path = root / RECEIPT_NAME
    missing_before = _missing_binaries()
    if not force and not missing_before:
        receipt = {
            "schema": SCHEMA,
            "status": "already_available",
            "attempted": False,
            "packages": list(PACKAGE_SPECS),
            "missing_before": [],
            "missing_after": [],
            "resolved": {name: shutil.which(name) or "" for name in REQUIRED_BINARIES},
            "checked_at": _now(),
        }
        _write_receipt(receipt_path, receipt)
        return receipt

    previous = _load_receipt(receipt_path)
    if previous.get("attempted"):
        if previous.get("status") == "installed":
            _refresh_process_path()
            missing_after = _missing_binaries()
            if not missing_after:
                return previous
        raise OperatorBootstrapError(
            "operator bootstrap already attempted for this run: "
            + str(previous.get("detail") or previous.get("status") or "failed")
        )

    if not auto_bootstrap_enabled(env):
        receipt = {
            "schema": SCHEMA,
            "status": "disabled",
            "attempted": False,
            "packages": list(PACKAGE_SPECS),
            "missing_before": missing_before,
            "missing_after": missing_before,
            "detail": f"{AUTO_BOOTSTRAP_ENV}=disabled",
            "checked_at": _now(),
        }
        _write_receipt(receipt_path, receipt)
        raise OperatorBootstrapError(
            "automatic operator bootstrap is disabled; install "
            + " ".join(PACKAGE_SPECS)
        )

    attempts: List[Dict[str, Any]] = []
    installed = False
    for argv in _pip_commands(PACKAGE_SPECS):
        try:
            result = run(
                argv,
                capture_output=True,
                text=True,
                timeout=180,
            )
            attempts.append({
                "mode": "user" if "--user" in argv else "environment",
                "returncode": result.returncode,
                "stdout": _redact(result.stdout),
                "stderr": _redact(result.stderr),
            })
            if result.returncode == 0:
                installed = True
                break
        except (OSError, subprocess.SubprocessError) as exc:
            attempts.append({
                "mode": "user" if "--user" in argv else "environment",
                "returncode": None,
                "stdout": "",
                "stderr": _redact(str(exc)),
            })

    _refresh_process_path()
    missing_after = _missing_binaries()
    status = "installed" if installed and not missing_after else "failed"
    detail = (
        "both required operator binaries resolved"
        if status == "installed"
        else "missing after install: " + ", ".join(missing_after or REQUIRED_BINARIES)
    )
    receipt = {
        "schema": SCHEMA,
        "status": status,
        "attempted": True,
        "packages": list(PACKAGE_SPECS),
        "missing_before": missing_before,
        "missing_after": missing_after,
        "resolved": {name: shutil.which(name) or "" for name in REQUIRED_BINARIES},
        "attempts": attempts,
        "detail": detail,
        "checked_at": _now(),
    }
    _write_receipt(receipt_path, receipt)
    if status != "installed":
        raise OperatorBootstrapError("operator bootstrap failed: " + detail)
    return receipt


__all__ = [
    "AUTO_BOOTSTRAP_ENV",
    "OperatorBootstrapError",
    "PACKAGE_SPECS",
    "REQUIRED_BINARIES",
    "SCHEMA",
    "auto_bootstrap_enabled",
    "ensure_operators",
]
