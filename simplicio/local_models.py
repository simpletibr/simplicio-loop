"""local_models.py - hardware-tier -> llama.cpp GGUF recommendation.

Encodes the local LLM standard:

  all tiers -> local-llama/default
               bartowski/Qwen_Qwen3.5-2B-GGUF::Qwen_Qwen3.5-2B-Q6_K.gguf

The model runs in-process through llama-cpp-python. No Ollama daemon, pull, or
HTTP endpoint is required for the default local path.

Hard rule (issue #32 follow-up):
- NEVER auto-download a model that does not fit the detected tier.
- Downloads require explicit opt-in (SIMPLICIO_AUTO_DOWNLOAD=1 or
  `simplicio doctor --install`). We tell the user the command and stop.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .hardware import HardwareProfile
from .providers import (
    LOCAL_DEFAULT_FILE as DEFAULT_LOCAL_FILE,
    LOCAL_DEFAULT_REPO as DEFAULT_LOCAL_REPO,
    LOCAL_EXECUTOR_DIR,
    LOCAL_MODEL_PREFIX,
)


DEFAULT_LOCAL_MODEL_ID = f"{LOCAL_MODEL_PREFIX}default"
DEFAULT_LOCAL_LABEL = "Qwen3.5 2B Q6_K GGUF (llama.cpp)"
DEFAULT_LOCAL_SIZE_GB = 1.6
DEFAULT_LOCAL_NOTES = (
    "canonical local doer; runs in-process with llama-cpp-python, no Ollama service"
)


@dataclass
class ModelSpec:
    tier: str
    model_id: str
    repo_id: str
    filename: str
    size_gb_q4: float
    label: str
    notes: str = ""

    @property
    def ollama_id(self) -> str:
        """Backward-compatible read alias for older callers."""
        return self.model_id


RECOMMENDATIONS: dict[str, ModelSpec] = {
    tier: ModelSpec(
        tier,
        DEFAULT_LOCAL_MODEL_ID,
        DEFAULT_LOCAL_REPO,
        DEFAULT_LOCAL_FILE,
        DEFAULT_LOCAL_SIZE_GB,
        DEFAULT_LOCAL_LABEL,
        DEFAULT_LOCAL_NOTES,
    )
    for tier in ("cpu-tiny", "cpu-small", "gpu-mid", "gpu-large", "gpu-xlarge", "unknown")
}


def local_model_dir() -> Path:
    return Path(os.environ.get("SIMPLICIO_LOCAL_MODEL_DIR", LOCAL_EXECUTOR_DIR)).expanduser()


def model_file_path(spec: ModelSpec) -> Path:
    override = os.environ.get("SIMPLICIO_LOCAL_MODEL_PATH")
    if override:
        return Path(override).expanduser()
    return local_model_dir() / spec.filename


def _is_gguf_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"GGUF"
    except OSError:
        return False


def model_file_present(spec: ModelSpec) -> bool:
    return _is_gguf_file(model_file_path(spec))


def is_installed(spec: ModelSpec | str) -> bool:
    if isinstance(spec, ModelSpec):
        return model_file_present(spec)
    if spec.endswith(".gguf"):
        return _is_gguf_file(local_model_dir() / spec)
    if spec == DEFAULT_LOCAL_MODEL_ID:
        return model_file_present(RECOMMENDATIONS["unknown"])
    return False


def download(spec: ModelSpec) -> tuple[bool, str]:
    """Download the recommended GGUF into the executor model directory."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return (
            False,
            "huggingface-hub not installed. Install extras: pip install 'simplicio-cli[local]'",
        )

    target_dir = local_model_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = Path(
            hf_hub_download(
                repo_id=spec.repo_id,
                filename=spec.filename,
                local_dir=str(target_dir),
            )
        )
    except Exception as exc:  # noqa: BLE001 - rendered as CLI status
        return False, str(exc)
    if not _is_gguf_file(path):
        return False, f"{path} is not a valid GGUF file"
    return True, str(path)


