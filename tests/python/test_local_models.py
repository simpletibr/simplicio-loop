"""Deterministic-only model status tests."""

from __future__ import annotations

from simplicio.hardware import HardwareProfile, pick_tier
from simplicio.local_models import (
    DEFAULT_LOCAL_FILE,
    DEFAULT_LOCAL_MODEL_ID,
    RECOMMENDATIONS,
    ModelSpec,
    download,
    ensure_recommended,
    evaluate,
)


def _profile(ram: float, vram: float, apple: bool = False) -> HardwareProfile:
    return HardwareProfile(
        os_name="Linux",
        ram_gb=ram,
        vram_gb=vram,
        gpu_name="",
        apple_silicon=apple,
        tier=pick_tier(ram, vram, apple),
    )


def test_recommendations_are_data_only() -> None:
    result = evaluate(_profile(24, 24, apple=True))
    assert result.spec.model_id == DEFAULT_LOCAL_MODEL_ID
    assert result.spec.filename == DEFAULT_LOCAL_FILE
    assert result.installed is False


def test_download_is_always_blocked() -> None:
    ok, message = download(RECOMMENDATIONS["unknown"])
    assert ok is False
    assert "llm_execution_disabled" in message


def test_ensure_never_downloads_even_when_requested(monkeypatch) -> None:
    monkeypatch.setenv("SIMPLICIO_AUTO_DOWNLOAD", "1")
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")
    result = ensure_recommended(_profile(64, 24), auto_download=True)
    assert result.can_download is False
    assert result.policy_receipt["reason_code"] == "llm_execution_disabled"


def test_ensure_preserves_installed_data_status(monkeypatch) -> None:
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _spec: True)
    result = ensure_recommended(_profile(64, 24))
    assert result.installed is True
    assert result.can_download is False


def test_evaluate_safety_margin_remains_deterministic(monkeypatch) -> None:
    monkeypatch.setitem(
        RECOMMENDATIONS,
        "gpu-large",
        ModelSpec(
            "gpu-large",
            DEFAULT_LOCAL_MODEL_ID,
            "repo/too-large",
            "too-large.gguf",
            17.5,
            "Too Large",
        ),
    )
    result = evaluate(
        HardwareProfile(
            os_name="Linux",
            ram_gb=8,
            vram_gb=0,
            gpu_name="",
            apple_silicon=False,
            tier="gpu-large",
        )
    )
    assert result.can_run is False
