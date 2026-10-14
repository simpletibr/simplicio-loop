"""web_verify point: the real proc.run and sandbox.wrap (no-bwrap test mode) around a fake worker, real git."""
import asyncio
import json
import subprocess
import sys

import pytest

from simplicio_loop.watcher247 import sandbox
from simplicio_loop.watcher247.points import _scripts, web_verify

from .evidence_helpers import fake_worker, init_repo, write

URL = "http://127.0.0.1:3000/"


@pytest.fixture(autouse=True)
def no_bwrap(monkeypatch):
    """The sandbox has its own tests: here the argv is wrapped for real but runs without bwrap."""
    monkeypatch.setenv("SIMPLICIO_247_ALLOW_UNSANDBOXED", "1")
    monkeypatch.setattr(sandbox, "engine", lambda *a, **k: None)
    monkeypatch.setenv("GH_TOKEN", "super-secret")


@pytest.fixture
def clone(tmp_path):
    return init_repo(tmp_path / "clone", {"app.py": "x = 1\n", "ui/page.html": "<p>a</p>\n"})


@pytest.fixture
def worker(tmp_path, monkeypatch):
    def install(exit_code=0, produces="ISSUE-web.png"):
        script = fake_worker(tmp_path / "web_verify.py", exit_code=exit_code, produces=produces)
        monkeypatch.setattr(_scripts, "script_path", lambda name: script)
        return script
    return install


@pytest.fixture
def ctx(make_ctx, clone, tmp_path):
    return make_ctx(clone=clone, run_dir=tmp_path / "run", state_dir=tmp_path / "state", issue={"number": 7})


def run(ctx):
    return asyncio.run(web_verify.run(ctx))


def test_ok_with_untracked_frontend_file(ctx, clone, worker, monkeypatch):
    worker()
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, {"ui/new.tsx": "export {}\n"})
    result = run(ctx)
    assert result.status == "ok", result
    assert result.evidence["screenshot"].endswith("7-web.png")
    recorded = json.loads((ctx.run_dir / "web_verify" / "argv.json").read_text())
    assert recorded["argv"][:5] == ["run", "--url", URL, "--issue", "7"]
    assert recorded["gh_token"] is None  # scrubbed_env: the watcher's tokens do not reach the worker


def test_ok_with_modified_tracked_frontend_file(ctx, clone, worker, monkeypatch):
    worker()
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, {"ui/page.html": "<p>b</p>\n"})
    assert run(ctx).status == "ok"


@pytest.mark.parametrize("changes", [{}, {"app.py": "x = 2\n"}, {"notes.txt": "hi\n"}])
def test_not_applicable_without_frontend_change(ctx, clone, worker, monkeypatch, changes):
    worker()
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, changes)
    result = run(ctx)
    assert (result.status, result.reason_code) == ("skipped", "not_applicable")
    assert not (ctx.run_dir / "web_verify").exists()


def test_committed_frontend_change_is_not_a_working_tree_change(ctx, clone, worker, monkeypatch):
    from .evidence_helpers import git
    worker()
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, {"ui/page.html": "<p>c</p>\n"})
    git(clone, "commit", "-qam", "fe")
    assert run(ctx).reason_code == "not_applicable"


def test_no_url_is_skipped_not_faked(ctx, clone, worker, monkeypatch):
    worker()
    monkeypatch.delenv(web_verify.URL_ENV, raising=False)
    write(clone, {"ui/new.tsx": "export {}\n"})
    result = run(ctx)
    assert (result.status, result.reason_code) == ("skipped", "no_url")
    assert not (ctx.run_dir / "web_verify").exists()


@pytest.mark.parametrize("code, reason", [(1, "web_verify_failed"), (2, "web_verify_error"), (3, "web_verify_blocked")])
def test_nonzero_exit_is_error(ctx, clone, worker, monkeypatch, code, reason):
    worker(exit_code=code)
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, {"ui/new.tsx": "export {}\n"})
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", reason)
    assert result.evidence["return_code"] == code


def test_exit_zero_without_screenshot_is_error(ctx, clone, worker, monkeypatch):
    worker(produces=None)
    monkeypatch.setenv(web_verify.URL_ENV, URL)
    write(clone, {"ui/new.tsx": "export {}\n"})
    result = run(ctx)
    assert (result.status, result.reason_code) == ("error", "no_screenshot")


def test_not_a_git_repo_is_error(make_ctx, tmp_path, worker):
    worker()
    plain = tmp_path / "plain"
    plain.mkdir()
    result = run(make_ctx(clone=plain, run_dir=tmp_path / "run"))
    assert (result.status, result.reason_code) == ("error", "git_failed")


def test_missing_pieces_are_skipped(make_ctx, tmp_path, clone, monkeypatch):
    assert run(make_ctx()).reason_code == "no_clone"
    assert run(make_ctx(clone=clone)).reason_code == "no_run_dir"
    monkeypatch.setattr(_scripts, "script_path", lambda name: None)
    assert run(make_ctx(clone=clone, run_dir=tmp_path / "run")).reason_code == "script_unavailable"


def test_applies_needs_a_clone(make_ctx, clone):
    assert web_verify.applies(make_ctx(clone=clone)) is True
    assert web_verify.applies(make_ctx()) is False


def test_contract(point_contract, make_ctx, clone, tmp_path):
    result = point_contract("web_verify", make_ctx(clone=clone, run_dir=tmp_path / "run"), expect="skipped")
    assert result.reason_code == "not_applicable"


def test_real_script_has_the_subcommand_and_pattern():
    script = _scripts.script_path("web_verify.py")
    assert script is not None
    done = subprocess.run([sys.executable, str(script), "nosuchcommand"], capture_output=True, text=True)
    assert done.returncode == 2
    assert "run" in done.stdout.split("choices:")[1].split()
    assert _scripts.frontend_files(["a.tsx", "b.py"]) == ["a.tsx"]
