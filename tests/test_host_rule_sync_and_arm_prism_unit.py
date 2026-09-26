"""host_rule_sync + arm_drain_prism unit tests."""

from __future__ import annotations

from pathlib import Path

import host_rule_sync
import arm_drain_prism


def test_host_rule_sync_writes_project_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMPLICIO_HOME", str(tmp_path / "home"))
    # force module home via env already set for global; only project target
    receipt = host_rule_sync.sync(do_global=False, target=tmp_path / "repo")
    assert receipt["ok"] is True
    assert receipt["count"] >= 1
    rule = tmp_path / "repo" / ".claude" / "rules" / "simplicio-loop-operator-flow.md"
    assert rule.is_file()
    text = rule.read_text(encoding="utf-8")
    assert "SIMPLICIO_LOOP_STRICT" in text
    assert "simplicio-mapper" in text


def test_host_rule_sync_global_env_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("SIMPLICIO_HOME", str(home))
    monkeypatch.setenv("HOME", str(home))
    # host_rule_sync._home uses SIMPLICIO_HOME first
    receipt = host_rule_sync.sync(do_global=True, target=None)
    assert receipt["ok"] is True
    env_sh = home / ".simplicio" / "loop-env.sh"
    assert env_sh.is_file()
    env_text = env_sh.read_text(encoding="utf-8")
    assert "SIMPLICIO_LOOP_STRICT=1" in env_text
    assert "SIMPLICIO_EXECUTION_PROFILE=standalone" in env_text
    assert "SIMPLICIO_REQUIRE_MCP" not in env_text
    assert "SIMPLICIO_MCP_FORCE" not in env_text
    assert "SIMPLICIO_LOOP_REQUIRE_RUNTIME" not in env_text
    grok_rule = home / ".grok" / "rules" / "simplicio-loop-operator-flow.md"
    assert grok_rule.is_file()


def test_arm_drain_prism_writes_scratchpad(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    receipt = arm_drain_prism.arm(repo, slots=3, max_iterations=50, promise="done-when-empty")
    assert receipt["ok"] is True
    assert receipt["prism_slots"] == 3
    assert receipt["prism_logical_capacity"] == 30
    assert receipt["prism_batch_size"] == 10
    assert receipt["prism_wave_barrier"] == "reconcile-before-next"
    scratch = Path(receipt["scratchpad"])
    assert scratch.is_file()
    body = scratch.read_text(encoding="utf-8")
    assert "mode: drain" in body
    assert "prism_slots: 3" in body
    assert "forbid_hand_edit: true" in body
    assert "done-when-empty" in body


def test_arm_drain_prism_honors_explicit_batch_size(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setattr(arm_drain_prism, "_open_issue_count", lambda _repo: None)
    receipt = arm_drain_prism.arm(repo, slots=3, batch_size=30, max_iterations=50, promise="done")
    assert receipt["prism_batch_size"] == 30
    assert receipt["prism_eligibility"]["reason_code"] == "source_unavailable"
