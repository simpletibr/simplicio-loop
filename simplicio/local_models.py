"""local model status compatibility layer.

Keeps the historical local-model status shape:

  all tiers -> openbmb/minicpm5:latest
               openbmb/MiniCPM5-1B-GGUF::MiniCPM5-1B-Q4_K_M.gguf

``simplicio-py`` no longer executes or provisions local models.  The data-only
status types remain for callers that still render hardware/model state.

All model execution and provisioning is permanently disabled in this package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .hardware import HardwareProfile
from .providers import (
    LOCAL_DEFAULT_FILE as DEFAULT_LOCAL_FILE,
)
from .providers import (
    LOCAL_DEFAULT_MODEL,
    LOCAL_EXECUTOR_DIR,
)
from .providers import (
    LOCAL_DEFAULT_REPO as DEFAULT_LOCAL_REPO,
)

DEFAULT_LOCAL_MODEL_ID = LOCAL_DEFAULT_MODEL
DEFAULT_LOCAL_LABEL = "MiniCPM5 1B Q4_K_M GGUF (disabled status only)"
DEFAULT_LOCAL_SIZE_GB = 0.8
DEFAULT_LOCAL_NOTES = "historical local model metadata; execution and provisioning disabled"


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
    """Refuse model provisioning; the adapter is deterministic-only."""
    del spec
    return False, "local LLM execution and model provisioning are disabled"


@dataclass
class RecommendationResult:
    spec: ModelSpec
    profile: HardwareProfile
    can_run: bool
    can_download: bool
    installed: bool
    reason: str = ""
    policy_receipt: dict | None = None

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
            "policy_receipt": self.policy_receipt,
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
    """Return a deterministic disabled receipt for local-model requests."""
    del auto_download, auto_pull

    result = evaluate(profile)
    result.can_run = False
    result.can_download = False
    result.reason = "llm_execution_disabled"
    result.policy_receipt = {
        "schema": "simplicio.provider-terminal/v1",
        "status": "blocked",
        "reason_code": "llm_execution_disabled",
        "message": "local model execution and provisioning are disabled",
    }
    return result
