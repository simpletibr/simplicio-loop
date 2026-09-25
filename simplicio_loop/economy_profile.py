"""Fastest + cheapest operational profile for the Simplicio stack.

Goals (operator contract):
- **Tokens:** mapper handoff / Runtime MCP first; no host bulk-read; Fast hot path.
- **CPU/RAM:** bounded workers from host CPU count; leave headroom for OS + Runtime Tokio.
- **Parallel:** Prism slots + ``SIMPLICIO_LOOP_AUTO_FAN_OUT`` (worktree lanes) + asyncio
  supervisor concurrency. Runtime uses Tokio natively when ``simplicio`` is bound.

This module only *recommends and applies env*. Logical parallelism is unbounded;
physical execution still requires measured capacity and lease/claim isolation
(no double-writers).
"""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

SCHEMA = "simplicio.economy-parallel-profile/v1"
PROFILE_NAME = "economy-parallel"
DEFAULT_PRISM_BATCH_SIZE = 10
MIN_PRISM_BATCH_SIZE = 10


def resolve_prism_batch_size(requested: Optional[int] = None, *, env: Optional[Mapping[str, str]] = None) -> int:
    """Resolve Prism wave width (default/minimum 10, with no logical upper bound)."""
    source = os.environ if env is None else env
    raw = requested if requested is not None else source.get("SIMPLICIO_PRISM_BATCH_SIZE", DEFAULT_PRISM_BATCH_SIZE)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("SIMPLICIO_PRISM_BATCH_SIZE must be an integer") from exc
    if value < MIN_PRISM_BATCH_SIZE:
        raise ValueError(f"Prism batch size must be at least {MIN_PRISM_BATCH_SIZE}")
    return value


def prism_is_eligible(item_count: int, *, explicit_serial: bool = False) -> dict[str, object]:
    """Route 1-3 tasks to direct parallelism and larger work to Prism."""
    count = int(item_count)
    if explicit_serial:
        return {"eligible": False, "reason_code": "explicit_serial"}
    if count <= 3:
        return {
            "eligible": False,
            "reason_code": "direct_parallelism" if count > 1 else "single_item",
            "parallelism": "direct",
        }
    return {
        "eligible": True,
        "reason_code": "prism_above_three_tasks",
        "parallelism": "prism",
    }


def prism_batches(items, batch_size: Optional[int] = None):
    """Yield frozen waves; the next wave starts only after the prior one reconciles."""
    values = list(items)
    width = resolve_prism_batch_size(batch_size)
    return [values[offset:offset + width] for offset in range(0, len(values), width)]


# Opt-out of always-on economy defaults (legacy serial / heavy ceremony).
DISABLE_ENV = "SIMPLICIO_ECONOMY_PARALLEL"
_FALSE = frozenset({"0", "false", "no", "off", "disabled", "legacy", "serial"})


def economy_parallel_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    source = os.environ if env is None else env
    raw = str(source.get(DISABLE_ENV, "1")).strip().lower()
    return raw not in _FALSE


def _cpu_count() -> int:
    return max(1, int(os.cpu_count() or 4))


