"""video_evidence point: the real proc.run and sandbox.wrap (no-bwrap test mode) around a fake worker."""
import asyncio
import json
import subprocess
import sys

import pytest

from simplicio_loop.watcher247 import sandbox
from simplicio_loop.watcher247.points import _scripts, video_evidence

from .evidence_helpers import fake_worker, init_repo


@pytest.fixture(autouse=True)
def no_bwrap(monkeypatch):
    monkeypatch.setenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", "1")
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    monkeypatch.setenv("GH_TOKEN", "super-secret")
    monkeypatch.setenv(video_evidence.ENABLE_ENV, "1")


@pytest.fixture
def worker(tmp_path, monkeypatch):
    def install(exit_code=0, produces="evidence-ISSUE.mp4"):
        script = fake_worker(tmp_path / "video_evidence.py", exit_code=exit_code, produces=produces)
        monkeypatch.setattr(_scripts, "script_path", lambda name: script)
    return install


@pytest.fixture
def ctx(make_ctx, tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "web_verify").mkdir(parents=True)
    (run_dir / "web_verify" / "7-web.png").write_bytes(b"png")
    return make_ctx(clone=init_repo(tmp_path / "clone", {"a.py": "x\n"}), run_dir=run_dir,
                    issue={"number": 7, "title": "Fix login"})


def run(ctx):
    return asyncio.run(video_evidence.run(ctx))


def test_ok_calls_the_real_verify_arguments(ctx, worker):
    worker()
    result = run(ctx)
    assert result.status == "ok", result
    assert result.evidence["artifact"].endswith("evidence-7.mp4")
    recorded = json.loads((ctx.run_dir / "video_evidence" / "argv.json").read_text())
    argv = recorded["argv"]
    assert argv[:3] == ["verify", "--engine", "hyperframes"]
    assert argv[argv.index("--frames") + 1] == str(ctx.run_dir / "web_verify")
    assert argv[argv.index("--title") + 1] == "Fix login"
    assert recorded["gh_token"] is None  # scrubbed_env


@pytest.mark.parametrize("code, reason", [(1, "video_evidence_failed"), (2, "video_evidence_error"),
                                          (3, "video_evidence_blocked")])
def test_nonzero_exit_is_error(ctx, worker, code, reason):
    worker(exit_code=code)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", reason)
    assert result.evidence["return_code"] == code


def test_exit_zero_without_video_is_error(ctx, worker):
    worker(produces=None)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", "no_video")


def test_missing_pieces_are_skipped(make_ctx, ctx, tmp_path, monkeypatch):
    assert run(make_ctx()).reason_code == "no_clone"
    assert run(make_ctx(clone=ctx.clone)).reason_code == "no_run_dir"
    empty = make_ctx(clone=ctx.clone, run_dir=tmp_path / "empty")
    assert run(empty).reason_code == "no_screenshots"
    monkeypatch.setattr(_scripts, "script_path", lambda name: None)
    assert run(ctx).reason_code == "script_unavailable"


def test_applies_needs_the_env_flag_and_screenshots(ctx, make_ctx, tmp_path, monkeypatch):
    assert video_evidence.applies(ctx) is True
    assert video_evidence.applies(make_ctx(run_dir=tmp_path / "empty")) is False
    assert video_evidence.applies(make_ctx()) is False
    monkeypatch.delenv(video_evidence.ENABLE_ENV)
    assert video_evidence.applies(ctx) is False


def test_contract(point_contract, ctx, monkeypatch):
    monkeypatch.delenv(video_evidence.ENABLE_ENV)
    result = point_contract("video_evidence", ctx, expect="skipped")
    assert result.reason_code == "not_applicable"


def test_real_script_has_the_subcommand():
    script = _scripts.script_path("video_evidence.py")
    assert script is not None
    done = subprocess.run([sys.executable, str(script), "nosuchcommand"], capture_output=True, text=True)
    assert done.returncode == 2
    assert "verify" in done.stdout.split("choices:")[1].split()
    assert "generate" not in done.stdout.split("choices:")[1].split()
