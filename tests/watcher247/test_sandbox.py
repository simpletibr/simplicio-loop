"""Sandbox: scrubbed env, argv wrapping (bwrap), and the refusal with no sandbox."""
from __future__ import annotations

from pathlib import Path

import pytest

from simplicio_loop.watcher247 import sandbox

CLONE = Path("/var/lib/simplicio-loop-247/work/simplicio-a")
STATE = Path("/var/lib/simplicio-loop-247")
TURBO = ["simplicio-loop", "turbo", "--repo", str(CLONE), "--provider", "openrouter", "--task", "t"]
ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/home/simplicio-loop",
    "GH_TOKEN": "gh-secret",
    "GITHUB_TOKEN": "gh-secret-2",
    "OPENAI_API_KEY": "openai-secret",
    "AWS_SECRET_ACCESS_KEY": "aws-secret",
    "OPENROUTER_API_KEY": "or-secret",
    "SIMPLICIO_247_STATE_DIR": "/var/lib/simplicio-loop-247",
}


def only(names):
    def which(binary):
        return f"/usr/bin/{binary}" if binary in names else None
    return which


def test_scrubbed_env_keeps_only_the_allowlist(tmp_path):
    env = sandbox.scrubbed_env(ENV, home=tmp_path)
    assert set(env) <= set(sandbox.ALLOWED_ENV) | {"HOME", "SIMPLICIO_LOOP_DAEMON"}
    assert env["PATH"] == "/usr/bin:/bin" and env["LANG"] == "C.UTF-8"
    assert env["HOME"] == str(tmp_path)


def test_scrubbed_env_keeps_the_sandboxed_command_away_from_the_daemon(tmp_path):
    assert sandbox.scrubbed_env({"SIMPLICIO_LOOP_DAEMON": "1"}, home=tmp_path)["SIMPLICIO_LOOP_DAEMON"] == "0"


def test_scrubbed_env_drops_every_token(tmp_path):
    env = sandbox.scrubbed_env(ENV, home=tmp_path)
    blob = " ".join(env.values())
    for secret in ("gh-secret", "openai-secret", "aws-secret", "or-secret"):
        assert secret not in blob
    assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env


def test_scrubbed_env_passes_only_explicitly_needed_keys(tmp_path):
    env = sandbox.scrubbed_env(ENV, home=tmp_path, keep=("OPENROUTER_API_KEY",))
    assert env["OPENROUTER_API_KEY"] == "or-secret"
    assert "GH_TOKEN" not in env


def test_scrubbed_env_supplies_a_default_path(tmp_path):
    env = sandbox.scrubbed_env({}, home=tmp_path)
    assert env["PATH"] == sandbox.DEFAULT_PATH


def test_wrap_with_bwrap_is_read_only_except_clone_and_state(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap"}))
    state = tmp_path / "state"  # not the host's real state dir: wrap looks for the watcher's control files in it
    argv = sandbox.wrap(TURBO, clone=CLONE, state_dir=state, platform="linux", environ={})
    assert argv[0] == "bwrap"
    assert argv[argv.index("--ro-bind") + 1:argv.index("--ro-bind") + 3] == ["/", "/"]
    binds = [argv[i + 1] for i, a in enumerate(argv) if a == "--bind"]
    assert binds == [str(state), str(CLONE)]  # the clone last: nothing read-only may cover it
    assert argv[argv.index("--chdir") + 1] == str(CLONE)
    assert "--die-with-parent" in argv and "--new-session" in argv
    assert argv[argv.index("--") + 1:] == TURBO


def test_wrap_of_an_items_worktree_binds_exactly_in_this_order(monkeypatch, tmp_path):
    """state dir rw, then the whole work dir ro (the other items' worktrees and the base clones), then the item's own clone rw."""
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap"}))
    state = tmp_path / "state"
    clone = state / "work" / "demo.wt" / "31"
    common = state / "work" / "demo" / ".git"
    for folder in (clone, common / "worktrees" / "31", common / "objects", common / "simplicio"):
        folder.mkdir(parents=True)
    for name in ("claims.json", "budget.json", "STOP"):
        (state / name).write_text("{}")
    argv = sandbox.wrap(TURBO, clone=clone, state_dir=state, platform="linux", environ={})
    assert argv == [
        "bwrap", "--ro-bind", "/", "/", "--unshare-pid", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
        "--bind", str(state), str(state),
        "--ro-bind", str(state / "claims.json"), str(state / "claims.json"),
        "--ro-bind", str(state / "budget.json"), str(state / "budget.json"),
        "--ro-bind", str(state / "STOP"), str(state / "STOP"),
        "--ro-bind", str(state / "work"), str(state / "work"),
        "--bind", str(clone), str(clone),
        "--bind", str(common / "worktrees" / "31"), str(common / "worktrees" / "31"),
        "--bind", str(common / "objects"), str(common / "objects"),
        "--bind", str(common / "simplicio"), str(common / "simplicio"),
        "--chdir", str(clone), "--die-with-parent", "--new-session", "--", *TURBO,
    ]


def test_wrap_of_a_plain_clone_makes_nothing_read_only_but_the_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap"}))
    argv = sandbox.wrap(TURBO, clone=CLONE, state_dir=tmp_path, platform="linux", environ={})
    assert [argv[i + 1] for i, a in enumerate(argv) if a == "--ro-bind"] == ["/"]


def test_wrap_uses_bwrap_when_present(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap", "systemd-run"}))
    argv = sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="linux", environ={})
    assert argv[0] == "bwrap"


def test_systemd_run_alone_is_not_a_sandbox(monkeypatch):
    # A --user --scope rejects ProtectSystem/ReadWritePaths ("Unknown assignment", rc=1) and a user-manager
    # service does not enforce them reliably, so bwrap is the only engine.
    monkeypatch.setattr(sandbox.shutil, "which", only({"systemd-run"}))
    assert sandbox.engine(platform="linux") is None
    assert sandbox.refusal({}, platform="linux") == "sandbox_unavailable"
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="linux", environ={})


def test_refuses_without_any_sandbox(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only(set()))
    with pytest.raises(sandbox.SandboxUnavailable) as caught:
        sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="linux", environ={})
    assert caught.value.reason_code == "sandbox_unavailable"


def test_refuses_off_linux_even_if_bwrap_exists(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap"}))
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="darwin", environ={})


def test_unsandboxed_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only(set()))
    argv = sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="linux",
                        environ={"SIMPLICIO_247_ALLOW_UNSANDBOXED": "1"})
    assert argv == TURBO


def test_opt_in_must_be_exactly_one(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only(set()))
    with pytest.raises(sandbox.SandboxUnavailable):
        sandbox.wrap(TURBO, clone=CLONE, state_dir=STATE, platform="linux",
                     environ={"SIMPLICIO_247_ALLOW_UNSANDBOXED": "yes"})


def test_refusal_reason_is_none_when_a_sandbox_exists(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only({"bwrap"}))
    assert sandbox.refusal(platform="linux", environ={}) is None


def test_refusal_reason_names_the_missing_sandbox(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", only(set()))
    assert sandbox.refusal(platform="linux", environ={}) == "sandbox_unavailable"
    assert sandbox.refusal(platform="linux", environ={"SIMPLICIO_247_ALLOW_UNSANDBOXED": "1"}) is None
