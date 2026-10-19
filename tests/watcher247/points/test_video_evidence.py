"""video_evidence point: the real proc.run and sandbox.wrap (no-bwrap test mode) around a fake worker.

The default engine records the running app with Playwright (`verify --url`) for a front-end change. hyperframes (the
slideshow of the web_verify screenshots) runs only when the work item explicitly asks for a video.
"""
import asyncio
import json
import subprocess
import sys

import pytest

from simplicio_loop.watcher247 import sandbox
from simplicio_loop.watcher247.points import _scripts, video_evidence

from .evidence_helpers import fake_worker, init_repo, write

URL = "http://127.0.0.1:3000/login"


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
    return make_ctx(clone=init_repo(tmp_path / "clone", {"a.py": "x\n", "ui/page.html": "<p>a</p>\n"}), run_dir=run_dir,
                    issue={"number": 7, "title": "Fix login", "body": "The login button does nothing."})


def frontend_change(ctx):
    write(ctx.clone, {"ui/login.tsx": "export {}\n"})


def explainer(ctx, make_ctx):
    """The same run, for a work item that explicitly asks for an explainer video."""
    return make_ctx(clone=ctx.clone, run_dir=ctx.run_dir,
                    issue={"number": 7, "title": "Login", "body": "make an explainer video of the login screen"})


def run(ctx):
    return asyncio.run(video_evidence.run(ctx))


def recorded_argv(ctx) -> list[str]:
    return json.loads((ctx.run_dir / "video_evidence" / "argv.json").read_text())["argv"]


def test_the_default_engine_records_the_app_with_playwright(ctx, worker, monkeypatch):
    worker()
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    frontend_change(ctx)
    result = run(ctx)
    assert result.status == "ok", result
    argv = recorded_argv(ctx)
    assert argv[:3] == ["verify", "--url", URL]  # Playwright is the default engine: no --engine, no --frames
    assert "--engine" not in argv and "--frames" not in argv
    assert argv[argv.index("--name") + 1] == "evidence" and argv[argv.index("--issue") + 1] == "7"
    assert result.evidence["artifact"].endswith("evidence-7.mp4")
    assert json.loads((ctx.run_dir / "video_evidence" / "argv.json").read_text())["gh_token"] is None  # scrubbed_env


def test_the_playwright_recording_is_the_webm_when_ffmpeg_did_not_convert_it(ctx, worker, monkeypatch):
    worker(produces="evidence-ISSUE-pw/video.webm")
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    frontend_change(ctx)
    result = run(ctx)
    assert result.status == "ok", result
    assert result.evidence["artifact"].endswith("evidence-7-pw/video.webm")


def test_hyperframes_runs_only_when_the_work_item_explicitly_asks_for_a_video(ctx, make_ctx, worker, monkeypatch):
    worker()
    monkeypatch.setenv(video_evidence.URL_ENV, URL)  # a URL is there, but the explainer uses the screenshots
    asked = explainer(ctx, make_ctx)
    result = run(asked)
    assert result.status == "ok", result
    argv = recorded_argv(asked)
    assert argv[:3] == ["verify", "--engine", "hyperframes"]
    assert argv[argv.index("--frames") + 1] == str(ctx.run_dir / "web_verify")
    assert "--url" not in argv


def test_the_explicit_explainer_needs_the_web_verify_screenshots(ctx, make_ctx, worker, tmp_path):
    worker()
    empty = make_ctx(clone=ctx.clone, run_dir=tmp_path / "empty", issue=explainer(ctx, make_ctx).issue)
    assert run(empty).reason_code == "no_screenshots"


def test_the_default_engine_needs_the_app_url(ctx, worker, monkeypatch):
    worker()
    monkeypatch.delenv(video_evidence.URL_ENV, raising=False)
    frontend_change(ctx)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("skipped", "no_url")
    assert not (ctx.run_dir / "video_evidence").exists()


def test_the_default_engine_is_not_applicable_without_a_frontend_change(ctx, worker, monkeypatch):
    worker()
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    result = run(ctx)  # the clone holds only its committed files
    assert (result.status, result.reason_code) == ("skipped", "not_applicable")
    assert not (ctx.run_dir / "video_evidence").exists()


@pytest.mark.parametrize("code, reason", [(1, "video_evidence_failed"), (2, "video_evidence_error"),
                                          (3, "video_evidence_blocked")])
def test_nonzero_exit_is_error(ctx, worker, monkeypatch, code, reason):
    worker(exit_code=code)
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    frontend_change(ctx)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", reason)
    assert result.evidence["return_code"] == code


def test_exit_zero_without_a_recording_is_error(ctx, worker, monkeypatch):
    worker(produces=None)
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    frontend_change(ctx)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", "no_video")


def test_missing_pieces_are_skipped(make_ctx, ctx, tmp_path, monkeypatch):
    monkeypatch.setenv(video_evidence.URL_ENV, URL)
    frontend_change(ctx)
    assert run(make_ctx()).reason_code == "no_clone"
    assert run(make_ctx(clone=ctx.clone)).reason_code == "no_run_dir"
    monkeypatch.setattr(_scripts, "script_path", lambda name: None)
    assert run(ctx).reason_code == "script_unavailable"


def test_applies_needs_the_env_flag_and_a_run_dir(ctx, make_ctx, monkeypatch):
    assert video_evidence.applies(ctx) is True
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


def test_the_real_request_matcher_is_what_routes_to_hyperframes():
    real = _scripts.load_script("video_evidence.py")
    assert real.is_video_request("make an explainer video of the login screen")
    assert not real.is_video_request("fix the login timeout bug and add a unit test")
