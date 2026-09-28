"""ZERO PROBES: mapper/dev-cli capability probes run at most once per run_root."""
from __future__ import annotations

import subprocess

from simplicio_loop import runner as runner_mod


def _mapper_completed(argv, **_kwargs):
    if "--version" in argv:
        return subprocess.CompletedProcess(argv, 0, "simplicio-mapper 0.30.0\n", "")
    return subprocess.CompletedProcess(
        argv, 0, "Public agent verbs: scan, inspect, handoff, ask, sync.\n"
        "--goal --task-file --task-fingerprint\n", "",
    )


def test_preflight_mapper_probes_once_per_run_root(tmp_path, monkeypatch):
    runner_mod.reset_capability_probe_cache()
    repo = tmp_path / "repo"
    run_root = tmp_path / "run"
    repo.mkdir()
    run_root.mkdir()
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON", raising=False)

    calls: list[list[str]] = []
    real_run_cmd = runner_mod._run_cmd

    def fake_run_cmd(argv, cwd):
        if argv and argv[0] == "simplicio-mapper":
            calls.append(list(argv))
            return _mapper_completed(argv)
        return real_run_cmd(argv, cwd)

    monkeypatch.setattr(runner_mod, "_run_cmd", fake_run_cmd)

    for _ in range(5):
        receipt = runner_mod._preflight_mapper(repo, run_root)
        assert receipt["version_ok"] is True

    # 2 subprocess calls total (--version, --help) across 5 task-attempts, not 10.
    assert len(calls) == 2


def test_preflight_mapper_recomputes_repo_state_every_call(tmp_path, monkeypatch):
    runner_mod.reset_capability_probe_cache()
    repo = tmp_path / "repo"
    run_root = tmp_path / "run"
    repo.mkdir()
    run_root.mkdir()
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON", raising=False)
    monkeypatch.setattr(runner_mod, "_run_cmd", lambda argv, cwd: _mapper_completed(argv))

    fingerprints = iter([{"tree_hash": "a"}, {"tree_hash": "b"}])
    monkeypatch.setattr(runner_mod, "_repo_fingerprint", lambda _repo: next(fingerprints))

    first = runner_mod._preflight_mapper(repo, run_root)
    second = runner_mod._preflight_mapper(repo, run_root)
    assert first["repo_state"] == {"tree_hash": "a"}
    assert second["repo_state"] == {"tree_hash": "b"}


def test_preflight_mapper_cache_is_scoped_per_run_root(tmp_path, monkeypatch):
    runner_mod.reset_capability_probe_cache()
    repo = tmp_path / "repo"
    repo.mkdir()
    run_a = tmp_path / "run-a"
    run_b = tmp_path / "run-b"
    run_a.mkdir()
    run_b.mkdir()
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_MAPPER_PREFLIGHT_JSON", raising=False)

    calls: list[list[str]] = []
    real_run_cmd = runner_mod._run_cmd

    def fake_run_cmd(argv, cwd):
        if argv and argv[0] == "simplicio-mapper":
            calls.append(list(argv))
            return _mapper_completed(argv)
        return real_run_cmd(argv, cwd)

    monkeypatch.setattr(runner_mod, "_run_cmd", fake_run_cmd)

    runner_mod._preflight_mapper(repo, run_a)
    runner_mod._preflight_mapper(repo, run_a)
    runner_mod._preflight_mapper(repo, run_b)

    # run_a: 2 calls cached across its 2 attempts; run_b probes fresh: +2 calls.
    assert len(calls) == 4


def test_preflight_operator_uses_in_process_manifest_with_zero_subprocess_calls(tmp_path, monkeypatch):
    runner_mod.reset_capability_probe_cache()
    repo = tmp_path / "repo"
    run_root = tmp_path / "run"
    repo.mkdir()
    run_root.mkdir()
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON", raising=False)

    manifest = {
        "schema": "simplicio.dev-cli.capabilities/v1",
        "top_level_flags": ["--help", "-h"],
        "package": {"name": "simplicio-cli", "version": "0.18.16"},
        "commands": {
            "edit": {
                "flags": ["--plan", "--apply", "--dry-run", "--json"],
                "help": "apply an edit plan",
            },
        },
    }

    class _FakeCapabilitiesModule:
        @staticmethod
        def load_capabilities_manifest():
            return manifest

    monkeypatch.setitem(__import__("sys").modules, "simplicio.capabilities", _FakeCapabilitiesModule())
    # _devcli_env()'s PATH-candidate resolution is a separate, pre-existing concern
    # (which `simplicio-dev-cli` on PATH to use) -- stub it so this test isolates
    # only the --help/--version capability-probe subprocesses this change removes.
    monkeypatch.setattr(runner_mod, "_devcli_command_path", lambda: "simplicio-dev-cli")

    calls = []
    real_subprocess_run = runner_mod.subprocess.run

    def fake_subprocess_run(*a, **k):
        argv = a[0] if a else k.get("args")
        if argv and "simplicio-dev-cli" in str(argv[0]):
            calls.append((a, k))
            raise AssertionError("no capability-probe subprocess expected")
        return real_subprocess_run(*a, **k)

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_subprocess_run)

    for _ in range(3):
        receipt = runner_mod._preflight_operator(repo, run_root)
        assert receipt["version_ok"] is True
        assert receipt["missing_tokens"] == []
        assert receipt["missing_capabilities"] == []

    assert calls == []


def test_preflight_operator_fails_closed_with_no_legacy_fallback(tmp_path, monkeypatch):
    """No backward-compat layer (repo rule): when neither the in-process manifest
    nor `capabilities --json` resolves, block with a typed reason instead of
    falling back to the legacy --help/--version subprocess probe."""
    runner_mod.reset_capability_probe_cache()
    repo = tmp_path / "repo"
    run_root = tmp_path / "run"
    repo.mkdir()
    run_root.mkdir()
    monkeypatch.delenv("SIMPLICIO_LOOP_FAKE_DEVCLI_PREFLIGHT_JSON", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "simplicio.capabilities", None)
    monkeypatch.setattr(runner_mod, "_devcli_command_path", lambda: "simplicio-dev-cli")

    calls = []
    real_subprocess_run = runner_mod.subprocess.run

    def fake_subprocess_run(*a, **k):
        argv = a[0] if a else k.get("args")
        calls.append(list(argv) if argv else [])
        if argv and "capabilities" in argv and "--json" in argv:
            return subprocess.CompletedProcess(argv, 1, "", "no such command")
        raise AssertionError(f"no legacy --help/--version probe expected, got {argv}")

    monkeypatch.setattr(runner_mod.subprocess, "run", fake_subprocess_run)

    with __import__("pytest").raises(runner_mod.DevCliCapabilitiesUnavailableError) as excinfo:
        runner_mod._preflight_operator(repo, run_root)

    assert excinfo.value.reason_code == "devcli_capabilities_unavailable"
    assert "simplicio-loop>=3.43.17" in str(excinfo.value)
    # Exactly one subprocess call (`capabilities --json`), never the legacy triple.
    assert len(calls) == 1
