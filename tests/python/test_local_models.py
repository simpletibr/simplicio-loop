"""Data-only local-model compatibility tests."""

from __future__ import annotations

import subprocess

from simplicio.hardware import HardwareProfile, detect_gpu, pick_tier
from simplicio.local_models import DEFAULT_LOCAL_MODEL_ID, ensure_recommended


def _profile() -> HardwareProfile:
    return HardwareProfile(
        os_name="Darwin",
        ram_gb=64,
        vram_gb=0,
        gpu_name="Apple GPU",
        apple_silicon=True,
        tier=pick_tier(64, 0, True),
    )


def test_hardware_tier_mapping_remains_deterministic() -> None:
    assert pick_tier(64, 0, True) == "gpu-xlarge"
    assert pick_tier(8, 0, True) == "cpu-small"


def test_gpu_probe_oserror_degrades_to_no_gpu(monkeypatch) -> None:
    def broken_probe(*_args, **_kwargs):
        raise OSError(6, "invalid handle")

    monkeypatch.setattr(subprocess, "run", broken_probe)

    assert detect_gpu() == (0.0, "", "no GPU detected", False)


def test_local_model_status_never_provisions_or_enables_execution(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")
    result = ensure_recommended(_profile(), auto_download=True)

    assert result.spec.model_id == DEFAULT_LOCAL_MODEL_ID
    assert result.can_run is False
    assert result.can_download is False
    assert result.reason == "llm_execution_disabled"
    assert result.policy_receipt["reason_code"] == "llm_execution_disabled"
