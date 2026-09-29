"""Focused tests for Prism's automatic slot capacity."""

from __future__ import annotations

import pytest

import arm_drain_prism


def _repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_arm_slots_zero_uses_machine_governor(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(arm_drain_prism, "_open_issue_count", lambda _repo: None)
    calls = []

    def recommend():
        calls.append(True)
        return 4

    monkeypatch.setattr(
        "simplicio_loop.economy_profile.recommend_prism_slots", recommend
    )

    receipt = arm_drain_prism.arm(repo, slots=0, max_iterations=5)

    assert calls == [True]
    assert receipt["prism_slots"] == 4
    assert receipt["prism_logical_capacity"] == 40
    assert receipt["recommended_env"]["SIMPLICIO_PRISM_SLOTS"] == "4"


def test_arm_rejects_negative_slots(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(arm_drain_prism, "_open_issue_count", lambda _repo: None)

    with pytest.raises(ValueError, match="non-negative"):
        arm_drain_prism.arm(repo, slots=-1)


def test_explicit_positive_slots_are_preserved(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(arm_drain_prism, "_open_issue_count", lambda _repo: None)
    def unexpected_auto():
        pytest.fail("explicit positive request must not invoke auto sizing")
    monkeypatch.setattr("simplicio_loop.economy_profile.recommend_prism_slots", unexpected_auto)
    receipt = arm_drain_prism.arm(repo, slots=3)
    assert receipt["prism_slots"] == 3


def test_main_rejects_negative_slots(tmp_path):
    repo = _repo(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        arm_drain_prism.main(["--repo", str(repo), "--slots", "-1"])

    assert exc_info.value.code == 2


def test_arm_env_fallback_is_standalone_and_names_no_runtime(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(arm_drain_prism, "_open_issue_count", lambda _repo: None)

    def unavailable(**_kwargs):
        raise RuntimeError("economy profile unavailable")

    monkeypatch.setattr("simplicio_loop.economy_profile.economy_parallel_env", unavailable)

    env = arm_drain_prism.arm(repo, slots=2, max_iterations=5)["recommended_env"]

    assert env["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in env
    assert env["SIMPLICIO_PRISM_SLOTS"] == "2"