def _ram_gb() -> tuple[Optional[float], Optional[float]]:
    """Best-effort (total_gb, available_gb) from psutil or /proc/meminfo."""
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        return (
            float(vm.total) / (1024.0**3),
            float(vm.available) / (1024.0**3),
        )
    except Exception:
        pass
    try:
        path = Path("/proc/meminfo")
        if path.is_file():
            total_kb = avail_kb = None
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MemTotal:"):
                    total_kb = float(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    avail_kb = float(line.split()[1])
            total = (total_kb / (1024.0 * 1024.0)) if total_kb else None
            avail = (avail_kb / (1024.0 * 1024.0)) if avail_kb else None
            return total, avail
    except Exception:
        pass
    return None, None


def _available_ram_gb() -> Optional[float]:
    """Backward-compatible helper (available only)."""
    _total, avail = _ram_gb()
    return avail


def recommend_operator_workers(cpu: Optional[int] = None) -> int:
    """Operator pool sized to the host: use all logical CPUs (min 2).

    Big machines are no longer clamped at 12 — maximise what the box can run.
    """
    n = _cpu_count() if cpu is None else max(1, int(cpu))
    return max(2, n)


def recommend_prism_slots(cpu: Optional[int] = None) -> int:
    """Recommend a physical Prism worker width for this machine.

    Policy:
    - Start from logical CPU count (leave 1 core for OS + Runtime Tokio when
      cpu >= 3; otherwise use all cores, floor 2).
    - Cap by available RAM (~1.25 GiB per isolated Prism slot/worktree) when
      measurable — never oversubscribe memory into thrash.
    - No artificial 6/8 ceiling on large hosts.
    - Env ``SIMPLICIO_PRISM_SLOTS`` is *not* read here; callers that want an
      explicit override pass ``prism_slots=`` into ``economy_parallel_env``.
    """
    n = _cpu_count() if cpu is None else max(1, int(cpu))
    # Physical worker recommendation from CPU: leave one core free when possible.
    cpu_slots = max(2, n - 1) if n >= 3 else max(2, n)

    total_gb, avail_gb = _ram_gb()
    if total_gb is not None:
        # Machine capacity from total RAM: reserve 4 GiB for OS+Runtime+Fast;
        # ~1.0 GiB per Prism worktree/agent (isolated).
        capacity = max(0.0, float(total_gb) - 4.0)
        ram_slots = max(2, int(capacity / 1.0))
        slots = min(cpu_slots, ram_slots)
        # Emergency tighten only if free RAM is critically low (avoid thrash)
        if avail_gb is not None and float(avail_gb) < 2.5:
            slots = max(2, min(slots, int(float(avail_gb) / 1.25)))
    else:
        slots = cpu_slots

    return max(2, int(slots))


def recommend_async_concurrency(cpu: Optional[int] = None) -> int:
    """asyncio IO supervisor concurrency (Python "Tokio")."""
    workers = recommend_operator_workers(cpu)
    # Match host width; soft ceiling only for pathological cpu_count reports
    return max(4, min(max(16, workers + 4), workers + 8))


def economy_parallel_env(
    *,
    env: Optional[Mapping[str, str]] = None,
    runtime_operational: Optional[bool] = None,
    prism_slots: Optional[int] = None,
    operator_workers: Optional[int] = None,
    prism_batch_size: Optional[int] = None,
) -> dict[str, str]:
    """Return env map for fastest token path + parallel drain/batch.

    When ``runtime_operational`` is None, probes PATH for the native Runtime binary.
    """
    if runtime_operational is None:
        try:
            from .strict_mode import runtime_status

            runtime_operational = bool(runtime_status(env).get("operational"))
        except Exception:
            runtime_operational = False

    workers = (
        int(operator_workers)
        if operator_workers is not None
        else recommend_operator_workers()
    )
    slots = int(prism_slots) if prism_slots is not None else recommend_prism_slots()
    batch_size = resolve_prism_batch_size(prism_batch_size, env=env)
    async_n = recommend_async_concurrency()

    out: dict[str, str] = {
        # Core loop + safety floor (unchanged)
        "SIMPLICIO_LOOP": "1",
        "SIMPLICIO_LOOP_STRICT": "1",
        "SIMPLICIO_REQUIRE_MUTATION_AUTHORITY": "1",
        "SIMPLICIO_LOOP_AUTO_PLANNING_RECEIPT": "1",
        "SIMPLICIO_LOOP_FORBID_HAND_EDIT": "1",
        # Adaptive: runtime-backed when Runtime is up, standalone when it isn't.
        "SIMPLICIO_LOOP_REQUIRE_RUNTIME": "auto",
        "SIMPLICIO_EXECUTION_PROFILE": "auto",
        # Fast hot path (mmap / understand-plan-apply)
        "SIMPLICIO_FAST_MODE": "required",
        # Always latest packages on preflight
        "SIMPLICIO_OPERATOR_ALWAYS_LATEST": "1",
        # Parallel: worktree fan-out + worker pool + Prism width
        "SIMPLICIO_LOOP_AUTO_FAN_OUT": "1",
        "SIMPLICIO_LOOP_OPERATOR_WORKERS": str(workers),
        "SIMPLICIO_PRISM_SLOTS": str(slots),
        "SIMPLICIO_PRISM_BATCH_SIZE": str(batch_size),
        "SIMPLICIO_ASYNC_IO_MAX_CONCURRENCY": str(async_n),
        # Profile marker
        "SIMPLICIO_ECONOMY_PARALLEL": "1",
        "SIMPLICIO_ECONOMY_PROFILE": PROFILE_NAME,
    }
    # Token economy MCP layer follows the measured Runtime state: bind it when
    # Runtime is operational, degrade (never fake) when it is not.
    mcp_flag = "1" if runtime_operational else "0"
    out["SIMPLICIO_REQUIRE_MCP"] = mcp_flag
    out["SIMPLICIO_MCP_FORCE"] = mcp_flag
    return out


def llm_max_speed_orientation_contract() -> dict[str, Any]:
    """Return the native, machine-readable host orientation contract."""
    return {
        "schema": "simplicio.llm-max-speed-orientation/v1",
        "canonical_doc": "docs/LLM_MAX_SPEED_ORIENTATION.md",
        "runtime_twin": "simplicio-runtime/docs/LLM_MAX_SPEED_ORIENTATION.md",
        "skill_block": "plugin/skills/simplicio-loop/SKILL.md <!-- SIMPLICIO-LLM-ORIENTATION -->",
        "law": "act>narrate; Runtime loop decide; Mapper→Fast→dev-cli; 1-3 direct / Prism>3; lease isolation; smallest AC gate; MEASURED only",
        "control_plane": {
            "authority": "simplicio-runtime",
            "command": "simplicio loop decide --task … --repo . --json",
            "host_may_override": False,
        },
        "context_route": {
            "primary": "simplicio-fast",
            "fallback": "simplicio-mapper",
            "bounded": True,
            "local_llm": False,
        },
        "fallback_policy": {
            "auto": "mapper_read_only",
            "required_fast": "blocked",
            "explicit_rust": "blocked",
        },
        "mutation_boundary": {
            "authorized": False,
            "next_surfaces": ["simplicio-dev-cli task", "simplicio edit --plan"],
        },
        "receipt_schema": "simplicio.loop-orient-receipt/v1",
        "message_cadence": ["DONE", "NEXT", "BLOCKED"],
        "forbid": [
            "full-repo fmt/test residual thrash",
            "3-reviewer panels on metadata-only",
            "hand-edit under STRICT",
            "peer /simplicio-loop bypass when Runtime owns activation",
            "N full agents on one dirty tree without worktrees",
        ],
    }


def _resolve_runtime_operational(
    env: Optional[Mapping[str, str]], runtime_operational: Optional[bool]
) -> bool:
    if runtime_operational is not None:
        return bool(runtime_operational)
    try:
        from .strict_mode import runtime_status

        return bool(runtime_status(env).get("operational"))
    except Exception:
        return False


def profile_status(
    env: Optional[Mapping[str, str]] = None,
    *,
    runtime_operational: Optional[bool] = None,
) -> dict[str, Any]:
    resolved_runtime_operational = _resolve_runtime_operational(env, runtime_operational)
    recommended = economy_parallel_env(
        env=env, runtime_operational=resolved_runtime_operational
    )
    source = os.environ if env is None else env
    applied = {
        key: str(source.get(key, ""))
        for key in recommended
        if str(source.get(key, "")).strip() != ""
    }
    missing = [k for k, v in recommended.items() if str(source.get(k, "")).strip() != v]
    execution_profile = "runtime-backed" if resolved_runtime_operational else "standalone"
    note = None if resolved_runtime_operational else "UNVERIFIED|runtime_unavailable"
    return {
        "schema": SCHEMA,
        "profile": PROFILE_NAME,
        "enabled": economy_parallel_enabled(env),
        "cpu_count": _cpu_count(),
        "recommended": recommended,
        "applied": applied,
        "drift_keys": missing,
        "aligned": len(missing) == 0,
        "runtime_operational": resolved_runtime_operational,
        "execution_profile": execution_profile,
        "note": note,
        "backends": {
            "runtime_tokio": "native when simplicio-runtime bound",
            "python_asyncio": "async_io_supervisor + async_bounded_queue + batch fan-out",
            "prism": "arm_drain_prism + SIMPLICIO_PRISM_SLOTS + lease isolation",
        },
        "hot_path": [
            "simplicio loop decide --task \"…\" --repo . --json",
            "simplicio-loop preflight --strict --json",
            "simplicio-mapper scan . --await --json",
            "simplicio-mapper handoff . --for-llm toon --await",
            "simplicio-fast understand|plan|apply (when operational)",
            "simplicio-loop batch (AUTO_FAN_OUT worktrees) or arm_drain_prism --slots 0 --batch-size N",
            "mutate: simplicio-dev-cli task (STRICT)",
        ],
        # Always-on LLM orientation for hosts (max safe speed)
        "llm_orientation": llm_max_speed_orientation_contract(),
    }


def apply_to_environ(
    target: MutableMapping[str, str],
    *,
    env: Optional[Mapping[str, str]] = None,
    runtime_operational: Optional[bool] = None,
) -> dict[str, str]:
    """Mutate a mapping (e.g. os.environ) with the profile; return applied pairs."""
    recommended = economy_parallel_env(
        env=env, runtime_operational=runtime_operational
    )
    for key, value in recommended.items():
        target[key] = value
    return recommended


def user_env_paths() -> dict[str, Path]:
    home = Path.home()
    root = home / ".simplicio"
    return {
        "dir": root,
        "json": root / "economy-parallel-env.json",
        "ps1": root / "economy-parallel-env.ps1",
        "sh": root / "economy-parallel-env.sh",
    }


def persist_user_profile(
    *,
    runtime_operational: Optional[bool] = None,
    set_windows_user_env: bool = True,
) -> dict[str, Any]:
    """Write ~/.simplicio/economy-parallel-env.* and optionally Windows User env."""
    resolved_runtime_operational = _resolve_runtime_operational(None, runtime_operational)
    recommended = economy_parallel_env(runtime_operational=resolved_runtime_operational)
    paths = user_env_paths()
    paths["dir"].mkdir(parents=True, exist_ok=True)
    paths["json"].write_text(
        json.dumps(
            {
                "schema": SCHEMA,
                "profile": PROFILE_NAME,
                "env": recommended,
                "platform": platform.system(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    # PowerShell
    ps_lines = [
        "# Simplicio economy-parallel profile — dot-source: . $HOME\\.simplicio\\economy-parallel-env.ps1",
        "$ErrorActionPreference = 'SilentlyContinue'",
    ]
    for key, value in sorted(recommended.items()):
        ps_lines.append(f"$env:{key} = '{value}'")
    paths["ps1"].write_text("\n".join(ps_lines) + "\n", encoding="utf-8", newline="\n")
    # POSIX
    sh_lines = [
        "# Simplicio economy-parallel profile — source ~/.simplicio/economy-parallel-env.sh",
    ]
    for key, value in sorted(recommended.items()):
        sh_lines.append(f'export {key}="{value}"')
    paths["sh"].write_text("\n".join(sh_lines) + "\n", encoding="utf-8", newline="\n")

    windows_set: list[str] = []
    if set_windows_user_env and sys.platform == "win32":
        try:
            import winreg  # type: ignore

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Environment",
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                for name, value in recommended.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                    windows_set.append(name)
                    os.environ[name] = value
        except OSError as exc:
            return {
                "schema": SCHEMA,
                "ok": False,
                "error": f"windows_user_env_failed: {exc}",
                "paths": {k: str(v) for k, v in paths.items()},
                "env": recommended,
            }
    else:
        # still apply to this process
        for name, value in recommended.items():
            os.environ[name] = value

    note = "New shells pick up User env after restart; this process is updated in-place."
    if not resolved_runtime_operational:
        note = f"{note} UNVERIFIED|runtime_unavailable"
    return {
        "schema": SCHEMA,
        "ok": True,
        "profile": PROFILE_NAME,
        "paths": {k: str(v) for k, v in paths.items()},
        "env": recommended,
        "windows_user_env_keys": windows_set,
        "runtime_operational": resolved_runtime_operational,
        "execution_profile": "runtime-backed" if resolved_runtime_operational else "standalone",
        "note": note,
    }


def render_shell_exports(env_map: Mapping[str, str], *, shell: str = "auto") -> str:
    kind = shell
    if kind == "auto":
        kind = "ps1" if sys.platform == "win32" else "sh"
    if kind in {"ps1", "powershell", "pwsh"}:
        return "\n".join(f"$env:{k} = '{v}'" for k, v in sorted(env_map.items())) + "\n"
    return "\n".join(f'export {k}="{v}"' for k, v in sorted(env_map.items())) + "\n"


__all__ = [
    "SCHEMA",
    "PROFILE_NAME",
    "economy_parallel_enabled",
    "economy_parallel_env",
    "llm_max_speed_orientation_contract",
    "profile_status",
    "apply_to_environ",
    "persist_user_profile",
    "render_shell_exports",
    "recommend_operator_workers",
    "recommend_prism_slots",
    "recommend_async_concurrency",
    "DEFAULT_PRISM_BATCH_SIZE",
    "MAX_PRISM_BATCH_SIZE",
    "resolve_prism_batch_size",
    "prism_is_eligible",
    "prism_batches",
]
