"""Mapper, devcli and operator environment, timeouts and inspection helpers for the runner (#1818 split of runner_core).

Functions moved verbatim from `simplicio_loop/runner_core.py` (#1818).
`runner_core` re-exports them, so import paths and patch targets on `runner_core` keep working.
"""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

from .store_adapter import StorageRoute, StoreAdapterError


def _devcli_env(repo_path: Path, base_env: Dict[str, str] | None = None) -> Dict[str, str]:
    env = dict(base_env or os.environ)
    repo_str = str(repo_path)
    current = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = repo_str if not current else f"{repo_str}{os.pathsep}{current}"
    selected_devcli = _runner_core._devcli_command_path()
    if selected_devcli != "simplicio-dev-cli":
        env["PATH"] = f"{Path(selected_devcli).resolve().parent}{os.pathsep}{env.get('PATH', '')}"
    # The external provider worker receives credentials through its own
    # allow-listed in-process boundary. Deterministic Dev CLI must never receive
    # provider credentials, even when the parent shell has them set.
    for key in _PROVIDER_SECRET_ENV:
        env.pop(key, None)
    env["SIMPLICIO_LOCAL_LLM_DISABLED"] = "1"
    if _degraded_mapper_fallback_enabled():
        env["SIMPLICIO_ALLOW_DEGRADED_MAPPER"] = "1"
    # The Loop's standalone operator preflight is a context/target gate;
    # it must not invoke the deterministic Dev CLI provider.
    env["SIMPLICIO_STANDALONE_PREFLIGHT"] = "1"
    model = env.get("SIMPLICIO_MODEL", "").strip().casefold()
    if model.startswith(("local/", "llama", "ollama")):
        env.pop("SIMPLICIO_MODEL", None)
    return env


def _devcli_has_mapper_manifest(command: str) -> bool:
    try:
        executable = Path(command).resolve()
        first_line = executable.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
        interpreter = first_line[2:].strip() if first_line.startswith("#!") else ""
        if interpreter.startswith("/usr/bin/env "):
            interpreter = shutil.which(interpreter.rsplit(" ", 1)[-1]) or ""
        if not interpreter:
            return False
        probe = subprocess.run(
            [interpreter, "-c",
             "import importlib.resources; print(int(importlib.resources.files('simplicio_mapper').joinpath('contracts/context-snapshot/v1/contract-manifest.json').is_file()))"],
            capture_output=True, text=True, timeout=3, check=False,
            env=_subprocess_env(),
        )
        return probe.returncode == 0 and probe.stdout.strip() == "1"
    except (OSError, IndexError, subprocess.SubprocessError):
        return False


def _devcli_command_path() -> str:
    explicit = os.environ.get("SIMPLICIO_DEV_CLI_BIN", "").strip()
    if explicit:
        return explicit
    current = shutil.which("simplicio-dev-cli")
    candidates = []
    if current:
        candidates.append(current)
    pipx_root = Path.home() / ".local" / "pipx" / "venvs"
    if pipx_root.is_dir():
        candidates.extend(str(path) for path in sorted(pipx_root.glob("*/bin/simplicio-dev-cli")))
    compatible = next((path for path in candidates if _devcli_has_mapper_manifest(path)), None)
    return compatible or current or "simplicio-dev-cli"


def _devcli_cmd(repo_path: Path, *args: str) -> List[str]:
    if (repo_path / "simplicio" / "cli.py").exists():
        base = [sys.executable, "-m", "simplicio.cli", *args]
    else:
        base = ["simplicio-dev-cli", *args]
    return base


