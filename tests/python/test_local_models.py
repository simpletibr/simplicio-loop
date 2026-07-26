"""Tests for hardware detection + local_models tier -> spec mapping +
ensure_recommended safety gate."""

from __future__ import annotations

import pytest

from simplicio.hardware import HardwareProfile, pick_tier
from simplicio.local_models import (
    DEFAULT_LOCAL_FILE,
    DEFAULT_LOCAL_MODEL_ID,
    RECOMMENDATIONS,
    ModelSpec,
    evaluate,
)


@pytest.fixture(autouse=True)
def _explicit_local_test_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy provisioning tests intentionally exercise the gated path."""
    monkeypatch.setenv("SIMPLICIO_LOCAL_INFERENCE", "enabled")


# ---- pick_tier ---- #


@pytest.mark.parametrize(
    ("ram", "vram", "apple", "expected"),
    [
        # NVIDIA / generic non-Apple paths key on VRAM
        (32, 40, False, "gpu-xlarge"),  # 40 GB VRAM
        (32, 24, False, "gpu-large"),  # 24 GB VRAM
        (32, 16, False, "gpu-mid"),
        (16, 0, False, "cpu-small"),
        (15.7, 0, False, "cpu-small"),  # OS-reserved memory: 16 GB nominal → 15.7 reported
        (4, 0, False, "cpu-tiny"),
        # Apple Silicon: unified memory, key on RAM
        (64, 0, True, "gpu-xlarge"),
        (32, 0, True, "gpu-large"),
        (18, 0, True, "gpu-mid"),
        (15.7, 0, True, "gpu-mid"),  # 16 GB Mac reports ~15.7 too
        (8, 0, True, "cpu-small"),
        (4, 0, True, "cpu-tiny"),
    ],
)
def test_pick_tier_threshold_table(ram, vram, apple, expected) -> None:
    assert pick_tier(ram, vram, apple) == expected


# ---- evaluate / safety gate ---- #


def _profile(ram, vram, apple=False, tier=None) -> HardwareProfile:
    return HardwareProfile(
        os_name="Linux",
        ram_gb=ram,
        vram_gb=vram,
        gpu_name="",
        apple_silicon=apple,
        tier=tier or pick_tier(ram, vram, apple),
    )


def test_evaluate_picks_correct_spec_per_tier() -> None:
    for tier in ("cpu-tiny", "cpu-small", "gpu-mid", "gpu-large", "gpu-xlarge"):
        prof = HardwareProfile(os_name="Linux", ram_gb=64, vram_gb=64, apple_silicon=False, tier=tier)
        r = evaluate(prof)
        assert r.spec.tier == tier
        assert r.spec.model_id == RECOMMENDATIONS[tier].model_id
        assert r.spec.model_id == DEFAULT_LOCAL_MODEL_ID
        assert r.spec.filename == DEFAULT_LOCAL_FILE


def test_evaluate_refuses_to_run_oversized_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 16 GB laptop should NEVER get can_run=True for the 17.5 GB MoE
    even if the tier mapping somehow points there — safety margin enforces."""
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    monkeypatch.setitem(
        RECOMMENDATIONS,
        "gpu-large",
        ModelSpec("gpu-large", DEFAULT_LOCAL_MODEL_ID, "repo/too-large", "too-large.gguf", 17.5, "Too Large"),
    )
    # Force a mismatch: profile says cpu-small (small) but we set tier to
    # gpu-large to simulate a bad override
    prof = HardwareProfile(os_name="Linux", ram_gb=16, vram_gb=0, apple_silicon=False, tier="gpu-large")
    r = evaluate(prof)
    assert r.can_run is False
    assert "usable" in r.reason and "required" in r.reason


def test_evaluate_marks_gguf_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    prof = _profile(ram=8, vram=0)
    r = evaluate(prof)
    assert r.can_download is True
    assert "local GGUF not installed" in r.reason


def test_apple_silicon_profile_can_run_minicpm_gguf_at_24gb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    prof = _profile(ram=24, vram=24, apple=True)
    r = evaluate(prof)
    assert r.spec.tier == "gpu-large"
    assert r.can_run is True
    # not yet installed -> can_download=true, but caller still needs --install
    assert r.can_download is True


# ---- ensure_recommended opt-in gate ---- #


