"""hardware.py — detect host RAM + GPU VRAM to pick a default local model.

Stdlib-only. Works on Linux + macOS. Returns a `HardwareProfile` carrying
the numbers + a `tier` string (`cpu-tiny` / `cpu-small` / `gpu-mid` /
`gpu-large` / `gpu-xlarge`) that maps deterministically to a model.

The detection routines all fail soft — if a probe fails we mark that
resource as unknown rather than crash. simplicio-py doctor surfaces the
unknown fields so the user can override.
"""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass, field


@dataclass
class HardwareProfile:
    os_name: str
    ram_gb: float  # total system RAM
    vram_gb: float  # largest GPU VRAM, 0 if no GPU detected
    gpu_name: str = ""  # human-readable
    apple_silicon: bool = False
    tier: str = "unknown"
    detected_via: dict = field(default_factory=dict)  # debug breadcrumbs

    def to_dict(self) -> dict:
        return {
            "os": self.os_name,
            "ram_gb": round(self.ram_gb, 1),
            "vram_gb": round(self.vram_gb, 1),
            "gpu_name": self.gpu_name,
            "apple_silicon": self.apple_silicon,
            "tier": self.tier,
            "detected_via": self.detected_via,
        }


# ---- RAM detection ---- #


def _ram_linux() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except OSError:
        return None
    return None


def _ram_macos() -> float | None:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if out.returncode != 0:
            return None
        return int(out.stdout.strip()) / (1024**3)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def detect_ram() -> tuple[float, str]:
    """Return (ram_gb, source). 0.0 if unknown."""
    system = platform.system()
    if system == "Linux":
        v = _ram_linux()
        if v is not None:
            return v, "/proc/meminfo"
    if system == "Darwin":
        v = _ram_macos()
        if v is not None:
            return v, "sysctl hw.memsize"
    return 0.0, "unknown"


# ---- GPU detection ---- #


def _gpu_nvidia() -> tuple[float, str] | None:
    """nvidia-smi available? Return (vram_gb, name) for the biggest GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    # Captured console handles can be invalid under Windows test runners
    # (WinError 6/50).  Hardware probing is advisory, so every OS-level
    # process-launch failure must degrade to "no GPU" instead of failing
    # `doctor --json`.
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    best = (0.0, "")
    for line in out.stdout.strip().splitlines():
        try:
            mem_str, name = line.split(",", 1)
            mem_mib = float(mem_str.strip())
            if mem_mib > best[0]:
                best = (mem_mib / 1024, name.strip())
        except (ValueError, IndexError):
            continue
    return best if best[0] > 0 else None


_APPLE_SILICON_RE = re.compile(r"Apple (M\d+(?:\s+(?:Pro|Max|Ultra))?)")


def _gpu_apple_silicon() -> tuple[float, str] | None:
    """On Apple Silicon the GPU shares system RAM. Return (vram_gb, chip)
    where vram_gb = total RAM (since unified memory), and chip is e.g. "M3 Max".
    """
    if platform.system() != "Darwin":
        return None
    if platform.machine() != "arm64":
        return None
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    chip_match = _APPLE_SILICON_RE.search(out.stdout)
    chip_name = chip_match.group(1) if chip_match else "Apple Silicon"
    ram_gb, _ = detect_ram()
    return (ram_gb, chip_name) if ram_gb > 0 else None


def detect_gpu() -> tuple[float, str, str, bool]:
    """Return (vram_gb, gpu_name, source, apple_silicon)."""
    nv = _gpu_nvidia()
    if nv is not None:
        vram, name = nv
        return vram, name, "nvidia-smi", False
    apple = _gpu_apple_silicon()
    if apple is not None:
        vram, chip = apple
        return vram, chip, "sysctl + arm64", True
    return 0.0, "", "no GPU detected", False


# ---- tier mapping ---- #


def pick_tier(ram_gb: float, vram_gb: float, apple_silicon: bool) -> str:
    """Map detected resources to one of:
      cpu-tiny      — <8 GB RAM, no usable GPU
      cpu-small     — 8-16 GB RAM, no usable GPU
      gpu-mid       — 12-20 GB usable VRAM (or unified) — 14B sweet spot
      gpu-large     — 20-32 GB unified/VRAM — 30B-A3B MoE sweet spot
      gpu-xlarge    — 32+ GB — Coder-Next-class

    For Apple Silicon, unified memory means RAM doubles as VRAM, so we
    pick on RAM directly. For NVIDIA, we pick on VRAM and trust the user
    to have enough system RAM for the model + KV cache overhead.

    Thresholds are deliberately ~5% looser than the marketing number
    (e.g. "16 GB" → threshold 15.0) because the OS always reserves a
    chunk for itself and /proc/meminfo reports the user-available number,
    not the slot capacity. A 16 GB machine that shows 15.7 GB should
    still pick up the 8-16 GB tier.
    """
    if apple_silicon:
        if ram_gb >= 46:
            return "gpu-xlarge"
        if ram_gb >= 23:
            return "gpu-large"
        if ram_gb >= 15:
            return "gpu-mid"
        if ram_gb >= 7.5:
            return "cpu-small"
        return "cpu-tiny"

    if vram_gb >= 30:
        return "gpu-xlarge"
    if vram_gb >= 19:
        return "gpu-large"
    if vram_gb >= 11:
        return "gpu-mid"
    if ram_gb >= 15:
        return "cpu-small"
    return "cpu-tiny"


def detect() -> HardwareProfile:
    ram_gb, ram_src = detect_ram()
    vram_gb, gpu_name, gpu_src, apple = detect_gpu()
    tier = pick_tier(ram_gb, vram_gb, apple)
    return HardwareProfile(
        os_name=platform.system(),
        ram_gb=ram_gb,
        vram_gb=vram_gb,
        gpu_name=gpu_name,
        apple_silicon=apple,
        tier=tier,
        detected_via={"ram": ram_src, "gpu": gpu_src},
    )
