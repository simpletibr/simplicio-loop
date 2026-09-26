"""Economy-parallel profile: token path + bounded parallel defaults."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from simplicio_loop import economy_profile as ep
from simplicio_loop import strict_mode


@pytest.fixture(autouse=True)
def _restore_process_env():
    # persist_user_profile() updates os.environ in-place by design; keep that
    # from leaking into later tests (e.g. strict_mode preflight shape checks).
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


def test_worker_bounds_scale_with_cpu():
    # Maximum the machine can use: all logical CPUs (floor 2)
    assert ep.recommend_operator_workers(1) == 2
    assert ep.recommend_operator_workers(4) == 4
    assert ep.recommend_operator_workers(32) == 32  # no artificial 12 clamp


def test_prism_slots_machine_max_scales_with_cpu(monkeypatch):
    # Isolate from RAM so CPU formula is deterministic
    monkeypatch.setattr(ep, "_ram_gb", lambda: (None, None))
    assert ep.recommend_prism_slots(1) == 2
    assert ep.recommend_prism_slots(2) == 2
    assert ep.recommend_prism_slots(4) == 3  # leave 1 core for OS/Runtime
    assert ep.recommend_prism_slots(16) == 15  # no 8-slot ceiling
    # Total RAM capacity caps slots (32 GiB → 28 usable → up to 28; min with cpu)
    monkeypatch.setattr(ep, "_ram_gb", lambda: (32.0, 20.0))
    assert ep.recommend_prism_slots(16) == 15  # cpu still binds
    monkeypatch.setattr(ep, "_ram_gb", lambda: (8.0, 6.0))  # 8-4=4 slots
    assert ep.recommend_prism_slots(16) == 4
    # Critical free RAM tightens further
    monkeypatch.setattr(ep, "_ram_gb", lambda: (32.0, 2.0))
    assert ep.recommend_prism_slots(16) == 2


def test_economy_env_is_always_standalone():
    env = ep.economy_parallel_env(prism_slots=4, operator_workers=6)
    assert env["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in env
    assert "SIMPLICIO_REQUIRE_MCP" not in env
    assert "SIMPLICIO_MCP_FORCE" not in env


def test_economy_env_enables_fan_out_and_latest():
    env = ep.economy_parallel_env(prism_slots=4, operator_workers=6)
    assert env["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"
    assert env["SIMPLICIO_OPERATOR_ALWAYS_LATEST"] == "1"
    assert env["SIMPLICIO_PRISM_SLOTS"] == "4"
    assert env["SIMPLICIO_PRISM_BATCH_SIZE"] == "10"
    assert env["SIMPLICIO_LOOP_OPERATOR_WORKERS"] == "6"
    assert env["SIMPLICIO_FAST_MODE"] == "required"
    assert env["SIMPLICIO_EXECUTION_PROFILE"] == "standalone"


def test_profile_status_exposes_llm_max_speed_orientation():
    status = ep.profile_status()
    orient = status["llm_orientation"]
    assert orient["schema"] == "simplicio.llm-max-speed-orientation/v1"
    assert orient["canonical_doc"] == "docs/LLM_MAX_SPEED_ORIENTATION.md"
    assert "DONE" in orient["message_cadence"]
    assert any("hand-edit" in f for f in orient["forbid"])
    assert orient["context_route"]["primary"] == "simplicio-fast"
    assert orient["fallback_policy"]["auto"] == "mapper_read_only"
    assert orient["mutation_boundary"]["authorized"] is False
    assert orient["receipt_schema"] == "simplicio.loop-orient-receipt/v1"
    assert status["hot_path"][0].startswith("simplicio-loop preflight")


def test_prism_batch_defaults_to_ten_and_supports_explicit_thirty():
    assert ep.resolve_prism_batch_size() == 10
    assert ep.resolve_prism_batch_size(30) == 30
    assert ep.prism_batches(range(1, 26), 10) == [
        list(range(1, 11)), list(range(11, 21)), list(range(21, 26))
    ]
    assert ep.prism_is_eligible(3)["eligible"] is False
    assert ep.prism_is_eligible(3)["parallelism"] == "direct"
    assert ep.prism_is_eligible(4)["eligible"] is True
    assert ep.prism_is_eligible(4)["reason_code"] == "prism_above_three_tasks"
    assert ep.prism_is_eligible(1)["reason_code"] == "single_item"
    assert ep.resolve_prism_batch_size(65) == 65
    with pytest.raises(ValueError):
        ep.resolve_prism_batch_size(9)


def test_profile_status_reports_standalone():
    status = ep.profile_status()
    assert status["execution_profile"] == "standalone"
    assert status["note"] is None
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in status["recommended"]
    assert "SIMPLICIO_REQUIRE_MCP" not in status["recommended"]
    assert "SIMPLICIO_MCP_FORCE" not in status["recommended"]


def test_recommended_env_uses_economy_when_enabled(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ECONOMY_PARALLEL", "1")
    monkeypatch.setattr(
        strict_mode,
        "fast_status",
        lambda env=None: {"operational": True, "present": True, "version": "2.0.23"},
    )
    rec = strict_mode.recommended_env({})
    assert rec["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"
    assert rec["SIMPLICIO_OPERATOR_ALWAYS_LATEST"] == "1"
    assert "SIMPLICIO_PRISM_SLOTS" in rec


def test_recommended_env_opt_out_minimal(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_ECONOMY_PARALLEL", "0")
    monkeypatch.setattr(
        strict_mode,
        "fast_status",
        lambda env=None: {"operational": False, "present": False, "version": ""},
    )
    rec = strict_mode.recommended_env({})
    assert rec["SIMPLICIO_LOOP"] == "1"
    # minimal path still prefers auto fan-out + always-latest
    assert rec["SIMPLICIO_LOOP_AUTO_FAN_OUT"] == "1"


def test_persist_posix_rc_writes_idempotent_guarded_block(tmp_path, monkeypatch):
    monkeypatch.setattr(ep.Path, "home", staticmethod(lambda: tmp_path))
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("existing content\n", encoding="utf-8")
    sh_path = tmp_path / ".simplicio-loop" / "economy-parallel-env.sh"

    changed = ep.persist_posix_rc(sh_path)
    assert changed == [str(bashrc)]
    contents = bashrc.read_text(encoding="utf-8")
    assert ep._RC_MARK_BEGIN in contents
    assert str(sh_path) in contents
    assert contents.startswith("existing content\n")

    # Re-running is a no-op (idempotent): no duplicate blocks, nothing reported changed.
    changed_again = ep.persist_posix_rc(sh_path)
    assert changed_again == []
    assert bashrc.read_text(encoding="utf-8").count(ep._RC_MARK_BEGIN) == 1


def test_persist_posix_rc_falls_back_to_profile_when_no_rc_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ep.Path, "home", staticmethod(lambda: tmp_path))
    sh_path = tmp_path / ".simplicio-loop" / "economy-parallel-env.sh"

    changed = ep.persist_posix_rc(sh_path)
    assert changed == [str(tmp_path / ".profile")]


def test_profile_status_explains_not_applied_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(ep.Path, "home", staticmethod(lambda: tmp_path))
    payload = ep.profile_status(env={})
    assert payload["aligned"] is False
    assert payload["drift_reason"] == "not_applied"
    assert "apply" in payload["drift_fix"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX rc persistence only")
def test_apply_then_new_shell_status_is_aligned(tmp_path, monkeypatch):
    """Regression for #1289: apply must persist so a NEW shell sees aligned=true."""
    monkeypatch.setattr(ep.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".bashrc").write_text("", encoding="utf-8")

    result = ep.persist_user_profile(set_windows_user_env=False)
    assert result["ok"] is True
    assert result["rc_files_changed"] == [str(tmp_path / ".bashrc")]

    repo_root = Path(__file__).resolve().parents[1]
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(repo_root)}
    out = subprocess.run(
        ["bash", "-ic", f"{sys.executable} -m simplicio_loop.cli_impl economy status --json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert out.returncode in (0, 1), out.stderr
    import json as _json

    payload = _json.loads(out.stdout)
    assert payload["aligned"] is True, payload.get("drift_keys")