@dataclass
class RecommendationResult:
    spec: ModelSpec
    profile: HardwareProfile
    can_run: bool
    can_download: bool
    installed: bool
    reason: str = ""

    @property
    def can_pull(self) -> bool:
        """Backward-compatible read alias for older callers."""
        return self.can_download

    def to_dict(self) -> dict:
        return {
            "tier": self.spec.tier,
            "model_id": self.spec.model_id,
            "repo_id": self.spec.repo_id,
            "filename": self.spec.filename,
            "model_path": str(model_file_path(self.spec)),
            "label": self.spec.label,
            "size_gb_q4": self.spec.size_gb_q4,
            "notes": self.spec.notes,
            "ram_gb": round(self.profile.ram_gb, 1),
            "vram_gb": round(self.profile.vram_gb, 1),
            "gpu": self.profile.gpu_name,
            "apple_silicon": self.profile.apple_silicon,
            "can_run": self.can_run,
            "can_download": self.can_download,
            "installed": self.installed,
            "reason": self.reason,
        }


# Safety margin: refuse to download if the detected resource is not at least
# (size + margin). We do not want a local automation flow to fill disk/RAM with
# a model it cannot actually run.
_SAFETY_MARGIN_GB = 4.0


def evaluate(profile: HardwareProfile) -> RecommendationResult:
    """Pick the local GGUF spec and decide whether the host can run/download it."""
    spec = RECOMMENDATIONS.get(profile.tier, RECOMMENDATIONS["unknown"])

    if profile.apple_silicon:
        usable_gb = profile.ram_gb
    else:
        usable_gb = max(profile.vram_gb, profile.ram_gb)
    needed_gb = spec.size_gb_q4 + _SAFETY_MARGIN_GB

    can_run = usable_gb >= needed_gb
    installed = is_installed(spec)
    can_download = can_run and not installed
    reason = ""
    if not can_run:
        reason = (
            f"detected {usable_gb:.1f} GB usable < {needed_gb:.1f} GB "
            f"required for {spec.label} (size {spec.size_gb_q4:.1f} GB + "
            f"{_SAFETY_MARGIN_GB:.0f} GB safety margin)"
        )
    elif not installed:
        reason = f"local GGUF not installed at {model_file_path(spec)}"

    return RecommendationResult(
        spec=spec,
        profile=profile,
        can_run=can_run,
        can_download=can_download,
        installed=installed,
        reason=reason,
    )


def ensure_recommended(
    profile: HardwareProfile,
    auto_download: bool = False,
    *,
    auto_pull: bool | None = None,
) -> RecommendationResult:
    """High-level orchestrator for the default local llama.cpp model.

    If the recommended GGUF is missing and auto_download is true, download it.
    Otherwise return a result the CLI can render so the user knows what to do.
    `auto_pull` remains as a keyword-only alias for older code paths, but still
    performs a GGUF download rather than any Ollama action.
    """
    if auto_pull is not None:
        auto_download = auto_download or auto_pull

    result = evaluate(profile)
    if result.installed:
        return result
    if not result.can_download:
        return result

    do_download = auto_download or os.environ.get(
        "SIMPLICIO_AUTO_DOWNLOAD", ""
    ).strip() in ("1", "true", "True", "yes")
    if not do_download:
        result.reason = (
            "model not installed - opt in to download with "
            "`simplicio doctor --install` or `SIMPLICIO_AUTO_DOWNLOAD=1 ...` "
            f"(will fetch ~{result.spec.size_gb_q4:.1f} GB)"
        )
        return result

    ok, log = download(result.spec)
    if ok:
        result.installed = True
        result.can_download = False
        result.reason = f"downloaded GGUF to {log}"
    else:
        result.reason = f"GGUF download failed: {log[-300:]}"
    return result
