"""Fastest + cheapest operational profile for the Simplicio stack.

Goals (operator contract):
- **Tokens:** mapper handoff first; no host bulk-read.
- **CPU/RAM:** bounded workers from host CPU count; leave headroom for the OS.
- **Parallel:** Prism slots + ``SIMPLICIO_LOOP_AUTO_FAN_OUT`` (worktree lanes) + asyncio
  supervisor concurrency.

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
        # Machine capacity from total RAM: reserve 4 GiB for the OS and operators;
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
    prism_slots: Optional[int] = None,
    operator_workers: Optional[int] = None,
    prism_batch_size: Optional[int] = None,
) -> dict[str, str]:
    """Return env map for fastest token path + parallel drain/batch."""
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
        "SIMPLICIO_EXECUTION_PROFILE": "standalone",
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
    return out


def llm_max_speed_orientation_contract() -> dict[str, Any]:
    """Return the native, machine-readable host orientation contract."""
    return {
        "schema": "simplicio.llm-max-speed-orientation/v1",
        "canonical_doc": "docs/LLM_MAX_SPEED_ORIENTATION.md",
        "skill_block": "plugin/skills/simplicio-loop/SKILL.md <!-- SIMPLICIO-LLM-ORIENTATION -->",
        "law": "act>narrate; Mapper→dev-cli; 1-3 direct / Prism>3; lease isolation; smallest AC gate; MEASURED only",
        "context_route": {
            "primary": "simplicio-mapper",
            "bounded": True,
            "local_llm": False,
        },
        "mutation_boundary": {
            "authorized": False,
            "next_surfaces": ["simplicio-dev-cli edit --plan --compile", "simplicio-dev-cli edit --plan --apply"],
        },
        "receipt_schema": "simplicio.loop-orient-receipt/v1",
        "message_cadence": ["DONE", "NEXT", "BLOCKED"],
        "forbid": [
            "full-repo fmt/test residual thrash",
            "3-reviewer panels on metadata-only",
            "hand-edit under STRICT",
            "N full agents on one dirty tree without worktrees",
        ],
    }


def _persisted_env_matches(recommended: Mapping[str, str]) -> bool:
    """True when ~/.simplicio-loop/economy-parallel-env.json already holds this profile."""
    try:
        raw = user_env_paths()["json"].read_text(encoding="utf-8")
        stored = json.loads(raw).get("env", {})
    except Exception:
        return False
    return all(str(stored.get(k, "")) == v for k, v in recommended.items())


def _drift_explanation(
    *, drift_keys: list[str], persisted_matches: bool
) -> dict[str, Any]:
    """Explain *why* drift exists: never applied vs. applied-but-not-loaded."""
    if not drift_keys:
        return {"reason_code": "aligned", "reason": "", "fix": ""}
    if not persisted_matches:
        return {
            "reason_code": "not_applied",
            "reason": "the economy profile has not been applied on this host "
            "(or was applied with different values)",
            "fix": "simplicio-loop economy apply",
        }
    if sys.platform == "win32":
        return {
            "reason_code": "applied_not_loaded",
            "reason": "the profile is persisted to the Windows User environment "
            "but this process started before that change took effect",
            "fix": "open a new shell/terminal (User env applies to new processes only)",
        }
    return {
        "reason_code": "applied_not_loaded",
        "reason": "the profile is persisted under ~/.simplicio-loop but this shell "
        "was not started after apply() wired the rc-file source line, or the "
        "active shell's rc file was not one of the ones apply() edited",
        "fix": f". {user_env_paths()['sh']}",
    }


def profile_status(
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, Any]:
    recommended = economy_parallel_env(env=env)
    source = os.environ if env is None else env
    applied = {
        key: str(source.get(key, ""))
        for key in recommended
        if str(source.get(key, "")).strip() != ""
    }
    missing = [k for k, v in recommended.items() if str(source.get(k, "")).strip() != v]
    execution_profile = "standalone"
    note = None
    drift_explanation = _drift_explanation(
        drift_keys=missing,
        persisted_matches=_persisted_env_matches(recommended),
    )
    return {
        "schema": SCHEMA,
        "profile": PROFILE_NAME,
        "enabled": economy_parallel_enabled(env),
        "cpu_count": _cpu_count(),
        "recommended": recommended,
        "applied": applied,
        "drift_keys": missing,
        "drift_reason": drift_explanation["reason_code"],
        "drift_explanation": drift_explanation["reason"],
        "drift_fix": drift_explanation["fix"],
        "aligned": len(missing) == 0,
        "execution_profile": execution_profile,
        "note": note,
        "backends": {
            "python_asyncio": "async_io_supervisor + async_bounded_queue + batch fan-out",
            "prism": "arm_drain_prism + SIMPLICIO_PRISM_SLOTS + lease isolation",
        },
        "hot_path": [
            "simplicio-loop preflight --strict --json",
            "simplicio-mapper scan . --await --json",
            "simplicio-mapper handoff . --for-llm toon --await",
            "simplicio-loop batch (AUTO_FAN_OUT worktrees) or arm_drain_prism --slots 0 --batch-size N",
            "mutate: simplicio-dev-cli edit --plan --apply (STRICT)",
        ],
        # Always-on LLM orientation for hosts (max safe speed)
        "llm_orientation": llm_max_speed_orientation_contract(),
    }


def apply_to_environ(
    target: MutableMapping[str, str],
    *,
    env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Mutate a mapping (e.g. os.environ) with the profile; return applied pairs."""
    recommended = economy_parallel_env(env=env)
    for key, value in recommended.items():
        target[key] = value
    return recommended


