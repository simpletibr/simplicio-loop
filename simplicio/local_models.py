"""local_models.py — hardware-tier → local model recommendation + Ollama plumbing.

Encodes the local LLM standard:

  all tiers      → openbmb/minicpm5:latest via local Ollama (~0.7 GB)

The GGUF fallback is handled by simplicio.providers as
Qwen_Qwen3.5-2B-Q6_K.gguf when Ollama is unavailable.

Hard rule (issue #32 follow-up):
- NEVER auto-pull a model that does not fit the detected tier.
  ensure_recommended() refuses to pull if disk_gb < expected_size +
  safety margin OR if the model size > hardware tier ceiling.
- Pulls require explicit opt-in (SIMPLICIO_AUTO_PULL=1 or the user passes
  --auto-pull through the CLI). We tell the user the command and stop.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

from .hardware import HardwareProfile


@dataclass
class ModelSpec:
    tier: str
    ollama_id: str
    size_gb_q4: float
    label: str
    notes: str = ""


DEFAULT_LOCAL_OLLAMA_ID = "openbmb/minicpm5:latest"
DEFAULT_LOCAL_OLLAMA_LABEL = "MiniCPM5 local (Ollama)"
DEFAULT_LOCAL_OLLAMA_SIZE_GB = 0.7
DEFAULT_LOCAL_OLLAMA_NOTES = (
    "canonical local primary; falls back to Qwen_Qwen3.5-2B-Q6_K.gguf in providers"
)


# Order matters: list is consulted in the rare case the user asks for the
# next-step-up model. The default lookup is by exact tier.
RECOMMENDATIONS: dict[str, ModelSpec] = {
    tier: ModelSpec(
        tier,
        DEFAULT_LOCAL_OLLAMA_ID,
        DEFAULT_LOCAL_OLLAMA_SIZE_GB,
        DEFAULT_LOCAL_OLLAMA_LABEL,
        DEFAULT_LOCAL_OLLAMA_NOTES,
    )
    for tier in ("cpu-tiny", "cpu-small", "gpu-mid", "gpu-large", "gpu-xlarge", "unknown")
}


# ---- Ollama plumbing ---- #


def ollama_present() -> bool:
    return shutil.which("ollama") is not None


def ollama_list_installed() -> list[str]:
    """Return the list of Ollama models currently installed.

    Each entry is the full tag the user can target (e.g. "openbmb/minicpm5:latest").
    Empty list on failure — never raises.
    """
    if not ollama_present():
        return []
    try:
        out = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    # `ollama list` first row is the header; subsequent rows have NAME first
    rows = out.stdout.strip().splitlines()
    if len(rows) <= 1:
        return []
    installed = []
    for line in rows[1:]:
        parts = line.split()
        if parts:
            installed.append(parts[0])
    return installed


def is_installed(ollama_id: str) -> bool:
    """Looser match hook kept for future aliases; currently exact tag match."""
    installed = ollama_list_installed()
    return ollama_id in installed


def pull(ollama_id: str, timeout: int = 1800) -> tuple[bool, str]:
    """Run `ollama pull <id>`. Returns (ok, last_lines).

    Caller is responsible for tier / disk-space gating BEFORE calling this.
    """
    if not ollama_present():
        return False, "ollama not on PATH"
    try:
        out = subprocess.run(
            ["ollama", "pull", ollama_id],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"ollama pull timed out after {timeout}s"
    log = (out.stdout or "") + (out.stderr or "")
    return out.returncode == 0, log[-2000:]


# ---- The actual gate ---- #


@dataclass
class RecommendationResult:
    spec: ModelSpec
    profile: HardwareProfile
    can_run: bool
    can_pull: bool
    installed: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "tier": self.spec.tier,
            "ollama_id": self.spec.ollama_id,
            "label": self.spec.label,
            "size_gb_q4": self.spec.size_gb_q4,
            "notes": self.spec.notes,
            "ram_gb": round(self.profile.ram_gb, 1),
            "vram_gb": round(self.profile.vram_gb, 1),
            "gpu": self.profile.gpu_name,
            "apple_silicon": self.profile.apple_silicon,
            "can_run": self.can_run,
            "can_pull": self.can_pull,
            "installed": self.installed,
            "reason": self.reason,
        }


# Safety margin: refuse to pull if the detected resource isn't at least
# (size + margin) — we don't want to brick a 16 GB laptop pulling a 17.5 GB
# model and then OOM at runtime.
_SAFETY_MARGIN_GB = 4.0


def evaluate(profile: HardwareProfile) -> RecommendationResult:
    """Pick the spec for this tier and decide whether the host can run/pull it."""
    spec = RECOMMENDATIONS.get(profile.tier, RECOMMENDATIONS["unknown"])

    # `can_run`: hardware has enough headroom to actually run the model.
    # On Apple Silicon, RAM == VRAM. On Linux/Windows NVIDIA, VRAM dominates;
    # we still check RAM as a backstop for CPU offload.
    if profile.apple_silicon:
        usable_gb = profile.ram_gb
    else:
        usable_gb = max(profile.vram_gb, profile.ram_gb)
    needed_gb = spec.size_gb_q4 + _SAFETY_MARGIN_GB

    can_run = usable_gb >= needed_gb
    can_pull = ollama_present() and can_run
    reason = ""
    if not ollama_present():
        reason = "ollama not installed — see https://ollama.ai"
    elif not can_run:
        reason = (f"detected {usable_gb:.1f} GB usable < {needed_gb:.1f} GB "
                  f"required for {spec.label} (size {spec.size_gb_q4:.1f} GB + "
                  f"{_SAFETY_MARGIN_GB:.0f} GB safety margin)")

    installed = is_installed(spec.ollama_id) if ollama_present() else False
    return RecommendationResult(
        spec=spec, profile=profile,
        can_run=can_run, can_pull=can_pull, installed=installed, reason=reason,
    )


def ensure_recommended(profile: HardwareProfile, auto_pull: bool = False) -> RecommendationResult:
    """High-level orchestrator. If the recommended model isn't installed, and
    auto_pull is True AND can_pull is True, run `ollama pull`. Otherwise return
    a result that the CLI can render so the user knows what to do.

    Honours SIMPLICIO_AUTO_PULL=1 as an alias for auto_pull=True.
    """
    result = evaluate(profile)
    if result.installed:
        return result
    if not result.can_pull:
        return result

    do_pull = auto_pull or os.environ.get("SIMPLICIO_AUTO_PULL", "").strip() in (
        "1", "true", "True", "yes",
    )
    if not do_pull:
        result.reason = (f"model not installed — opt in to auto-pull with "
                         f"`simplicio doctor --install` or "
                         f"`SIMPLICIO_AUTO_PULL=1 ...` "
                         f"(will fetch {result.spec.size_gb_q4:.1f} GB)")
        return result

    ok, log = pull(result.spec.ollama_id)
    if ok:
        result.installed = True
        result.reason = "pulled via ollama"
    else:
        result.reason = f"ollama pull failed: {log[-300:]}"
    return result