def _mapper_timeout_seconds() -> int:
    """Return the bounded wait used by every Mapper deep-pass command.

    The same runaway ceiling as the mapper index (300 s). Operators can raise it
    with SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC. A detached index must not be awaited
    for an hour.
    """
    default = 300
    raw = os.environ.get("SIMPLICIO_LOOP_MAPPER_TIMEOUT_SEC", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def _mapper_supports_command(preflight: Mapping[str, Any], command: str) -> bool:
    """Detect an optional Mapper command from its measured help surface."""
    help_stdout = str(preflight.get("help_stdout") or "")
    return any(
        line.strip().startswith(command + " ") or line.strip() == command
        for line in help_stdout.splitlines()
    )


def _mapper_inspection_is_fresh(result: subprocess.CompletedProcess[str]) -> bool:
    """Return whether Mapper's persisted inspection proves a usable fresh index."""
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return (
        isinstance(status, Mapping)
        and status.get("artifacts_present") is True
        and status.get("fresh") is True
    )


def _mapper_inspection_reports_stale(result: subprocess.CompletedProcess[str]) -> bool:
    """Return true only when Mapper explicitly reports a stale/incomplete index."""
    try:
        payload = json.loads(result.stdout or "")
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return (
        isinstance(status, Mapping)
        and (
            status.get("artifacts_present") is not True
            or status.get("fresh") is not True
        )
    )


def _degraded_mapper_fallback_enabled() -> bool:
    """Allow explicit-target local work to continue when deep mapping is unavailable."""
    raw = os.environ.get("SIMPLICIO_LOOP_ALLOW_DEGRADED_MAPPER", "").strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off", "disabled"}
    return True


def _degraded_mapper_payload(
    repo_path: Path,
    before: Mapping[str, Any],
    mapper_preflight: Mapping[str, Any],
    scan: Any,
    inspect: Any,
    snapshot: Any,
    handoff: Any,
    target_hint: str,
    ecc_admission: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build an explicitly UNVERIFIED context for a bounded local retry.

    This is not a substitute for a Mapper receipt: the original command results remain
    persisted, the degraded marker is durable, and only targets resolved inside the
    repository are exposed to planning. Without a target hint, the context remains
    empty and planning fails closed.
    """
    target = str(target_hint or "").strip().replace("\\", "/")
    files: List[Dict[str, Any]] = []
    if target:
        candidate = (repo_path / target).resolve()
        try:
            candidate.relative_to(repo_path.resolve())
        except (OSError, ValueError):
            target = ""
        else:
            if candidate.is_file() or candidate.is_dir():
                files.append({"path": target, "source": "explicit_task_target"})
            else:
                target = ""
    # Without an explicit target, keep the context empty and fail closed;
    # repository-wide inference can authorize an unrelated file.
    pack_seed = {
        "repo_state": dict(before),
        "target": target,
        "files": files,
        "reason": "mapper_deep_pass_unavailable",
    }
    pack_hash = hashlib.sha256(
        json.dumps(pack_seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    degraded_handoff = {
        "ready": bool(files),
        "context_pack": {
            "schema": "simplicio.context-pack/v1",
            "pack_hash": pack_hash,
            "files": files,
            "fidelity": {"gate": "degraded_local", "status": "UNVERIFIED"},
            "source": "simplicio-loop-local-fallback",
        },
        "degraded_local": True,
    }
    return {
        "scan": {
            "returncode": scan.returncode,
            "stdout": json.loads(scan.stdout) if scan.stdout.strip() else {},
            "stderr": (scan.stderr or "").strip(),
        },
        "inspect": {
            "returncode": inspect.returncode,
            "stdout": json.loads(inspect.stdout) if inspect.stdout.strip() else {},
            "stderr": (inspect.stderr or "").strip(),
        },
        "snapshot": {
            "returncode": snapshot.returncode,
            "stdout": json.loads(snapshot.stdout) if snapshot.stdout.strip() else {},
            "stderr": (snapshot.stderr or "").strip(),
        },
        "handoff": {
            "returncode": 0,
            "stdout": degraded_handoff,
            "stderr": (handoff.stderr or "").strip(),
        },
        "handoff_original": {
            "returncode": handoff.returncode,
            "stdout": json.loads(handoff.stdout) if handoff.stdout.strip() else {},
            "stderr": (handoff.stderr or "").strip(),
        },
        "generated_at": _runner_core._now(),
        "repo_state_before": dict(before),
        "repo_state_after": _runner_core._repo_fingerprint(repo_path),
        "mapper_preflight": dict(mapper_preflight),
        "ecc_admission": dict(ecc_admission or {}),
        "degraded_local": True,
        "degraded_reason_code": "mapper_deep_pass_unavailable",
        "evidence_status": "UNVERIFIED",
    }


def _mapper_journal_enabled(storage_route: StorageRoute | str | None = None) -> bool:
    raw = _runner_core._storage_route_requested() if storage_route is None else storage_route
    try:
        return StorageRoute(raw) == StorageRoute.MAPPER
    except ValueError as error:
        raise StoreAdapterError("STORAGE_ROUTE_INVALID") from error


def _operator_env() -> Dict[str, str]:
    env = _subprocess_env()
    env.setdefault(
        "SIMPLICIO_MODEL",
        os.environ.get("SIMPLICIO_LOOP_OPERATOR_MODEL", "codex-cli/gpt-5.4"),
    )
    env.setdefault(
        "SIMPLICIO_CODEX_EFFORT",
        os.environ.get("SIMPLICIO_LOOP_OPERATOR_EFFORT", "medium"),
    )
    loop_test_cmd = os.environ.get("SIMPLICIO_LOOP_TEST_CMD", "").strip()
    if loop_test_cmd and not env.get("SIMPLICIO_TEST_CMD", "").strip():
        env["SIMPLICIO_TEST_CMD"] = loop_test_cmd
    return env


def _operator_timeout(kind: str) -> int:
    default = 60 if kind == "dry_run" else 600
    raw = os.environ.get("SIMPLICIO_LOOP_OPERATOR_TIMEOUT_SEC", "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(30, value)


def _execution_profile() -> str:
    """Return the execution profile. Always ``standalone`` -- there is no
    Runtime/MCP backend in this stack. ``SIMPLICIO_EXECUTION_PROFILE`` may
    only be explicitly set to ``standalone``; any other value fails closed.
    """
    raw = os.environ.get("SIMPLICIO_EXECUTION_PROFILE", "").strip().lower()
    if raw in {"", "standalone", "auto"}:
        return "standalone"
    raise RuntimeError("SIMPLICIO_EXECUTION_PROFILE must be standalone")

# Late imports (#1818): bound after this module's definitions so the runner modules can import each other.
from .runner_core import (_PROVIDER_SECRET_ENV, _subprocess_env)  # noqa: E402
from . import runner_core as _runner_core  # noqa: E402