def user_env_paths() -> dict[str, Path]:
    home = Path.home()
    root = home / ".simplicio-loop"
    return {
        "dir": root,
        "json": root / "economy-parallel-env.json",
        "ps1": root / "economy-parallel-env.ps1",
        "sh": root / "economy-parallel-env.sh",
    }


_RC_MARK_BEGIN = "# >>> simplicio economy-parallel >>>"
_RC_MARK_END = "# <<< simplicio economy-parallel <<<"


def _posix_rc_candidates() -> list[Path]:
    """rc files a new POSIX login/interactive shell is likely to source.

    Prefers files that already exist (``.bashrc``/``.zshrc``); falls back to
    ``.profile`` (sourced by POSIX-compliant shells, incl. bash as a login
    shell) so a host with neither still gets one persisted mechanism.
    """
    home = Path.home()
    candidates = [home / ".bashrc", home / ".zshrc"]
    existing = [p for p in candidates if p.is_file()]
    return existing if existing else [home / ".profile"]

def _rc_source_block(sh_path: Path) -> str:
    return (
        f"{_RC_MARK_BEGIN}\n"
        f'[ -f "{sh_path}" ] && . "{sh_path}"\n'
        f"{_RC_MARK_END}\n"
    )


def _write_idempotent_rc_block(rc_path: Path, block: str) -> bool:
    """Insert/replace the guarded block in ``rc_path``. Returns True if changed."""
    existing = rc_path.read_text(encoding="utf-8") if rc_path.is_file() else ""
    if _RC_MARK_BEGIN in existing:
        start = existing.index(_RC_MARK_BEGIN)
        end_marker = existing.index(_RC_MARK_END, start) + len(_RC_MARK_END)
        # Consume a trailing newline after the end marker, if present.
        end = end_marker + 1 if existing[end_marker:end_marker + 1] == "\n" else end_marker
        new_content = existing[:start] + block + existing[end:]
        if new_content == existing:
            return False
        rc_path.write_text(new_content, encoding="utf-8")
        return True
    rc_path.parent.mkdir(parents=True, exist_ok=True)
    separator = "" if not existing or existing.endswith("\n") else "\n"
    rc_path.write_text(existing + separator + block, encoding="utf-8")
    return True


def persist_posix_rc(sh_path: Path) -> list[str]:
    """Wire an idempotent, marker-guarded source line into POSIX shell rc files.

    Returns the list of rc file paths actually modified (empty if all already
    had the current block — apply() stays idempotent across re-runs).
    """
    block = _rc_source_block(sh_path)
    changed: list[str] = []
    for rc_path in _posix_rc_candidates():
        if _write_idempotent_rc_block(rc_path, block):
            changed.append(str(rc_path))
    return changed


def persist_user_profile(
    *,
    set_windows_user_env: bool = True,
) -> dict[str, Any]:
    """Write ~/.simplicio-loop/economy-parallel-env.* and optionally Windows User env."""
    recommended = economy_parallel_env()
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
        "# Simplicio economy-parallel profile — dot-source: . $HOME\\.simplicio-loop\\economy-parallel-env.ps1",
        "$ErrorActionPreference = 'SilentlyContinue'",
    ]
    for key, value in sorted(recommended.items()):
        ps_lines.append(f"$env:{key} = '{value}'")
    paths["ps1"].write_text("\n".join(ps_lines) + "\n", encoding="utf-8", newline="\n")
    # POSIX
    sh_lines = [
        "# Simplicio economy-parallel profile — source ~/.simplicio-loop/economy-parallel-env.sh",
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
    rc_files_changed: list[str] = []
    if sys.platform != "win32":
        rc_files_changed = persist_posix_rc(paths["sh"])
        # still apply to this process
        for name, value in recommended.items():
            os.environ[name] = value
    else:
        for name, value in recommended.items():
            os.environ[name] = value

    if sys.platform == "win32":
        note = "New shells pick up User env after restart; this process is updated in-place."
    elif rc_files_changed:
        note = (
            "Persisted via guarded source line in "
            + ", ".join(rc_files_changed)
            + "; new interactive shells pick it up. This process is updated in-place."
        )
    else:
        note = (
            "rc files already wired (idempotent, no change needed); "
            "new interactive shells pick it up. This process is updated in-place."
        )

    return {
        "schema": SCHEMA,
        "ok": True,
        "profile": PROFILE_NAME,
        "paths": {k: str(v) for k, v in paths.items()},
        "env": recommended,
        "windows_user_env_keys": windows_set,
        "execution_profile": "standalone",
        "rc_files_changed": rc_files_changed,
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
    "persist_posix_rc",
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