def test_ensure_recommended_does_not_download_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hard rule from issue #32: never auto-download without explicit consent.
    Missing model + can_download=True must STILL not call download() unless
    auto_download=True or SIMPLICIO_AUTO_DOWNLOAD=1 is set."""
    monkeypatch.delenv("SIMPLICIO_AUTO_PULL", raising=False)
    monkeypatch.delenv("SIMPLICIO_AUTO_DOWNLOAD", raising=False)
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    monkeypatch.setitem(
        RECOMMENDATIONS,
        "gpu-large",
        ModelSpec("gpu-large", DEFAULT_LOCAL_MODEL_ID, "repo/weights", "weights.gguf", 1.6, "MiniCPM GGUF"),
    )
    downloaded = {"called": False}

    def fake_download(_spec):
        downloaded["called"] = True
        return True, ""

    monkeypatch.setattr("simplicio.local_models.download", fake_download)

    from simplicio.local_models import ensure_recommended

    prof = _profile(ram=32, vram=24, apple=False)  # gpu-large
    r = ensure_recommended(prof, auto_download=False)
    assert downloaded["called"] is False
    assert r.installed is False
    assert "opt in" in r.reason


def test_ensure_recommended_reports_pause_without_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIMPLICIO_LOCAL_INFERENCE", raising=False)
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    called = {"value": False}

    def fake_download(_spec):
        called["value"] = True
        return True, "unexpected"

    monkeypatch.setattr("simplicio.local_models.download", fake_download)
    from simplicio.local_models import ensure_recommended

    result = ensure_recommended(_profile(ram=64, vram=24), auto_download=True)
    assert result.reason == "LOCAL_INFERENCE_PAUSED"
    assert result.can_download is False
    assert called["value"] is False


def test_ensure_recommended_downloads_with_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    downloaded = {"called": False, "file": ""}

    def fake_download(spec):
        downloaded["called"] = True
        downloaded["file"] = spec.filename
        return True, "downloaded ok"

    monkeypatch.setattr("simplicio.local_models.download", fake_download)

    from simplicio.local_models import ensure_recommended

    prof = _profile(ram=64, vram=24, apple=False)  # gpu-large
    r = ensure_recommended(prof, auto_download=True)
    assert downloaded["called"] is True
    assert downloaded["file"] == RECOMMENDATIONS["gpu-large"].filename
    assert r.installed is True


def test_ensure_recommended_downloads_via_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLICIO_AUTO_DOWNLOAD", "1")
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    called = {"value": False}

    def fake_download(_spec):
        called["value"] = True
        return True, ""

    monkeypatch.setattr("simplicio.local_models.download", fake_download)

    from simplicio.local_models import ensure_recommended

    prof = _profile(ram=64, vram=24, apple=False)
    ensure_recommended(prof, auto_download=False)
    assert called["value"] is True


def test_ensure_recommended_skips_download_when_already_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: True)
    downloaded = {"called": False}

    def fake_download(_spec):
        downloaded["called"] = True
        return True, ""

    monkeypatch.setattr("simplicio.local_models.download", fake_download)

    from simplicio.local_models import ensure_recommended

    prof = _profile(ram=64, vram=24, apple=False)
    r = ensure_recommended(prof, auto_download=True)
    assert downloaded["called"] is False
    assert r.installed is True


def test_ensure_recommended_refuses_download_when_undersized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hard guarantee: NEVER download a model that doesn't fit. Even with
    auto_download=True, if can_run is false we don't touch the disk."""
    monkeypatch.setattr("simplicio.local_models.model_file_present", lambda _s: False)
    monkeypatch.setattr("simplicio.local_models.is_installed", lambda _id: False)
    monkeypatch.setitem(
        RECOMMENDATIONS,
        "gpu-large",
        ModelSpec("gpu-large", DEFAULT_LOCAL_MODEL_ID, "repo/too-large", "too-large.gguf", 17.5, "Too Large"),
    )
    downloaded = {"called": False}

    def fake_download(_spec):
        downloaded["called"] = True
        return True, ""

    monkeypatch.setattr("simplicio.local_models.download", fake_download)

    from simplicio.local_models import ensure_recommended

    # Pretend the tier mapper picked gpu-large but the host has only 8 GB
    prof = HardwareProfile(
        os_name="Linux",
        ram_gb=8,
        vram_gb=0,
        apple_silicon=False,
        tier="gpu-large",
    )
    r = ensure_recommended(prof, auto_download=True)
    assert downloaded["called"] is False
    assert r.can_run is False
    assert r.installed is False
